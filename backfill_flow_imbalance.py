#!/usr/bin/env python3
"""
Recompute flow_imbalance (and smart_money_score / direction) from archived option_chain_json.

Uses per-strike buckets from compute_exposures_by_strike(require_oi=False) so OI=0 legs
still contribute volume / sizes when present.

When archived rows lack bidSize/askSize, flow_imbalance falls back to call vs put volume
near ATM (see math_probabilities.flow_imbalance_normalized_with_fallback).

Gate (default, not --force)
---------------------------
Only rows where flow_imbalance IS NULL OR = 0 are updated. This is intentional:

  - Idempotent reruns: won’t overwrite values you may have filled from the live path.
  - Safer for mixed pipelines: avoids clobbering non-zero flows if chain_json was
    trimmed or spot drifted vs chain capture time (rare, but possible).

It is not universal “best practice” — it’s a conservative default. For canonical truth
from option_chain_json only, run with --force (optionally after db_health_audit.py).

After updates, snapshots_1m_normalized is refreshed automatically when rows are written
(normalized_training_sync.ensure_normalized_training_table).

Usage:
  python backfill_flow_imbalance.py
  python backfill_flow_imbalance.py --dry-run
  python backfill_flow_imbalance.py --force
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from db import get_snapshot_sql
from math_exposure_core import compute_exposures_by_strike
from math_probabilities import (
    compute_smart_money_signal,
    flow_imbalance_normalized_with_fallback,
)
from timeframe_config import CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME

ROOT = Path(__file__).resolve().parent


def _contracts_from_chain_json(raw: str) -> list[dict]:
    try:
        arr = json.loads(raw)
    except Exception:
        return []
    if not isinstance(arr, list):
        return []
    out: list[dict] = []
    for ct in arr:
        if not isinstance(ct, dict):
            continue
        out.append(
            {
                "strikePrice": ct.get("strikePrice"),
                "putCall": ct.get("putCall"),
                "openInterest": ct.get("openInterest"),
                "totalVolume": ct.get("totalVolume") or ct.get("volume") or 0,
                "bidSize": ct.get("bidSize"),
                "askSize": ct.get("askSize"),
                "delta": ct.get("delta"),
                "gamma": ct.get("gamma"),
                "vega": ct.get("vega"),
                "volatility": ct.get("volatility"),
                "daysToExpiration": ct.get("daysToExpiration"),
                "multiplier": ct.get("multiplier") or 100,
                "expirationDate": ct.get("expirationDate"),
            }
        )
    return out


def backfill(
    db_path: Path,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, int]:
    conn = sqlite3.connect(str(db_path), timeout=120)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    q = get_snapshot_sql("backfill_flow_imbalance.py:select_candidates")
    if not force:
        q += " AND (flow_imbalance IS NULL OR flow_imbalance = 0)"
    rows = cur.execute(q, (CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME)).fetchall()

    updated = 0
    skipped = 0
    by_src: dict[str, int] = {"book": 0, "volume": 0, "none": 0}

    pending: list[tuple] = []

    for r in rows:
        sid = int(r["snapshot_id"])
        try:
            spot = float(r["spot"])
        except (TypeError, ValueError):
            skipped += 1
            continue
        if spot <= 0:
            skipped += 1
            continue
        contracts = _contracts_from_chain_json(r["option_chain_json"])
        if len(contracts) < 3:
            skipped += 1
            continue
        exposures, _diag = compute_exposures_by_strike(
            contracts, spot=spot, require_oi=False
        )
        flow_norm, src = flow_imbalance_normalized_with_fallback(exposures, spot)
        by_src[src] = by_src.get(src, 0) + 1
        sm = compute_smart_money_signal(exposures, spot, window_pts=3.0)
        sm_score = sm.get("score")
        sm_dir = sm.get("direction")

        pending.append((flow_norm, sm_score, sm_dir, sid))
        if len(pending) >= 400:
            if not dry_run:
                cur.executemany(
                    """
                    UPDATE snapshots SET
                        flow_imbalance = ?,
                        smart_money_score = ?,
                        smart_money_direction = ?
                    WHERE snapshot_id = ?
                    """,
                    pending,
                )
                conn.commit()
            updated += len(pending)
            pending = []

    if pending:
        if not dry_run:
            cur.executemany(
                """
                UPDATE snapshots SET
                    flow_imbalance = ?,
                    smart_money_score = ?,
                    smart_money_direction = ?
                WHERE snapshot_id = ?
                """,
                pending,
            )
            conn.commit()
        updated += len(pending)

    conn.close()

    if not dry_run and updated > 0:
        from normalized_training_sync import ensure_normalized_training_table

        ensure_normalized_training_table(db_path, force=False)

    return {
        "rows_considered": len(rows),
        "rows_updated": updated,
        "rows_skipped": skipped,
        "flow_source_book": by_src.get("book", 0),
        "flow_source_volume": by_src.get("volume", 0),
        "flow_source_none": by_src.get("none", 0),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill flow_imbalance from option_chain_json")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="Recompute even when flow_imbalance is non-zero")
    ap.add_argument(
        "--rematerialize",
        action="store_true",
        help="Deprecated: normalized refresh runs automatically when rows are updated.",
    )
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="backfill_flow_imbalance", write_capable=True)
    if not args.db.exists():
        raise SystemExit(f"DB not found: {args.db}")
    stats = backfill(args.db, dry_run=args.dry_run, force=args.force)
    print("backfill_flow_imbalance:", stats)


if __name__ == "__main__":
    main()
