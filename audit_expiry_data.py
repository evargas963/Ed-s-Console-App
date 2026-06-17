#!/usr/bin/env python3
"""
audit_expiry_data.py — Audit snapshots for bad expiry data from the 2026-03-12 bug

Run: python audit_expiry_data.py

Identifies rows with:
  - dte < 0 (expiry was in the past when snapshot was taken)
  - expiry date before snapshot date
  - hours_to_expiry NULL when dte=0 (same-day expiry, expected after 4pm ET)

No changes are made. Outputs a report and optional DELETE SQL (commented).
"""

import sys
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent))

from db import get_db, DB_PATH, get_snapshot_sql
from timeframe_config import CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME

_TF2 = (CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME)


def main():
    db = get_db()

    print("=" * 70)
    print("EXPIRY DATA AUDIT — Ed Console Snapshots")
    print(f"DB: {DB_PATH}")
    print("=" * 70)

    with db._connect() as conn:
        # ── 1. Rows with DTE < 0 ─────────────────────────────────────────────
        bad_dte = conn.execute(
            get_snapshot_sql("audit_expiry_data.py:37"),
            _TF2,
        ).fetchone()[0]

        print(f"\n1. Rows with DTE < 0 (expired options): {bad_dte}")

        if bad_dte > 0:
            by_ticker = conn.execute(
                get_snapshot_sql("audit_expiry_data.py:48"),
                _TF2,
            ).fetchall()
            print("   By ticker:")
            for r in by_ticker:
                print(f"      {r[0]}: {r[1]}")

            sample = conn.execute(
                get_snapshot_sql("audit_expiry_data.py:61"),
                _TF2,
            ).fetchall()
            print("   Sample (5 most recent):")
            for r in sample:
                print(f"      id={r[0]} {r[1]} expiry={r[2]} dte={r[3]} "
                      f"hrs_exp={r[4]} ts={r[5]}")

        # ── 2. Rows where expiry < snapshot date ─────────────────────────────
        # (catches any format edge cases; expiry stored as YYYY-MM-DD)
        bad_expiry_vs_ts = conn.execute(
            get_snapshot_sql("audit_expiry_data.py:78"),
            _TF2,
        ).fetchone()[0]

        print(f"\n2. Rows where expiry < snapshot date: {bad_expiry_vs_ts}")

        # ── 3. Total snapshots (for %) ───────────────────────────────────────
        total = conn.execute(
            get_snapshot_sql("audit_expiry_data.py:91"),
            _TF2,
        ).fetchone()[0]
        print(f"\n3. Total snapshots (timeframe IN 1m/5m): {total}")

        bad_count = bad_dte  # primary metric
        if total > 0:
            pct = round(100 * bad_count / total, 1)
            print(f"   Bad rows (dte<0): {pct}% of total")

        # ── 4. Date range of bad data ─────────────────────────────────────────
        if bad_dte > 0:
            range_rows = conn.execute(
                get_snapshot_sql("audit_expiry_data.py:104"),
                _TF2,
            ).fetchone()
            print(f"\n4. Bad data date range: {range_rows[0]} — {range_rows[1]}")

        # ── 5. Distinct bad expiry values ────────────────────────────────────
        if bad_dte > 0:
            expiries = conn.execute(
                get_snapshot_sql("audit_expiry_data.py:116"),
                _TF2,
            ).fetchall()
            print("\n5. Distinct expiries with dte<0:")
            for r in expiries:
                print(f"      {r[0]}: {r[1]} rows")

    print("\n" + "=" * 70)
    if bad_dte > 0:
        print("RECOMMENDATION: Exclude or delete rows with dte<0 for prediction/training.")
        print("\nTo DELETE bad rows (run manually if desired):")
        _sn = "snapshots"
        print(f"  sqlite3 {DB_PATH} \"DELETE FROM {_sn} WHERE dte < 0;\"")
        print("\nOr in Python:")
        print("  with db._connect() as conn:")
        print(f"      conn.execute('DELETE FROM {_sn} WHERE dte < 0')")
        print("      conn.commit()")
    else:
        print("No bad expiry rows found — DB looks clean.")
    print("=" * 70)


if __name__ == "__main__":
    main()
