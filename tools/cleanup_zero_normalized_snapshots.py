#!/usr/bin/env python3
"""Dry-run or delete contaminated snapshots_1m_normalized rows (candle_open == 0.0)."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import DB_PATH, configure_sqlite_connection  # noqa: E402


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def report_contamination(db_path: Path) -> int:
    conn = _connect(db_path)
    try:
        if not _table_exists(conn, "snapshots_1m_normalized"):
            print("Table snapshots_1m_normalized does not exist.")
            return 0

        total = conn.execute(
            "SELECT COUNT(*) FROM snapshots_1m_normalized WHERE candle_open = 0.0"
        ).fetchone()[0]
        print(f"Contaminated rows (candle_open = 0.0): {total}")
        if total == 0:
            return 0

        print("\nBy ticker:")
        for row in conn.execute(
            """
            SELECT ticker, COUNT(*) AS cnt
            FROM snapshots_1m_normalized
            WHERE candle_open = 0.0
            GROUP BY ticker
            ORDER BY cnt DESC, ticker
            """
        ):
            print(f"  {row['ticker']}: {row['cnt']}")

        bounds = conn.execute(
            """
            SELECT MIN(ts_utc) AS min_ts, MAX(ts_utc) AS max_ts
            FROM snapshots_1m_normalized
            WHERE candle_open = 0.0
            """
        ).fetchone()
        print(f"\nts_utc range: {bounds['min_ts']} .. {bounds['max_ts']}")
        return int(total)
    finally:
        conn.close()


def apply_cleanup(db_path: Path) -> int:
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "DELETE FROM snapshots_1m_normalized WHERE candle_open = 0.0"
        )
        conn.commit()
        deleted = cur.rowcount
        print(f"Deleted {deleted} contaminated row(s).")
        return deleted
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report or delete snapshots_1m_normalized rows with candle_open=0.0"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help=f"SQLite database path (default: {DB_PATH})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete contaminated rows (default: dry-run count only)",
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"ERROR: database not found: {args.db}", file=sys.stderr)
        return 1

    count = report_contamination(args.db)
    if args.apply:
        if count == 0:
            print("\n--apply: nothing to delete.")
            return 0
        print("\n--apply: deleting rows ...")
        apply_cleanup(args.db)
    else:
        print("\nDry-run only. Pass --apply to delete these rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
