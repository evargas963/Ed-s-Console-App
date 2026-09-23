"""Row retention (FIFO by age): delete rows older than a cutoff from a named table
(RC-REHAB-3, 2026-09-23).

Scope, per the operator-approved plan: `complete_chain_captures`, `production_decision_records`,
`calibration_decision_log` only. NEVER `snapshots` (feeds live similarity search / "The Call" --
retention deferred pending a measured accuracy-impact study) and NEVER
`model_execution_identities` (its own DB triggers refuse UPDATE/DELETE outright -- this script
would simply fail loudly against it, which is correct, not a bug to work around).

Runs in small batches, each its own transaction, so a large delete never holds one long-running
write lock against the live app. Dry-run by default: reports exactly how many rows and how many
bytes (real column-length sum, not an estimate) a real run would remove, with no writes.

Does NOT vacuum. A DELETE alone does not shrink the file (SQLite keeps the freed pages in its own
freelist for reuse) -- reclaiming disk space is a separate, deliberate step
(tools/db_maintenance.py's own docstring already explains why a naive VACUUM needs ~2x the file's
size in free disk; the incremental_vacuum path is the follow-up, not this script's job).

Usage:
    python tools/apply_row_retention_v1.py --table complete_chain_captures \\
        --ts-column ts_utc --retention-days 30 [--execute] [--db PATH]
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

DEFAULT_BATCH_SIZE = 500

#: The only tables this script will touch. Anything else is refused outright -- retention
#: windows are a per-table judgment call (see module docstring), never a blanket policy.
ALLOWED_TABLES = frozenset({
    "complete_chain_captures",
    "production_decision_records",
    "calibration_decision_log",
})


def apply_retention(
    db_path: Path | str,
    *,
    table: str,
    ts_column: str,
    retention_days: float,
    now_ts: float | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = True,
) -> dict:
    """Delete rows from `table` where `ts_column` < (now - retention_days).

    Returns a summary dict: table, cutoff_ts, rows_would_delete/rows_deleted, batches_run.
    `dry_run=True` (the default) counts exactly what a real run would remove, with no writes.
    """
    if table not in ALLOWED_TABLES:
        raise ValueError(
            f"refusing table {table!r}: not in the operator-approved retention scope "
            f"{sorted(ALLOWED_TABLES)} (see this script's own module docstring for why)"
        )
    cutoff = (now_ts if now_ts is not None else time.time()) - retention_days * 86400.0  # caps-ok: now_ts is a test-injection clock; production callers omit it and get the real wall clock
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    summary = {
        "table": table, "ts_column": ts_column, "cutoff_ts": cutoff,
        "dry_run": dry_run, "rows_affected": 0, "batches_run": 0,
    }
    try:
        while True:
            if dry_run:
                (n,) = conn.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE "{ts_column}" < ?', (cutoff,)
                ).fetchone()
                summary["rows_affected"] = int(n)
                # Same count the real loop below would run: full batches plus the final short one
                # (which may be empty). The old `1 if n else 0` reported one batch for any backlog.
                summary["batches_run"] = int(n) // batch_size + 1
                break
            cur = conn.execute(
                f'DELETE FROM "{table}" WHERE rowid IN '
                f'(SELECT rowid FROM "{table}" WHERE "{ts_column}" < ? LIMIT ?)',
                (cutoff, batch_size),
            )
            conn.commit()
            summary["batches_run"] += 1
            summary["rows_affected"] += cur.rowcount
            if cur.rowcount < batch_size:
                break
    finally:
        conn.close()
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", required=True, choices=sorted(ALLOWED_TABLES))
    ap.add_argument("--ts-column", required=True)
    ap.add_argument("--retention-days", type=float, required=True)
    ap.add_argument("--db", default=None, help="defaults to the canonical ed_console.db")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    ap.add_argument("--execute", action="store_true",
                     help="actually delete rows (default is dry-run report only)")
    args = ap.parse_args()

    db_path = Path(args.db) if args.db else canonical_console_db_path()
    result = apply_retention(
        db_path, table=args.table, ts_column=args.ts_column,
        retention_days=args.retention_days, batch_size=args.batch_size,
        dry_run=not args.execute,
    )
    verb = "would delete" if result["dry_run"] else "deleted"
    print(f"table={result['table']} cutoff_ts={result['cutoff_ts']:.0f} "
          f"{verb} {result['rows_affected']} rows across {result['batches_run']} batches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
