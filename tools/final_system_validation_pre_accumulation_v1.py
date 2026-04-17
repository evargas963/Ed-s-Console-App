#!/usr/bin/env python3
"""
Read-only bundle for docs/final_system_validation_pre_accumulation.md.
Uses current DB + EdDB.get_similar_setups (canonical path).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from db import EdDB, get_snapshot_sql
from timeframe_config import CANONICAL_TIMEFRAME


def _gap_analysis(conn: sqlite3.Connection, ticker: str) -> dict:
    """Largest gaps between consecutive ts_utc for 1m snapshots (one ticker sample)."""
    rows = conn.execute(
        get_snapshot_sql("tools/final_system_validation_pre_accumulation_v1.py:26"),
        (ticker, CANONICAL_TIMEFRAME),
    ).fetchall()
    ts = [float(r[0]) for r in rows if r[0] is not None]
    if len(ts) < 2:
        return {"ticker": ticker, "n": len(ts), "max_gap_sec": None, "median_gap_sec": None}
    gaps = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
    return {
        "ticker": ticker,
        "n": len(ts),
        "max_gap_sec": max(gaps),
        "median_gap_sec": float(statistics.median(gaps)) if gaps else None,
        "p95_gap_sec": float(sorted(gaps)[int(0.95 * (len(gaps) - 1))]) if len(gaps) > 1 else gaps[0],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--json-out", type=Path, default=None)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="tools.final_system_validation_pre_accumulation_v1", write_capable=False)
    conn = sqlite3.connect(str(args.db), timeout=120)
    conn.row_factory = sqlite3.Row
    now = time.time()

    n1m = conn.execute(
        get_snapshot_sql("tools/final_system_validation_pre_accumulation_v1.py:56"), (CANONICAL_TIMEFRAME,)
    ).fetchone()["n"]
    zone_null = conn.execute(
        get_snapshot_sql("tools/final_system_validation_pre_accumulation_v1.py:59"),
        (CANONICAL_TIMEFRAME,),
    ).fetchone()["n"]
    zones = conn.execute(
        get_snapshot_sql("tools/final_system_validation_pre_accumulation_v1.py:66"),
        (CANONICAL_TIMEFRAME,),
    ).fetchall()

    ts_bounds = conn.execute(
        get_snapshot_sql("tools/final_system_validation_pre_accumulation_v1.py:75"),
        (CANONICAL_TIMEFRAME,),
    ).fetchone()

    top_ticker = conn.execute(
        get_snapshot_sql("tools/final_system_validation_pre_accumulation_v1.py:83"),
        (CANONICAL_TIMEFRAME,),
    ).fetchone()

    gap = _gap_analysis(conn, top_ticker["ticker"]) if top_ticker else {}

    # Issue 19 style: pick pin_bull with dense ticker SPY if present
    pick = conn.execute(
        get_snapshot_sql("tools/final_system_validation_pre_accumulation_v1.py:95"),
        (CANONICAL_TIMEFRAME,),
    ).fetchone()

    issue19 = {"picked_row": None, "similar_count": 0, "match_tier_sample": None, "error": None}
    if pick:
        db = EdDB(
            args.db,
            allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)),
        )
        try:
            rows = db.get_similar_setups(
                ticker=pick["ticker"],
                timeframe=CANONICAL_TIMEFRAME,
                zone="pin_bull",
                vwap_side=pick["vwap_side"] or "above",
                nearest_above_dist=pick["nearest_above_dist"],
                nearest_below_dist=pick["nearest_below_dist"],
                n_similar=500,
            )
            issue19["picked_row"] = {
                "ticker": pick["ticker"],
                "zone": pick["zone"],
                "vwap_side": pick["vwap_side"],
                "nearest_above_dist": pick["nearest_above_dist"],
                "nearest_below_dist": pick["nearest_below_dist"],
                "cohort_size_hint": int(pick["c"]),
            }
            issue19["similar_count"] = len(rows)
            if rows:
                issue19["match_tier_sample"] = rows[0].get("match_tier")
        except Exception as e:
            issue19["error"] = repr(e)

    # Tier SQL counts for same anchor (mirror db tier 1/2 shape — count only)
    tier1 = tier2 = None
    if pick and not issue19.get("error"):
        from math_exposure import bucket_hi, bucket_lo, dist_bucket

        t = pick["ticker"].upper().strip()
        nad, nbd = pick["nearest_above_dist"], pick["nearest_below_dist"]
        ab, bb = dist_bucket(nad), dist_bucket(nbd)
        alo, ahi = bucket_lo(ab), bucket_hi(ab)
        blo, bhi = bucket_lo(bb), bucket_hi(bb)
        tier1 = conn.execute(
            get_snapshot_sql("tools/final_system_validation_pre_accumulation_v1.py:144"),
            (t, CANONICAL_TIMEFRAME, "pin_bull", pick["vwap_side"], nad, alo, ahi, nbd, blo, bhi),
        ).fetchone()["n"]
        tier2 = conn.execute(
            get_snapshot_sql("tools/final_system_validation_pre_accumulation_v1.py:154"),
            (t, CANONICAL_TIMEFRAME, "pin_bull", pick["vwap_side"], nad, alo, ahi),
        ).fetchone()["n"]

    issue19["tier1_sql_count"] = int(tier1) if tier1 is not None else None
    issue19["tier2_sql_count"] = int(tier2) if tier2 is not None else None

    n5m = conn.execute(get_snapshot_sql("tools/final_system_validation_pre_accumulation_v1.py:167")).fetchone()["n"]

    bars = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%bar%'"
    ).fetchall()]

    conn.close()

    report = {
        "schema": "final_system_validation_pre_accumulation_v1",
        "generated_ts_utc": now,
        "db_path": str(args.db.resolve()),
        "phase1_1m_pipeline": {
            "snapshots_1m_total": int(n1m),
            "zone_null_or_empty_1m": int(zone_null),
            "ts_utc_min": ts_bounds["tmin"],
            "ts_utc_max": ts_bounds["tmax"],
            "distinct_zones": [{"zone": r["z"], "count": int(r["c"])} for r in zones],
            "top_ticker_by_volume": dict(top_ticker) if top_ticker else None,
            "continuity_sample_gap_stats_sec": gap,
        },
        "phase2_issue19_pin_bull": issue19,
        "phase4_legacy": {
            "snapshots_5m_total": int(n5m),
            "note": "Issue 19 SQL binds timeframe=? as CANONICAL_TIMEFRAME from callers; 5m rows not selected by parameter.",
        },
        "phase3_bar_tables": bars,
    }
    text = json.dumps(report, indent=2, default=str) + "\n"
    print(text)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
