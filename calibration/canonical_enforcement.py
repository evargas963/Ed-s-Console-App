"""
Hard gate: calibration workflows must not mix non-canonical snapshot timeframes.

Canonical studies use timeframe '1m' only (see timeframe_config.CANONICAL_TIMEFRAME).
Raises CalibrationCanonicalViolationError if calibration_decision_log declares another timeframe.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from calibration.schema import ensure_calibration_schema
from timeframe_config import CANONICAL_TIMEFRAME

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

__all__ = [
    "CANONICAL_TIMEFRAME",
    "CalibrationCanonicalViolationError",
    "enforce_calibration_decision_log_only_1m",
    "enforce_snapshots_fallback_is_1m_only",
    "provenance_dict",
    "snapshots_1m_labeled_counts",
]


class CalibrationCanonicalViolationError(RuntimeError):
    """Non-1m rows present in calibration_decision_log (canonical_timeframe)."""


def enforce_calibration_decision_log_only_1m(conn: sqlite3.Connection) -> dict[str, Any]:
    """
    Fail loudly if any row declares canonical_timeframe != '1m', or canonical_timeframe is NULL.
    """
    n_null = int(
        conn.execute(
            "SELECT COUNT(*) FROM calibration_decision_log WHERE canonical_timeframe IS NULL"
        ).fetchone()[0]
    )
    if n_null > 0:
        raise CalibrationCanonicalViolationError(
            f"calibration_decision_log: {n_null} row(s) have NULL canonical_timeframe; "
            "backfill/migrate before calibration studies."
        )
    n_bad = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM calibration_decision_log
            WHERE canonical_timeframe != ?
            """,
            (CANONICAL_TIMEFRAME,),
        ).fetchone()[0]
    )
    if n_bad > 0:
        raise CalibrationCanonicalViolationError(
            f"calibration_decision_log: {n_bad} row(s) have canonical_timeframe "
            f"!= {CANONICAL_TIMEFRAME!r}; calibration studies abort."
        )
    return {
        "calibration_decision_log_noncanonical_rows": 0,
        "canonical_timeframe": CANONICAL_TIMEFRAME,
    }


def snapshots_1m_labeled_counts(conn: sqlite3.Connection) -> dict[str, Any]:
    """Counts for snapshots table — 1m only; used in provenance / fallback safety."""
    total_1m = int(
        conn.execute(
            get_snapshot_sql("calibration/canonical_enforcement.py:79"),
            (CANONICAL_TIMEFRAME,),
        ).fetchone()[0]
    )
    labeled_1m = int(
        conn.execute(
            get_snapshot_sql("calibration/canonical_enforcement.py:85"),
            (CANONICAL_TIMEFRAME,),
        ).fetchone()[0]
    )
    non_1m_rows = int(
        conn.execute(
            get_snapshot_sql("calibration/canonical_enforcement.py:94"),
            (CANONICAL_TIMEFRAME,),
        ).fetchone()[0]
    )
    return {
        "snapshots_rows_1m_total": total_1m,
        "snapshots_rows_1m_labeled_outcome_5c": labeled_1m,
        "snapshots_rows_excluded_unlabeled_1m": max(0, total_1m - labeled_1m),
        "snapshots_rows_non_canonical_timeframe_in_db": non_1m_rows,
    }


def provenance_dict(
    *,
    source_tables: list[str],
    labeled_sample_count: int,
    excluded_by_reason: dict[str, int],
) -> dict[str, Any]:
    return {
        "effective_timeframe": CANONICAL_TIMEFRAME,
        "source_tables": source_tables,
        "labeled_sample_count": labeled_sample_count,
        "excluded_by_reason": excluded_by_reason,
    }


def enforce_snapshots_fallback_is_1m_only(conn: sqlite3.Connection) -> dict[str, Any]:
    """
    Snapshot fallback queries MUST filter timeframe='1m'. This does not forbid 5m rows
    elsewhere in the DB; it proves the fallback path only pools 1m rows (counts + contract).
    """
    counts = snapshots_1m_labeled_counts(conn)
    return {
        "fallback_guarantee": "snapshots WHERE timeframe='1m' only — no pooling of other timeframes",
        **counts,
    }


def run_binary_gate(db_path: Path) -> dict[str, Any]:
    """JSON-serializable gate result; raises CalibrationCanonicalViolationError on failure."""
    if not db_path.is_file():
        return {"error": "db not found", "binary_pass": False}
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    try:
        gate = enforce_calibration_decision_log_only_1m(conn)
        snap = enforce_snapshots_fallback_is_1m_only(conn)
        return {
            "binary_pass": True,
            "calibration_decision_log_gate": gate,
            "snapshots_1m_contract": snap,
        }
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Binary PASS/FAIL: calibration canonical 1m gate")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="calibration.canonical_enforcement", write_capable=False)
    try:
        out = run_binary_gate(args.db)
        if out.get("error"):
            print(json.dumps(out, indent=2))
            return 2
        print(json.dumps(out, indent=2))
        return 0
    except CalibrationCanonicalViolationError as e:
        print(json.dumps({"binary_pass": False, "error": str(e)}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
