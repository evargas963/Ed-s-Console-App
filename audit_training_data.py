#!/usr/bin/env python3
"""
audit_training_data.py — Audit raw snapshots table for data quality.

NOTE: This audits the raw snapshots table (live write path). For canonical 1m
training data quality and model readiness, use audit_model_readiness.py, which
reads from snapshots_1m_normalized.

Run: python audit_training_data.py

Reports:
  1. RTH row count (09:30–16:00 ET, weekdays only)
  2. Pre-market/after-hours row count
  3. Rows per date (last 30 days)
  4. Rows by signal (long, short, wait)
  5. 0DTE row count (dte = 0)
  6. Earliest and latest clean RTH snapshot date
  7. Distinct trading days with RTH data
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from db import DB_PATH, get_db, get_snapshot_sql
from timeframe_config import CANONICAL_TIMEFRAME

def main():
    db = get_db()

    print("=" * 70)
    print("TRAINING DATA AUDIT — Snapshots Table")
    print(f"DB: {DB_PATH}")
    print("=" * 70)

    with db._connect() as conn:
        # 1. RTH rows (09:30–16:00 ET, weekdays only)
        rth = conn.execute(
            get_snapshot_sql("audit_training_data.py:rth_row_count"),
            (CANONICAL_TIMEFRAME,),
        ).fetchone()[0]
        print(f"\n1. RTH rows (09:30–16:00 ET, weekdays): {rth:,}")

        # 2. Pre-market / after-hours rows
        pre_after = conn.execute(
            get_snapshot_sql("audit_training_data.py:62"),
            (CANONICAL_TIMEFRAME,),
        ).fetchone()[0]
        print(f"\n2. Pre-market/after-hours rows: {pre_after:,}")

        # 3. Rows per date (last 30 days)
        print("\n3. Rows per date (last 30 days):")
        rows = conn.execute(
            get_snapshot_sql("audit_training_data.py:73"),
            (CANONICAL_TIMEFRAME,),
        ).fetchall()
        for r in rows:
            print(f"   {r[0]}: {r[1]:,}")

        # 4. Rows where signal = long, short, wait
        print("\n4. Rows by rules_signal:")
        for sig in ('long', 'short', 'wait'):
            cnt = conn.execute(
                get_snapshot_sql("audit_training_data.py:90"),
                (CANONICAL_TIMEFRAME, sig),
            ).fetchone()[0]
            print(f"   {sig}: {cnt:,}")

        # 5. 0DTE rows (dte = 0)
        dte0 = conn.execute(
            get_snapshot_sql("audit_training_data.py:97"),
            (CANONICAL_TIMEFRAME,),
        ).fetchone()[0]
        print(f"\n5. 0DTE rows (dte = 0): {dte0:,}")

        # 6. Earliest and latest clean RTH snapshot date
        range_row = conn.execute(
            get_snapshot_sql("audit_training_data.py:clean_rth_date_range"),
            (CANONICAL_TIMEFRAME,),
        ).fetchone()
        earliest = range_row[0] or "—"
        latest = range_row[1] or "—"
        print(f"\n6. Clean RTH snapshot date range: {earliest} — {latest}")

        # 7. Distinct trading days with RTH data
        days = conn.execute(
            get_snapshot_sql("audit_training_data.py:distinct_rth_days"),
            (CANONICAL_TIMEFRAME,),
        ).fetchone()[0]
        print(f"\n7. Distinct trading days with RTH data: {days}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
