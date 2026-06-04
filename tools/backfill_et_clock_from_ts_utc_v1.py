#!/usr/bin/env python3
"""
FIND-CAL-TS item-6: backfill et_hour, et_minute, market_session, ts_et from ts_utc.

Rewrites pre-COH-I-A rows (ts_utc < COH_I_A_ET_BACKFILL_CEILING_TS_UTC) on snapshots and
snapshots_1m_normalized. Idempotent: a second commit pass updates only rows still skewed.

Usage:
  python tools/backfill_et_clock_from_ts_utc_v1.py --db data/ed_console.db
  python tools/backfill_et_clock_from_ts_utc_v1.py --db data/ed_console.db --commit
  python tools/backfill_et_clock_from_ts_utc_v1.py --db data/ed_console.db --max-rows 1000 --commit

Exit codes: 0 success, 1 DB missing / post-commit sample mismatch, 2 canonical DB guard (via db_guard).
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.backfill_et_clock_from_ts_utc_v1 import (  # noqa: E402
    SCHEMA,
    count_candidates,
    count_mismatched,
    run_backfill,
    sample_post_backfill_check,
    table_ready_for_backfill,
)
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target  # noqa: E402
from calibration.paths import DEFAULT_DB, PROJECT_ROOT  # noqa: E402
from time_et import COH_I_A_ET_BACKFILL_CEILING_TS_UTC  # noqa: E402

log = logging.getLogger(__name__)


def _write_audit(result: dict, *, audit_root: Path | None) -> Path:
    root = Path(audit_root).resolve() if audit_root is not None else (PROJECT_ROOT / "governance" / "audits")
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = root / f"{SCHEMA}_{stamp}.json"
    result["audit_path"] = str(path)
    path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Backfill ET clock columns from ts_utc (item-6).")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database path")
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Apply UPDATEs (default: dry-run counts only)",
    )
    ap.add_argument(
        "--max-rows",
        type=int,
        default=None,
        metavar="N",
        help="Cap rows scanned/updated per invocation (safety)",
    )
    ap.add_argument(
        "--ceiling-ts-utc",
        type=float,
        default=COH_I_A_ET_BACKFILL_CEILING_TS_UTC,
        help="Only rows with ts_utc < this value are eligible",
    )
    ap.add_argument("--audit-root", type=Path, default=None, help="Override governance/audits dir")
    ap.add_argument(
        "--verify-sample",
        type=int,
        default=20,
        metavar="N",
        help="After commit, random-sample N pre-ceiling rows for regression check",
    )
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args(argv)
    require_canonical_db_target(
        args,
        tool_name=SCHEMA,
        write_capable=bool(args.commit),
    )
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    db_path = Path(args.db).resolve()
    if not db_path.is_file():
        log.error("database not found: %s", db_path)
        return 1

    conn = sqlite3.connect(str(db_path), timeout=120)
    try:
        pre: dict[str, dict[str, int]] = {}
        for table in ("snapshots", "snapshots_1m_normalized"):
            if not table_ready_for_backfill(conn, table):
                continue
            pre[table] = {
                "candidates": count_candidates(conn, table, ceiling_ts_utc=args.ceiling_ts_utc),
                "mismatched": count_mismatched(
                    conn,
                    table,
                    ceiling_ts_utc=args.ceiling_ts_utc,
                    max_rows=args.max_rows,
                ),
            }
    finally:
        conn.close()

    result = run_backfill(
        str(db_path),
        apply=bool(args.commit),
        ceiling_ts_utc=float(args.ceiling_ts_utc),
        max_rows=args.max_rows,
    )
    result["pre_scan"] = pre
    result["post_scan"] = {}
    conn_post = sqlite3.connect(str(db_path), timeout=120)
    try:
        for table in ("snapshots", "snapshots_1m_normalized"):
            if not table_ready_for_backfill(conn_post, table):
                continue
            result["post_scan"][table] = {
                "candidates": count_candidates(conn_post, table, ceiling_ts_utc=args.ceiling_ts_utc),
                "mismatched": count_mismatched(conn_post, table, ceiling_ts_utc=args.ceiling_ts_utc),
            }
    finally:
        conn_post.close()
    result["success"] = True

    if args.commit and int(args.verify_sample) > 0:
        conn = sqlite3.connect(str(db_path), timeout=120)
        try:
            checks = []
            for table in ("snapshots", "snapshots_1m_normalized"):
                if table_ready_for_backfill(conn, table):
                    checks.append(
                        sample_post_backfill_check(
                            conn,
                            table,
                            ceiling_ts_utc=float(args.ceiling_ts_utc),
                            sample_size=int(args.verify_sample),
                        )
                    )
            result["post_commit_sample"] = checks
            if any(not c.get("ok") for c in checks):
                result["success"] = False
                result["status"] = "post_commit_sample_mismatch"
        finally:
            conn.close()

    audit_path = _write_audit(result, audit_root=args.audit_root)
    log.info("audit written: %s", audit_path)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
