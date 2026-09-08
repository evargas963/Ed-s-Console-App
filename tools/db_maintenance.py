"""DB maintenance for the console SQLite DB — planner stats + WAL bound + integrity (RC-51).

The RC-49 DB adversarial audit found the ~30 GB live DB had NEVER been ANALYZE'd
(sqlite_stat1 empty), so the query planner runs on heuristics with no real selectivity
statistics, and there is no routine WAL checkpoint to bound the -wal file under long readers.

This is read-mostly and safe to run on the LIVE file (ideally with the app stopped so the
checkpoint can fully truncate). It NEVER drops data and NEVER VACUUMs (freelist is ~0% so a
VACUUM would reclaim nothing and needs 2x disk — that is a separate, deliberate decision):
  1. PRAGMA quick_check              -> integrity, report only (abort maintenance if not ok)
  2. ANALYZE                         -> populates sqlite_stat1 (planner gets real statistics)
  3. PRAGMA wal_checkpoint(TRUNCATE) -> folds -wal back into the DB and truncates it

Usage:  python tools/db_maintenance.py [db_path]      (default data/ed_console.db)
Exit 0 = maintenance ran; non-zero = aborted (integrity failed / file missing).
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time


def db_stats(conn: sqlite3.Connection) -> dict[str, int]:
    """Cheap structural stats — page/freelist counts and whether ANALYZE has run."""
    cur = conn.cursor()
    return {
        "page_count": cur.execute("PRAGMA page_count").fetchone()[0],
        "freelist_count": cur.execute("PRAGMA freelist_count").fetchone()[0],
        "stat1_rows": cur.execute("SELECT COUNT(*) FROM sqlite_stat1").fetchone()[0]
        if cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_stat1'").fetchone()
        else 0,
    }


def quick_check(conn: sqlite3.Connection) -> str:
    return conn.execute("PRAGMA quick_check").fetchone()[0]


def analyze(conn: sqlite3.Connection) -> None:
    """Populate sqlite_stat1 with real per-index selectivity statistics."""
    conn.execute("ANALYZE")
    conn.commit()


def wal_checkpoint_truncate(conn: sqlite3.Connection) -> tuple[int, int, int]:
    """Fold the -wal back into the DB and truncate it. Returns (busy, log_pages, checkpointed)."""
    row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    return (int(row[0]), int(row[1]), int(row[2])) if row else (0, 0, 0)


def run_maintenance(db_path: str) -> int:
    if not os.path.isfile(db_path):
        print(f"  [ABORT] file not found: {db_path}", flush=True)
        return 2
    size = os.path.getsize(db_path)
    print(f"DB maintenance: {db_path}  ({size / 1e9:.2f} GB)", flush=True)
    conn = sqlite3.connect(db_path, timeout=120)
    try:
        before = db_stats(conn)
        print(f"  before: page_count={before['page_count']:,} freelist={before['freelist_count']:,} "
              f"sqlite_stat1_rows={before['stat1_rows']}", flush=True)

        print("  [1] PRAGMA quick_check ...", flush=True)
        t = time.perf_counter()
        r = quick_check(conn)
        print(f"      {r}  ({time.perf_counter() - t:.1f}s)", flush=True)
        if r != "ok":
            print("  [ABORT] integrity not ok — running no maintenance on a suspect file", flush=True)
            return 3

        print("  [2] ANALYZE (planner statistics) ...", flush=True)
        t = time.perf_counter()
        analyze(conn)
        print(f"      done ({time.perf_counter() - t:.1f}s)", flush=True)

        print("  [3] PRAGMA wal_checkpoint(TRUNCATE) ...", flush=True)
        busy, log_pages, ckpt = wal_checkpoint_truncate(conn)
        print(f"      busy={busy} log_pages={log_pages} checkpointed={ckpt}", flush=True)

        after = db_stats(conn)
        print(f"  after:  page_count={after['page_count']:,} freelist={after['freelist_count']:,} "
              f"sqlite_stat1_rows={after['stat1_rows']}", flush=True)
        if after["stat1_rows"] <= 0:
            print("  [WARN] sqlite_stat1 still empty after ANALYZE — investigate", flush=True)
            return 4
        print("  [OK] maintenance complete: planner statistics populated, WAL truncated.", flush=True)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a and not a.startswith("--")]
    path = args[0] if args else os.path.join("data", "ed_console.db")
    sys.exit(run_maintenance(path))
