#!/usr/bin/env python3
"""
audit_gate_labels.py — Identify raw snapshots with potentially bad signal labels
due to the _validate_trade gate bug (fixed today).

Uses fusion fields to find rows that should have been blocked by validation gates.
Audits raw snapshots (live write path). For canonical 1m training data, see
audit_model_readiness.py (uses snapshots_1m_normalized).

Run: python audit_gate_labels.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from db import DB_PATH, get_db, get_snapshot_sql
from timeframe_config import CANONICAL_TIMEFRAME

def main():
    db = get_db()

    print("=" * 70)
    print("GATE LABEL AUDIT — Potentially Bad Signal Labels")
    print(f"DB: {DB_PATH}")
    print("=" * 70)

    with db._connect() as conn:
        # Total RTH rows (for percentage)
        rth_total = conn.execute(
            get_snapshot_sql("audit_gate_labels.py:rth_total"),
            (CANONICAL_TIMEFRAME,),
        ).fetchone()[0]

        # 1. Long + high reversal (reversal gate should have blocked)
        cond1 = conn.execute(
            get_snapshot_sql("audit_gate_labels.py:47"),
            (CANONICAL_TIMEFRAME,),
        ).fetchone()[0]

        # 2. Short + high continuation AND breakout (continuation+breakout gate should have blocked)
        cond2 = conn.execute(
            get_snapshot_sql("audit_gate_labels.py:56"),
            (CANONICAL_TIMEFRAME,),
        ).fetchone()[0]

        # 3. validation_passed = 1 but cond1 or cond2 (confirmed bad labels)
        cond3 = conn.execute(
            get_snapshot_sql("audit_gate_labels.py:68"),
            (CANONICAL_TIMEFRAME,),
        ).fetchone()[0]

        # 4. Percentage of total RTH rows
        potentially_bad = cond1 + cond2
        pct = (potentially_bad / rth_total * 100) if rth_total else 0
        pct3 = (cond3 / rth_total * 100) if rth_total else 0

        print(f"\n1. long + fusion_reversal > 0.50 (reversal gate should block): {cond1:,}")
        print(f"\n2. short + fusion_continuation > 0.45 AND fusion_breakout > 0.45: {cond2:,}")
        print(f"\n3. validation_passed=1 but above conditions true (confirmed bad): {cond3:,}")
        print(f"\n4. % of total RTH rows:")
        print(f"   Potentially bad (cond1+cond2): {pct:.2f}%")
        print(f"   Confirmed bad (cond3):         {pct3:.2f}%")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
