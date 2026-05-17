#!/usr/bin/env python3
"""
Attach snapshot outcomes to calibration_decision_log.

Join keys: (ticker, timeframe='1m', ts_utc).

Priority:
  1. Exact: snapshots.ts_utc = calibration.decision_ts_utc (required for production; matches Phase A alignment).
  2. Optional nearest-within-tolerance only if --tol > 0: single unique closest row within tol; ties → skip + stat.

Never attaches if more than one snapshot row matches at the chosen key (duplicate ts_utc rows).

After pending rows are processed, every row with `outcome_5c` already set is re-synced from
`snapshots` at `COALESCE(matched_snapshot_ts_utc, decision_ts_utc)` so legacy partial attaches
cannot drift from the matched snapshot row.

Usage:
  python -m calibration.backfill_outcomes
  python -m calibration.backfill_outcomes --db data/ed_console.db --tol 0
  python -m calibration.backfill_outcomes --tol 5   # legacy: nearest unique within 5s only
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Optional

from calibration.canonical_enforcement import (
    CalibrationCanonicalViolationError,
    enforce_calibration_decision_log_only_1m,
)
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from calibration.schema import ensure_calibration_schema

log = logging.getLogger(__name__)

try:
    from db import configure_sqlite_connection
except ImportError as e:
    log.warning(
        "db.configure_sqlite_connection not available — using no-op stub: %s",
        e,
    )

    def configure_sqlite_connection(conn, **kwargs):
        pass

from db import get_snapshot_sql

_BASE_SEL = get_snapshot_sql("calibration/backfill_outcomes.py:select_base")


def _count_snapshots_at_exact_ts(
    conn: sqlite3.Connection, ticker: str, ts: float
) -> int:
    r = conn.execute(
        get_snapshot_sql("calibration/backfill_outcomes.py:57"),
        (ticker, ts),
    ).fetchone()
    return int(r["n"] if r else 0)


def resolve_snapshot_for_backfill(
    conn: sqlite3.Connection,
    ticker: str,
    decision_ts: float,
    tol_sec: float,
) -> tuple[Optional[sqlite3.Row], str, Optional[str]]:
    """
    Returns (snapshot_row_or_none, skip_reason, join_method).

    skip_reason 'ok' means row is usable; otherwise skip_reason explains why we did not attach.
    join_method is 'exact' | 'nearest_within_tol' when row is returned.
    """
    n_exact = _count_snapshots_at_exact_ts(conn, ticker, decision_ts)
    if n_exact > 1:
        return None, "ambiguous_duplicate_snapshots", None
    if n_exact == 1:
        row = conn.execute(
            _BASE_SEL + " AND ts_utc=?",
            (ticker, decision_ts),
        ).fetchone()
        if row is None:
            return None, "internal_inconsistent", None
        if row["outcome_5c"] is None:
            return None, "snapshot_outcomes_not_filled", None
        return row, "ok", "exact"

    # n_exact == 0
    if tol_sec <= 0.0:
        return None, "no_exact_match", None

    rows = conn.execute(
        _BASE_SEL + " AND ABS(ts_utc - ?) <= ?",
        (ticker, decision_ts, tol_sec),
    ).fetchall()
    if not rows:
        return None, "no_candidate_in_tol", None
    best = min(abs(float(r["ts_utc"]) - decision_ts) for r in rows)
    at_min = [
        r
        for r in rows
        if abs(float(r["ts_utc"]) - decision_ts) <= best + 1e-9
    ]
    if len(at_min) > 1:
        return None, "ambiguous_nearest_tie", None
    row = at_min[0]
    if row["outcome_5c"] is None:
        return None, "snapshot_outcomes_not_filled", None
    return row, "ok", "nearest_within_tol"


def backfill(db_path: Path, tol_sec: float = 0.0) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    enforce_calibration_decision_log_only_1m(conn)

    _reason_stat = {
        "ambiguous_duplicate_snapshots": "skipped_ambiguous_duplicate_snapshots",
        "ambiguous_nearest_tie": "skipped_ambiguous_nearest_tie",
        "no_exact_match": "skipped_no_exact_match",
        "no_candidate_in_tol": "skipped_no_candidate_in_tol",
        "snapshot_outcomes_not_filled": "skipped_snapshot_outcomes_not_filled",
        "internal_inconsistent": "skipped_internal_inconsistent",
    }
    stats: dict[str, Any] = {
        "candidates": 0,
        "updated": 0,
        "tol_sec": tol_sec,
    }
    for v in _reason_stat.values():
        stats[v] = 0
    stats["skipped_unknown"] = 0

    pending = conn.execute(
        """
        SELECT id, ticker, decision_ts_utc FROM calibration_decision_log
        WHERE outcome_5c IS NULL AND calibration_trust = 'trusted'
        ORDER BY id
        """
    ).fetchall()
    stats["candidates"] = len(pending)
    now = time.time()

    for row in pending:
        rid = int(row["id"])
        tk = row["ticker"]
        ts = float(row["decision_ts_utc"])
        snap, reason, method = resolve_snapshot_for_backfill(conn, tk, ts, tol_sec)
        if snap is None:
            sk = _reason_stat.get(reason, "skipped_unknown")
            stats[sk] = stats.get(sk, 0) + 1
            continue

        m_ts = float(snap["ts_utc"])
        conn.execute(
            """
            UPDATE calibration_decision_log SET
              outcome_1c=?,
              outcome_5c=?,
              outcome_15c=?,
              outcome_60c=?,
              outcome_1c_pts=?,
              outcome_5c_pts=?,
              outcome_15c_pts=?,
              outcome_60c_pts=?,
              outcomes_attached_ts_utc=?,
              matched_snapshot_ts_utc=?,
              outcome_join_method=?
            WHERE id=?
            """,
            (
                snap["outcome_1c"],
                snap["outcome_5c"],
                snap["outcome_15c"],
                snap["outcome_60c"],
                snap["outcome_1c_pts"],
                snap["outcome_5c_pts"],
                snap["outcome_15c_pts"],
                snap["outcome_60c_pts"],
                now,
                m_ts,
                method,
                rid,
            ),
        )
        stats["updated"] += 1

    # Re-sync rows that already have outcomes: fixes legacy partial attaches and drift.
    resync_stats = _resync_existing_outcomes_from_snapshots(conn, now)
    for k, v in resync_stats.items():
        stats[k] = v

    conn.commit()
    conn.close()
    return stats


def _resync_existing_outcomes_from_snapshots(
    conn: sqlite3.Connection, outcomes_attached_ts_utc: float
) -> dict[str, int]:
    out: dict[str, int] = {
        "resynced": 0,
        "resync_skipped_no_snapshot": 0,
        "resync_skipped_duplicate_snapshots": 0,
        "resync_skipped_snapshot_outcomes_not_filled": 0,
    }
    rows = conn.execute(
        """
        SELECT id, ticker, decision_ts_utc, matched_snapshot_ts_utc
        FROM calibration_decision_log
        WHERE outcome_5c IS NOT NULL AND calibration_trust = 'trusted'
        """
    ).fetchall()
    for r in rows:
        rid = int(r["id"])
        tk = r["ticker"]
        key_ts = float(r["matched_snapshot_ts_utc"] if r["matched_snapshot_ts_utc"] is not None else r["decision_ts_utc"])
        dec_ts = float(r["decision_ts_utc"])
        n = _count_snapshots_at_exact_ts(conn, tk, key_ts)
        if n == 0:
            out["resync_skipped_no_snapshot"] += 1
            continue
        if n > 1:
            out["resync_skipped_duplicate_snapshots"] += 1
            continue
        snap = conn.execute(
            _BASE_SEL + " AND ts_utc=?",
            (tk, key_ts),
        ).fetchone()
        if snap is None or snap["outcome_5c"] is None:
            out["resync_skipped_snapshot_outcomes_not_filled"] += 1
            continue
        method = "exact" if abs(dec_ts - key_ts) <= 1e-9 else "nearest_within_tol"
        conn.execute(
            """
            UPDATE calibration_decision_log SET
              outcome_1c=?,
              outcome_5c=?,
              outcome_15c=?,
              outcome_60c=?,
              outcome_1c_pts=?,
              outcome_5c_pts=?,
              outcome_15c_pts=?,
              outcome_60c_pts=?,
              outcomes_attached_ts_utc=?,
              matched_snapshot_ts_utc=?,
              outcome_join_method=?
            WHERE id=?
            """,
            (
                snap["outcome_1c"],
                snap["outcome_5c"],
                snap["outcome_15c"],
                snap["outcome_60c"],
                snap["outcome_1c_pts"],
                snap["outcome_5c_pts"],
                snap["outcome_15c_pts"],
                snap["outcome_60c_pts"],
                outcomes_attached_ts_utc,
                float(snap["ts_utc"]),
                method,
                rid,
            ),
        )
        out["resynced"] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--tol",
        type=float,
        default=0.0,
        help="Seconds: 0 = exact ts_utc match only (default). >0 allows unique nearest within tolerance.",
    )
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    if not args.db.is_file():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 1
    require_canonical_db_target(args, tool_name="calibration.backfill_outcomes", write_capable=True)
    try:
        s = backfill(args.db, tol_sec=float(args.tol))
    except CalibrationCanonicalViolationError as e:
        print(f"CANONICAL_ENFORCEMENT_FAIL: {e}", file=sys.stderr)
        return 2
    print(json.dumps(s, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
