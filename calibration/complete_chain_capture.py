"""Canonical persistence for the COMPLETE vendor options-chain capture, one expiry at a
time — distinct from option_chain_morning_full.py (near-term MULTI-expiry, gated to a
once-daily morning window, tuned width) and from the bounded ANALYTICAL chain snapshots
in `snapshots.option_chain_json` (gamma/terrain width, one row per refresh). Neither of
those tables is a record of what contracts actually existed for a ticker+expiry — this one
is, and only this one carries `completeness_basis`, the machine-readable record of WHY a
given capture is believed complete (not merely wide).

Written from the SAME live single-expiry fetch that serves GET /api/chain
(server.get_chain) — no separate scheduled job, no second producer duplicating the fetch.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any

from instrument_identity import ticker_storage_key

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS complete_chain_captures (
    ticker TEXT NOT NULL,
    expiry TEXT NOT NULL,
    ts_utc REAL NOT NULL,
    spot REAL,
    n_contracts INTEGER NOT NULL,
    completeness_basis TEXT NOT NULL,
    chain_json TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'schwab_chain_strike_range_all',
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (ticker, expiry, ts_utc)
);
CREATE INDEX IF NOT EXISTS idx_complete_chain_captures_latest
    ON complete_chain_captures(ticker, expiry, ts_utc DESC);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(TABLE_SQL)
    conn.commit()


def persist_complete_chain_capture(
    db_path: Path | str,
    *,
    ticker: str,
    expiry: str,
    contracts: list[Any],
    spot: float | None,
    completeness_basis: str,
    ts_utc: float | None = None,
    source: str = "schwab_chain_strike_range_all",
) -> dict[str, Any]:
    """Append one COMPLETE single-expiry capture. A time series (PRIMARY KEY includes
    ts_utc), not an idempotent once-a-day row — every successful live complete fetch
    banks its own capture, so `latest_complete_chain_capture` always answers "what did
    the vendor actually list, as of the most recent proof."

    FAIL CLOSED: no contracts, or an unproven `completeness_basis`, writes NOTHING and
    says why — a persisted row with an empty or unverifiable completeness claim would be
    worse than no row, since a caller trusts what THIS table alone claims to be complete.
    """
    tk = ticker_storage_key(ticker)
    if not tk:
        return {"status": "skipped", "reason": "no_ticker"}
    exp = str(expiry or "").strip()[:10]
    if not exp:
        return {"status": "skipped", "reason": "no_expiry"}
    if not completeness_basis:
        return {"status": "skipped", "reason": "no_completeness_basis"}
    clean = [dict(c) for c in (contracts or []) if isinstance(c, dict)]
    if not clean:
        return {"status": "skipped", "reason": "no_contracts", "ticker": tk, "expiry": exp}

    ts = float(ts_utc if ts_utc is not None else time.time())
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    try:
        ensure_schema(conn)
        conn.execute(
            "INSERT OR REPLACE INTO complete_chain_captures "
            "(ticker, expiry, ts_utc, spot, n_contracts, completeness_basis, chain_json, source) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (tk, exp, ts,
             float(spot) if spot is not None and math.isfinite(float(spot)) else None,
             len(clean), str(completeness_basis),
             json.dumps(clean, default=str), str(source)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "written", "ticker": tk, "expiry": exp, "ts_utc": ts,
            "n_contracts": len(clean), "completeness_basis": completeness_basis}


def latest_complete_chain_capture(
    db_path: Path | str, ticker: str, expiry: str
) -> dict[str, Any] | None:
    """Newest banked COMPLETE capture for (ticker, expiry), or None.

    Fail-closed: a missing file, a missing table, an unparseable payload, or an empty
    contract list all return None — absence must reach the caller as absence, never
    substitute a different expiry or a narrower book silently.
    """
    path = Path(db_path)
    if not path.is_file():
        return None
    tk = ticker_storage_key(ticker)
    exp = str(expiry or "").strip()[:10]
    if not tk or not exp:
        return None
    try:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='complete_chain_captures'"
        ).fetchone():
            return None
        row = conn.execute(
            "SELECT ts_utc, spot, n_contracts, completeness_basis, chain_json, source "
            "FROM complete_chain_captures WHERE ticker=? AND expiry=? "
            "ORDER BY ts_utc DESC LIMIT 1",
            (tk, exp),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row:
        return None
    try:
        contracts = json.loads(row[4])
    except (TypeError, ValueError):
        return None
    if not isinstance(contracts, list) or not contracts:
        return None
    return {"ticker": tk, "expiry": exp, "ts_utc": float(row[0]), "spot": row[1],
            "n_contracts": int(row[2]), "completeness_basis": row[3],
            "contracts": contracts, "source": str(row[5])}
