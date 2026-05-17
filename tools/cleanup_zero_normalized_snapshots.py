#!/usr/bin/env python3
"""Dry-run or delete contaminated snapshot rows (candle_open == 0.0, spot == 0.0)."""

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


def _report_table_contamination(
    conn: sqlite3.Connection, table: str, column: str, label: str
) -> int:
    if not _table_exists(conn, table):
        print(f"Table {table} does not exist.")
        return 0
    if column not in _table_column_set(conn, table):
        print(f"Table {table} has no column {column}; skipping {label}.")
        return 0

    total = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {column} = 0.0"
    ).fetchone()[0]
    print(f"\n{label} ({table}.{column} = 0.0): {total}")
    if total == 0:
        return 0

    print("  By ticker:")
    for row in conn.execute(
        f"""
        SELECT ticker, COUNT(*) AS cnt
        FROM {table}
        WHERE {column} = 0.0
        GROUP BY ticker
        ORDER BY cnt DESC, ticker
        """
    ):
        print(f"    {row['ticker']}: {row['cnt']}")

    bounds = conn.execute(
        f"""
        SELECT MIN(ts_utc) AS min_ts, MAX(ts_utc) AS max_ts
        FROM {table}
        WHERE {column} = 0.0
        """
    ).fetchone()
    print(f"  ts_utc range: {bounds['min_ts']} .. {bounds['max_ts']}")
    return int(total)


def _table_column_set(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def report_contamination(db_path: Path) -> int:
    conn = _connect(db_path)
    try:
        total = 0
        total += _report_table_contamination(
            conn,
            "snapshots_1m_normalized",
            "candle_open",
            "Normalized candle contamination",
        )
        total += _report_table_contamination(
            conn,
            "snapshots",
            "spot",
            "Raw snapshot spot contamination",
        )
        return total
    finally:
        conn.close()


def apply_cleanup(db_path: Path) -> int:
    conn = _connect(db_path)
    deleted = 0
    try:
        if _table_exists(conn, "snapshots_1m_normalized"):
            cur = conn.execute(
                "DELETE FROM snapshots_1m_normalized WHERE candle_open = 0.0"
            )
            deleted += cur.rowcount
        if _table_exists(conn, "snapshots") and "spot" in _table_column_set(
            conn, "snapshots"
        ):
            cur = conn.execute("DELETE FROM snapshots WHERE spot = 0.0")
            deleted += cur.rowcount
        conn.commit()
        print(f"Deleted {deleted} contaminated row(s) total.")
        return deleted
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report or delete rows with candle_open=0.0 or snapshots.spot=0.0"
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
