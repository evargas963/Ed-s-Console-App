"""RC-6 blob-dedup migration CORE — operates on ONE sqlite file, never on the original.

Reclaims the ~6.2 GB byte-identical duplicate of option_chain_json + replay_context_json in
`snapshots_1m_normalized` (proven identical to `snapshots`). This module NEVER touches the live
DB: the PowerShell wrapper (rc6_dedup.ps1) backs up the live file, copies it to a WORK file, and
calls this on the WORK copy. The operator swaps only after reviewing the verified result.

Safety model (every step aborts loudly on failure; the original is untouched throughout):
  1. PRAGMA integrity_check == "ok"      (refuse a corrupt input)
  2. EXHAUSTIVE orphan check == 0         (prove every normalized blob has a surviving snapshots
                                           copy; if any row would lose data, ABORT — drop nothing)
  3. record BEFORE counts + column sets
  4. DROP the two blob columns from snapshots_1m_normalized (SQLite 3.35+), then VACUUM
  5. verify AFTER: integrity ok; snapshots + normalized ROW COUNTS unchanged; the two columns
     gone from normalized; snapshots blobs still present (sample); file smaller

Usage:  python tools/migrations/rc6_migrate.py <work_db_path> [--verify-only]
Exit 0 = success (or verify-only clean); non-zero = aborted, DB left as-is.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from typing import NoReturn

NORM = "snapshots_1m_normalized"
BLOBS = ("option_chain_json", "replay_context_json")
MINLEN = 200


def _fail(msg: str) -> NoReturn:
    print(f"  [ABORT] {msg}", flush=True)
    sys.exit(2)


def _cols(c: sqlite3.Cursor, table: str) -> set[str]:
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}


def _counts(c: sqlite3.Cursor) -> dict[str, int]:
    return {
        "snapshots": c.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
        "normalized": c.execute(f"SELECT COUNT(*) FROM {NORM}").fetchone()[0],
    }


def check_integrity(c: sqlite3.Cursor) -> None:
    print("  [1] PRAGMA integrity_check ...", flush=True)
    r = c.execute("PRAGMA integrity_check").fetchone()[0]
    if r != "ok":
        _fail(f"integrity_check returned {r!r}, not 'ok'")
    print("      ok", flush=True)


def check_no_orphans(c: sqlite3.Cursor) -> None:
    """EXHAUSTIVE: every normalized row with a real blob MUST have a snapshots row carrying a
    real blob on the same (ticker, timeframe, ts_utc). If any lacks one, dropping would lose it.

    RC-135: a column already dropped is already-satisfied — nothing on normalized can be lost
    when the column does not exist. Without this skip the query SELECTs a missing column and
    dies with OperationalError, so a run interrupted after the DROP (measured 2026-07-29:
    killed mid-VACUUM by session teardown) could never be finished by re-invoking the tool.
    """
    print("  [2] EXHAUSTIVE orphan check (every normalized blob has a surviving snapshots copy) ...", flush=True)
    present = _cols(c, NORM)
    for col in BLOBS:
        if col not in present:
            print(f"      {col}: column already dropped — premise satisfied (resume)",
                  flush=True)
            continue
        n = c.execute(
            f"""SELECT COUNT(*) FROM {NORM} n
                WHERE n.{col} IS NOT NULL AND length(n.{col}) > {MINLEN}
                  AND NOT EXISTS (
                      SELECT 1 FROM snapshots s
                      WHERE s.ticker = n.ticker AND s.timeframe = n.timeframe AND s.ts_utc = n.ts_utc
                        AND s.{col} IS NOT NULL AND length(s.{col}) > {MINLEN})"""
        ).fetchone()[0]
        if n != 0:
            _fail(f"{n} normalized rows have a {col} with NO surviving snapshots copy — dropping "
                  f"would lose data. Nothing dropped.")
        print(f"      {col}: 0 orphans — safe", flush=True)


def migrate(path: str, verify_only: bool) -> None:
    if not os.path.isfile(path):
        _fail(f"file not found: {path}")
    size_before = os.path.getsize(path)
    print(f"RC-6 migration target (a COPY, never the live DB): {path}  size={size_before/1e9:.2f} GB", flush=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    c = con.cursor()

    check_integrity(c)
    check_no_orphans(c)
    before = _counts(c)
    ncols = _cols(c, NORM)
    print(f"  BEFORE: snapshots={before['snapshots']:,} normalized={before['normalized']:,}; "
          f"normalized has blobs: {[b for b in BLOBS if b in ncols]}", flush=True)

    if verify_only:
        print("  --verify-only: premise + integrity clean. Nothing changed.", flush=True)
        con.close()
        return

    print("  [3] dropping duplicate blob columns from normalized ...", flush=True)
    for col in BLOBS:
        if col in ncols:
            c.execute(f"ALTER TABLE {NORM} DROP COLUMN {col}")
            print(f"      dropped {NORM}.{col}", flush=True)
    con.commit()

    # RC-135: an interrupted prior run can leave a WAL as large as the database itself
    # (measured 2026-07-29: 21.1 GB beside a 23.8 GB DB, on a volume with 45 GB free).
    # VACUUM needs roughly another DB-size of temp space, so the stale WAL must be returned
    # to disk BEFORE it, or the resume fails for want of room on a copy that is otherwise good.
    wal_pages = c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    print(f"      WAL checkpoint(TRUNCATE) -> {tuple(wal_pages) if wal_pages else 'n/a'}",
          flush=True)

    print("  [4] VACUUM (reclaiming space) — this can take several minutes ...", flush=True)
    con.execute("VACUUM")
    con.commit()

    # ---- verify AFTER ----
    print("  [5] verifying result ...", flush=True)
    check_integrity(c)
    after = _counts(c)
    if after != before:
        _fail(f"ROW COUNTS CHANGED: before={before} after={after} — do NOT use this copy")
    ncols2 = _cols(c, NORM)
    still = [b for b in BLOBS if b in ncols2]
    if still:
        _fail(f"columns still present after drop: {still}")
    # snapshots blobs still intact (sample)
    scount = c.execute("SELECT COUNT(*) FROM snapshots WHERE option_chain_json IS NOT NULL "
                       "AND length(option_chain_json) > ?", (MINLEN,)).fetchone()[0]
    if scount <= 0:
        _fail("snapshots.option_chain_json appears empty after migration — do NOT use this copy")
    con.close()
    size_after = os.path.getsize(path)
    print(f"  AFTER: snapshots={after['snapshots']:,} normalized={after['normalized']:,} (unchanged); "
          f"normalized blob columns removed; snapshots blob rows still present={scount:,}", flush=True)
    print(f"  [SUCCESS] {size_before/1e9:.2f} GB -> {size_after/1e9:.2f} GB "
          f"(reclaimed {(size_before-size_after)/1e9:.2f} GB). Row counts unchanged; integrity ok.", flush=True)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a]
    verify_only = "--verify-only" in args
    positional = [a for a in args if not a.startswith("--")]
    if len(positional) != 1:
        print("usage: python tools/migrations/rc6_migrate.py <work_db_path> [--verify-only]")
        sys.exit(1)
    migrate(positional[0], verify_only)
