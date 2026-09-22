#!/usr/bin/env python3
"""
Compute required bar rehydration range for pin_neutral repair cohort (read-only SQL).

Usage:
  python tools/issue19_rehydration_range_v1.py --db data/ed_console.db
  python tools/issue19_rehydration_range_v1.py --db data/ed_console.db --json-out data/issue19_rehydration_range_last.json
"""
from __future__ import annotations

from db import get_snapshot_sql


import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1, OUTCOME_BAR_SPECS
from timeframe_config import CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME

FORWARD_PAD_SEC = float(max(s[2] for s in OUTCOME_BAR_SPECS)) * 60.0 + 120.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--json-out", type=Path, default=None)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="tools.issue19_rehydration_range_v1", write_capable=False)

    import sqlite3

    conn = sqlite3.connect(str(args.db.resolve()))
    conn.row_factory = sqlite3.Row

    g = conn.execute(
        "SELECT MIN(bar_start_ts_utc) AS mn, MAX(bar_end_ts_utc) AS mx FROM price_bars_1m"
    ).fetchone()
    global_min_bar_start = g["mn"]
    global_max_bar_end = g["mx"]

    cohort = conn.execute(
        get_snapshot_sql("tools/issue19_rehydration_range_v1.py:43"),
        (
            CANONICAL_TIMEFRAME,
            DERIVED_TIMEFRAME,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
        ),
    ).fetchall()

    bounds = conn.execute(
        get_snapshot_sql("tools/issue19_rehydration_range_v1.py:66"),
        (
            CANONICAL_TIMEFRAME,
            DERIVED_TIMEFRAME,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
        ),
    ).fetchone()

    cohort_min = float(bounds["cohort_min_ts"])
    cohort_max = float(bounds["cohort_max_ts"])
    latest_required_bar_end = cohort_max + FORWARD_PAD_SEC

    rows_out = []
    for r in cohort:
        tkr = r["ticker"]
        mn = float(r["min_snapshot_ts"])
        mx = float(r["max_snapshot_ts"])
        br = conn.execute(
            "SELECT MIN(bar_start_ts_utc) AS mn FROM price_bars_1m WHERE ticker = ?",
            (tkr,),
        ).fetchone()
        min_bar = br["mn"]
        if min_bar is None:
            gap_start = mn
            gap_end = float(global_min_bar_start) if global_min_bar_start is not None else None
            gap_sec = (gap_end - gap_start) if gap_end is not None else None
        else:
            mb = float(min_bar)
            # Bars exist but none with bar_end <= mn  => missing coverage is [mn downward] until we have bars; proxy: [mb - 60, mb] is first available bar period; missing epoch span from cohort activity start to mb
            gap_start = mn
            gap_end = mb
            gap_sec = max(0.0, mb - mn) if mb > mn else 0.0

        rows_out.append(
            {
                "ticker": tkr,
                "n_snapshots": int(r["n"]),
                "min_snapshot_ts_utc": mn,
                "max_snapshot_ts_utc": mx,
                "min_bar_start_ts_utc_in_db": min_bar,
                "gap_start_ts_utc": gap_start,
                "gap_end_ts_utc": gap_end,
                "gap_seconds_snapshot_min_to_min_bar_start": gap_sec,
                "gap_days": round(gap_sec / 86400.0, 4) if gap_sec is not None else None,
            }
        )

    out = {
        "schema": "issue19_rehydration_range_v1",
        "db_path": str(args.db.resolve()),
        "generated_ts_utc": time.time(),
        "forward_padding_sec": FORWARD_PAD_SEC,
        "cohort_min_snapshot_ts_utc": cohort_min,
        "cohort_max_snapshot_ts_utc": cohort_max,
        "latest_required_bar_coverage_ts_utc": latest_required_bar_end,
        "global_min_bar_start_ts_utc": global_min_bar_start,
        "global_max_bar_end_ts_utc": global_max_bar_end,
        "cohort_to_global_bar_gap_seconds": float(global_min_bar_start) - cohort_min
        if global_min_bar_start is not None
        else None,
        "cohort_to_global_bar_gap_days": round((float(global_min_bar_start) - cohort_min) / 86400.0, 4)
        if global_min_bar_start is not None
        else None,
        "per_ticker": rows_out,
    }

    txt = json.dumps(out, indent=2) + "\n"
    print(txt)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(txt, encoding="utf-8")

    conn.close()


if __name__ == "__main__":
    main()
