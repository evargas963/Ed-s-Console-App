#!/usr/bin/env python3
"""
clean_db.py — Delete bad snapshots from the SQLite database.

Removes rows with:
  - dte < 0 (expired options)
  - dte IS NULL AND expiry < snapshot date

Run: python clean_db.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from db import get_db, get_snapshot_sql
from timeframe_config import CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME

_TF2 = (CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME)


def main():
    db = get_db()

    DELETE_SQL = get_snapshot_sql("clean_db.py:delete")

    VERIFY_SQL = get_snapshot_sql("clean_db.py:verify")

    with db._connect() as conn:
        # Step 1: Delete bad rows (atomic transaction)
        cur = conn.execute(DELETE_SQL, _TF2)
        deleted = cur.rowcount
        conn.commit()

        # Step 2: Verify deletion
        bad_remaining = conn.execute(VERIFY_SQL, _TF2).fetchone()[0]
        total = conn.execute(
            get_snapshot_sql("clean_db.py:52"),
            _TF2,
        ).fetchone()[0]

    # Step 3: Print summary
    print(f"Bad rows deleted: {deleted}")
    print(f"Clean rows remaining: {total}")
    print(f"DB is clean: {bad_remaining == 0}")


if __name__ == "__main__":
    main()
