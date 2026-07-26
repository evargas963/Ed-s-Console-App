"""Mechanical completeness guard for the vendor-coercion lock's field set (RC-FAUCET).

OBSERVED (2026-07-26): the VENDOR_FIELDS set in tools/check_vendor_field_coercion.py was
hand-maintained, and reconciling it against every numeric option-contract leaf in real
captured chains proved it INCOMPLETE — 5 price/value leaves (breakEven, extrinsicValue,
high52Week, low52Week, percentChange) were missing, so the lock could not have caught a raw
float() on any of them. A hand list drifts silently; the vendor schema is the authority.

This test derives the truth from the DATA: it samples captured option chains from the
snapshots DB, collects every contract key whose values are overwhelmingly numeric, and
asserts each is either covered by VENDOR_FIELDS or explicitly listed in
EXCLUDED_NUMERIC_LEAVES. A new Schwab numeric field (or a drifted list) fails the build.

VALIDATED: run against the live snapshots DB on 2026-07-26 — after adding the 5 missing
leaves the reconciliation is exact. Skips (does not fail) when no DB is present (CI), so it
is a guard where data exists, never a false failure where it does not.
"""
from __future__ import annotations

import glob
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.check_vendor_field_coercion import EXCLUDED_NUMERIC_LEAVES, VENDOR_FIELDS


def _pick_db() -> str | None:
    dbs = [p for p in glob.glob(str(REPO / "data" / "*.db")) if os.path.getsize(p) > 100_000]
    if not dbs:
        return None
    for name in ("ed_console.db", "ed_console_claude.db"):
        for p in dbs:
            if Path(p).name == name:
                return p
    return max(dbs, key=os.path.getmtime)


def _numeric_leaves_from_chains(db: str, per_ticker: int = 40) -> dict[str, tuple[int, int]]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=20)
    con.row_factory = sqlite3.Row
    counts: dict[str, list[int]] = {}
    try:
        for t in ("SPY", "QQQ", "IWM"):
            ids = [r[0] for r in con.execute(
                "SELECT rowid FROM snapshots WHERE ticker=? AND option_chain_json IS NOT NULL "
                "AND length(option_chain_json)>500 ORDER BY rowid", (t,)).fetchall()]
            if not ids:
                continue
            for rid in ids[:: max(1, len(ids) // per_ticker)][:per_ticker]:
                row = con.execute("SELECT option_chain_json FROM snapshots WHERE rowid=?", (rid,)).fetchone()
                try:
                    cts = json.loads(row["option_chain_json"])
                except Exception:
                    continue
                for ct in cts[:80]:
                    if not isinstance(ct, dict):
                        continue
                    for k, v in ct.items():
                        num, nonnum = counts.setdefault(k, [0, 0])
                        if isinstance(v, bool):
                            counts[k][1] += 1
                        elif isinstance(v, (int, float)):
                            counts[k][0] += 1
                        else:
                            try:
                                float(v)
                                counts[k][0] += 1
                            except (TypeError, ValueError):
                                counts[k][1] += 1
    finally:
        con.close()
    return {k: (n, nn) for k, (n, nn) in counts.items()}


def test_vendor_fields_covers_every_numeric_contract_leaf():
    db = _pick_db()
    if db is None:
        pytest.skip("no snapshots DB present (CI); reconciliation guard runs where data exists")
    counts = _numeric_leaves_from_chains(db)
    if not counts:
        pytest.skip("no option chains found in snapshots DB")
    # a numeric leaf = key whose values are overwhelmingly numeric (>=10x non-numeric)
    numeric_leaves = {k for k, (num, nonnum) in counts.items() if num > 0 and num >= 10 * max(1, nonnum)}
    known = set(VENDOR_FIELDS) | set(EXCLUDED_NUMERIC_LEAVES)
    uncovered = sorted(numeric_leaves - known)
    assert not uncovered, (
        "Numeric option-contract leaf field(s) seen in real chains are neither in "
        "VENDOR_FIELDS (the coercion lock) nor EXCLUDED_NUMERIC_LEAVES: "
        f"{uncovered}. Add each price/greek leaf to VENDOR_FIELDS so the lock catches a raw "
        "float() on it, or list a non-price numeric (timestamp/id) in EXCLUDED_NUMERIC_LEAVES "
        "with a reason. The vendor schema is the authority — a hand-maintained list drifts."
    )
