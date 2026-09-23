"""Backfill: gzip-compress existing JSON blob columns written before json_blob_codec
existed (RC-REHAB-3, 2026-09-23).

Runs in small batches, each its own transaction, so it never holds a long-running write
lock against the live app. Idempotent and resumable: every batch re-selects rows whose
blob column is NOT already gzip (json_blob_codec.is_compressed_blob), so stopping and
re-running this script picks up exactly where it left off, and running it twice does no
extra work the second time.

Read-modify-write per row (not a bulk UPDATE), because compression is a Python-side
operation -- SQLite has no built-in gzip. Each row's own primary key columns identify it
for the UPDATE, so this is safe to run table-by-table, and column-by-column within a
table (a table can have several independent blob columns, backfilled one at a time).

Usage:
    python tools/backfill_json_blob_compression_v1.py --table complete_chain_captures \\
        --blob-column chain_json --key-columns ticker,expiry,ts_utc [--dry-run] [--db PATH]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db_authority import canonical_console_db_path
from json_blob_codec import encode_json_blob, is_compressed_blob, decode_json_blob

DEFAULT_BATCH_SIZE = 200


def backfill_table_column(
    db_path: Path | str,
    *,
    table: str,
    blob_column: str,
    key_columns: list[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = True,
    sleep_between_batches_sec: float = 0.0,
) -> dict:
    """Compress every not-yet-compressed row of `table`.`blob_column`, in batches keyed
    by `key_columns` (must uniquely identify a row -- the table's real primary key).

    Returns a summary dict: rows_scanned, rows_compressed, bytes_before, bytes_after,
    batches_run. `dry_run=True` (the default) does everything except the UPDATE/commit,
    so it reports the exact same numbers a real run would affect."""
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    key_list = ", ".join(f'"{c}"' for c in key_columns)
    where_clause = " AND ".join(f'"{c}" = ?' for c in key_columns)
    summary = {
        "table": table, "blob_column": blob_column, "dry_run": dry_run,
        "rows_scanned": 0, "rows_compressed": 0,
        "bytes_before": 0, "bytes_after": 0, "batches_run": 0,
    }
    try:
        rowid_cursor = 0
        while True:
            rows = conn.execute(
                f'SELECT rowid, {key_list}, "{blob_column}" FROM "{table}" '
                f"WHERE rowid > ? ORDER BY rowid LIMIT ?",
                (rowid_cursor, batch_size),
            ).fetchall()
            if not rows:
                break
            summary["batches_run"] += 1
            to_update: list[tuple] = []
            for row in rows:
                # RC-REHAB-3 bugfix (2026-09-23): row["rowid"] fails for a table whose
                # primary key is an INTEGER PRIMARY KEY column (e.g.
                # calibration_decision_log.id) -- SQLite treats that column as a rowid
                # ALIAS, so the driver reports the selected `rowid` expression under the
                # alias's own name ("id"), not literally "rowid"; sqlite3.Row.keys()
                # confirms this live: both the rowid and id selections come back named
                # "id". `rowid` genuinely is a separate, distinctly-named hidden column
                # only for a table with a composite or non-integer primary key
                # (complete_chain_captures, option_chain_morning_full,
                # option_chain_accrual, production_decision_records all worked fine
                # under the old name-based lookup for exactly this reason). Positional
                # indexing sidesteps the alias collision entirely: rowid is always the
                # first selected column, whatever name SQLite reports for it.
                rowid_cursor = row[0]
                summary["rows_scanned"] += 1
                blob = row[blob_column]
                if blob is None or is_compressed_blob(blob):
                    continue
                # Round-trip through decode/encode (not a raw re-gzip of the bytes) so a
                # malformed legacy row fails LOUD here, in a controlled backfill, instead
                # of silently persisting garbage as "compressed."
                obj = decode_json_blob(blob)
                compressed = encode_json_blob(obj)
                before_len = len(blob) if isinstance(blob, (bytes, bytearray)) else len(blob.encode("utf-8"))
                summary["bytes_before"] += before_len
                summary["bytes_after"] += len(compressed)
                summary["rows_compressed"] += 1
                key_values = tuple(row[c] for c in key_columns)
                to_update.append((compressed, *key_values))
            if to_update and not dry_run:
                conn.executemany(
                    f'UPDATE "{table}" SET "{blob_column}" = ? WHERE {where_clause}',
                    to_update,
                )
                conn.commit()
            if sleep_between_batches_sec:
                time.sleep(sleep_between_batches_sec)
    finally:
        conn.close()
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", required=True)
    ap.add_argument("--blob-column", required=True)
    ap.add_argument("--key-columns", required=True, help="comma-separated primary-key column names")
    ap.add_argument("--db", default=None, help="defaults to the canonical ed_console.db")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    ap.add_argument("--sleep-between-batches-sec", type=float, default=0.05,
                     help="throttle so this never competes hard with the live app")
    ap.add_argument("--execute", action="store_true",
                     help="actually write compressed rows (default is dry-run report only)")
    args = ap.parse_args()

    db_path = Path(args.db) if args.db else canonical_console_db_path()
    key_columns = [c.strip() for c in args.key_columns.split(",") if c.strip()]

    result = backfill_table_column(
        db_path, table=args.table, blob_column=args.blob_column, key_columns=key_columns,
        batch_size=args.batch_size, dry_run=not args.execute,
        sleep_between_batches_sec=args.sleep_between_batches_sec,
    )
    print(f"table={result['table']} column={result['blob_column']} "
          f"dry_run={result['dry_run']} batches={result['batches_run']} "
          f"scanned={result['rows_scanned']} compressed={result['rows_compressed']}")
    if result["bytes_before"]:
        ratio = result["bytes_before"] / max(result["bytes_after"], 1)
        saved_mb = (result["bytes_before"] - result["bytes_after"]) / 1e6
        print(f"bytes_before={result['bytes_before']} bytes_after={result['bytes_after']} "
              f"ratio={ratio:.1f}x saved={saved_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
