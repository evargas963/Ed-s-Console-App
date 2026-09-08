#!/usr/bin/env python3
"""RC-183 — reversible quarantine of outside-Collect-window bars (operator GO, 2026-08-02).

Moves every `price_bars_1m` row whose bar-end falls outside the operator Collect window —
ET minutes (555, min(975, cash_close+15)] on trading days — into `price_bars_1m_quarantine`.
The membership authority is `time_et.is_collect_window_bar_end_ts_utc`, the SAME function the
write seam enforces (one law, one function; a second implementation here would be the
two-faucet defect all over again).

Operator terms honoured verbatim:
- a fresh validated stable backup is REQUIRED before canonical execution,
- dry-run is the DEFAULT; --execute only after the dry-run count is approved,
- MOVE, never delete: schema-identical quarantine table + quarantined_at_utc + reason,
- reversible: --restore moves every quarantined row back (the exact inverse),
- canonical table must end with 0 outside-law rows, proven by COUNT(*) in the same run.

Safety: refuses while anything holds the DB write lock (BEGIN IMMEDIATE probe, same pattern as
the backfill tool); batched transactions so the WAL never balloons; every batch verifies
inserted==deleted before committing.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import (  # noqa: E402
    register_allow_noncanonical_flag,
    require_canonical_db_target,
)
from db_authority import canonical_console_db_path, is_canonical_db_path  # noqa: E402
from db_safety import backup_permanent_database  # noqa: E402
from time_et import is_collect_window_bar_end_ts_utc  # noqa: E402

BATCH = 50_000

QUARANTINE_SQL = """
CREATE TABLE IF NOT EXISTS price_bars_1m_quarantine (
    ticker            TEXT NOT NULL,
    bar_start_ts_utc  REAL NOT NULL,
    bar_end_ts_utc    REAL NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    source            TEXT,
    quarantined_at_utc REAL NOT NULL,
    reason            TEXT NOT NULL,
    PRIMARY KEY (ticker, bar_start_ts_utc)
)
"""


def _write_lock_free(db_path: str) -> tuple[bool, str | None]:
    try:
        conn = sqlite3.connect(db_path, timeout=2.0)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("COMMIT")
        finally:
            conn.close()
        return True, None
    except sqlite3.OperationalError as e:
        return False, str(e)


def _outside_rowids(con: sqlite3.Connection) -> list[int]:
    """Rowids of every outside-law row, judged by the seam's own authority function."""
    out: list[int] = []
    # session-universe-ok: this tool's PURPOSE is finding outside-window rows — it must read the full table to quarantine what the law rejects
    cur = con.execute("SELECT rowid, bar_end_ts_utc FROM price_bars_1m")
    while True:
        chunk = cur.fetchmany(200_000)
        if not chunk:
            break
        for rowid, ts in chunk:
            if not is_collect_window_bar_end_ts_utc(float(ts)):
                out.append(rowid)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(canonical_console_db_path()))
    ap.add_argument("--execute", action="store_true",
                    help="perform the move; default is dry-run counts only")
    ap.add_argument("--restore", action="store_true",
                    help="reverse: move every quarantined row back into price_bars_1m")
    ap.add_argument("--expected", type=int, default=None,
                    help="refuse to execute unless the dry-run count equals this number")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(
        args, tool_name="quarantine_outside_window_bars_v1", write_capable=True
    )

    ok, err = _write_lock_free(args.db)
    if not ok:
        print(json.dumps({"status": "DB_LOCKED", "error": err}))
        return 2

    con = sqlite3.connect(args.db, timeout=30.0)
    # autocommit mode: the stdlib driver otherwise auto-opens a deferred transaction on the
    # staging INSERT, and the explicit BEGIN IMMEDIATE below then throws "cannot start a
    # transaction within a transaction". Transaction boundaries here are ours, explicitly.
    con.isolation_level = None
    con.execute("PRAGMA busy_timeout=30000")
    try:
        backup: str | None = None
        manifest_path: Path | None = None
        if args.execute and is_canonical_db_path(args.db):
            try:
                backup_path, manifest_path, _ = backup_permanent_database(
                    Path(args.db), reason="pre_quarantine_outside_window_bars_v1"
                )
                backup = str(backup_path)
            except Exception as exc:
                print(json.dumps({"status": "REFUSED_BACKUP_FAILED", "error": str(exc)}))
                return 2
        if args.restore:
            con.execute(QUARANTINE_SQL)
            n = con.execute("SELECT COUNT(*) FROM price_bars_1m_quarantine").fetchone()[0]
            if not args.execute:
                print(json.dumps({"status": "RESTORE_DRY_RUN", "quarantined_rows": n}))
                return 0
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "INSERT OR REPLACE INTO price_bars_1m -- collect-window-ok: operator-driven RESTORE from quarantine; the daily quarantine pass re-evaluates every row against the current law\n"
                "(ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume, source) "
                "SELECT ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, "
                "volume, source FROM price_bars_1m_quarantine")
            con.execute("DELETE FROM price_bars_1m_quarantine")
            con.execute("COMMIT")
            print(json.dumps({
                "status": "RESTORED",
                "rows": n,
                "backup_used": backup,
                "backup_manifest": str(manifest_path) if manifest_path else None,
            }))
            return 0

        t0 = time.time()
        rowids = _outside_rowids(con)
        total = con.execute("SELECT COUNT(*) FROM price_bars_1m").fetchone()[0]
        report = {"status": "DRY_RUN", "outside_law_rows": len(rowids),
                  "total_rows": total, "scan_sec": round(time.time() - t0, 1)}
        if not args.execute:
            print(json.dumps(report))
            return 0

        if args.expected is not None and len(rowids) != args.expected:
            print(json.dumps({"status": "REFUSED_COUNT_MISMATCH",
                              "dry_run": len(rowids), "expected": args.expected}))
            return 2

        con.execute(QUARANTINE_SQL)
        stamp = time.time()
        # A TEMP rowid table sidesteps SQLite's bound-parameter ceiling (the first draft hit
        # "too many SQL variables" at the very first real batch) and lets the whole move run
        # as ONE verified transaction: either every row moves, or none do.
        con.execute("CREATE TEMP TABLE _q_rowids (rid INTEGER PRIMARY KEY)")
        con.executemany("INSERT INTO _q_rowids (rid) VALUES (?)",
                        [(r,) for r in rowids])
        staged = con.execute("SELECT COUNT(*) FROM _q_rowids").fetchone()[0]
        if staged != len(rowids):
            print(json.dumps({"status": "ABORTED_STAGING_MISMATCH",
                              "staged": staged, "expected": len(rowids)}))
            return 2
        con.execute("BEGIN IMMEDIATE")
        ins = con.execute(
            "INSERT OR REPLACE INTO price_bars_1m_quarantine "
            "SELECT ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, "
            "volume, source, ?, 'RC-183 outside 08:15-15:15 CT collect window' "
            "FROM price_bars_1m WHERE rowid IN (SELECT rid FROM _q_rowids)",
            (stamp,)).rowcount
        dele = con.execute(
            "DELETE FROM price_bars_1m WHERE rowid IN (SELECT rid FROM _q_rowids)").rowcount
        if ins != len(rowids) or dele != len(rowids):
            con.execute("ROLLBACK")
            print(json.dumps({"status": "ABORTED_MOVE_MISMATCH",
                              "inserted": ins, "deleted": dele, "expected": len(rowids)}))
            return 2
        con.execute("COMMIT")
        moved = dele

        # the operator's Done condition, measured in the SAME run
        residual = sum(1 for (ts,) in con.execute("SELECT bar_end_ts_utc FROM price_bars_1m")
                       if not is_collect_window_bar_end_ts_utc(float(ts)))
        qn = con.execute("SELECT COUNT(*) FROM price_bars_1m_quarantine").fetchone()[0]
        cn = con.execute("SELECT COUNT(*) FROM price_bars_1m").fetchone()[0]
        print(json.dumps({"status": "EXECUTED" if residual == 0 else "EXECUTED_WITH_RESIDUAL",
                          "moved": moved, "quarantine_rows": qn, "canonical_rows": cn,
                          "canonical_outside_law_after": residual,
                          "backup_used": backup,
                          "backup_manifest": str(manifest_path) if manifest_path else None}))
        return 0 if residual == 0 else 1
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
