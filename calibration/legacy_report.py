#!/usr/bin/env python3
"""
Report calibration_decision_log trust split and legacy subcategories (JSON to stdout).

  python -m calibration.legacy_report --db data/ed_console.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from calibration.canonical_enforcement import (
    CalibrationCanonicalViolationError,
    enforce_calibration_decision_log_only_1m,
)
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from calibration.schema import ensure_calibration_schema
from calibration.trust import CALIBRATION_TRUST_LEGACY, CALIBRATION_TRUST_TRUSTED

try:
    from db import configure_sqlite_connection
except Exception:

    def configure_sqlite_connection(conn, **kwargs):
        pass


def analyze(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    enforce_calibration_decision_log_only_1m(conn)

    total = int(conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0])
    n_trusted = int(
        conn.execute(
            "SELECT COUNT(*) FROM calibration_decision_log WHERE calibration_trust = ?",
            (CALIBRATION_TRUST_TRUSTED,),
        ).fetchone()[0]
    )
    n_legacy = int(
        conn.execute(
            "SELECT COUNT(*) FROM calibration_decision_log WHERE calibration_trust = ?",
            (CALIBRATION_TRUST_LEGACY,),
        ).fetchone()[0]
    )

    # Legacy row subcategories (partition legacy; informational — all remain quarantined).
    legacy_pending = int(
        conn.execute(
            f"""
            SELECT COUNT(*) FROM calibration_decision_log
            WHERE calibration_trust = ? AND outcome_5c IS NULL
            """,
            (CALIBRATION_TRUST_LEGACY,),
        ).fetchone()[0]
    )
    legacy_labeled_join_complete = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM calibration_decision_log
            WHERE calibration_trust = ?
              AND outcome_5c IS NOT NULL
              AND matched_snapshot_ts_utc IS NOT NULL
              AND outcome_join_method IS NOT NULL
            """,
            (CALIBRATION_TRUST_LEGACY,),
        ).fetchone()[0]
    )
    legacy_labeled_join_incomplete = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM calibration_decision_log
            WHERE calibration_trust = ?
              AND outcome_5c IS NOT NULL
              AND (matched_snapshot_ts_utc IS NULL OR outcome_join_method IS NULL)
            """,
            (CALIBRATION_TRUST_LEGACY,),
        ).fetchone()[0]
    )

    trusted_pending = int(
        conn.execute(
            f"""
            SELECT COUNT(*) FROM calibration_decision_log
            WHERE calibration_trust = ? AND outcome_5c IS NULL
            """,
            (CALIBRATION_TRUST_TRUSTED,),
        ).fetchone()[0]
    )
    trusted_with_outcomes = int(
        conn.execute(
            f"""
            SELECT COUNT(*) FROM calibration_decision_log
            WHERE calibration_trust = ? AND outcome_5c IS NOT NULL
            """,
            (CALIBRATION_TRUST_TRUSTED,),
        ).fetchone()[0]
    )

    conn.close()

    cat_sum = legacy_pending + legacy_labeled_join_complete + legacy_labeled_join_incomplete
    return {
        "meta": {"db": str(db_path)},
        "criteria": {
            "trusted": "calibration_trust = 'trusted' (production writer inserts after quarantine milestone).",
            "legacy": "calibration_trust = 'legacy' (all pre-migration rows and any non-writer inserts).",
            "legacy_subcategories": (
                "Partition of legacy only: pending | labeled_join_complete | labeled_join_incomplete."
            ),
        },
        "counts": {
            "total_rows": total,
            "trusted_rows": n_trusted,
            "legacy_rows": n_legacy,
            "trusted_pending_outcomes": trusted_pending,
            "trusted_with_outcomes": trusted_with_outcomes,
            "legacy_pending_outcomes": legacy_pending,
            "legacy_labeled_join_metadata_complete": legacy_labeled_join_complete,
            "legacy_labeled_join_metadata_incomplete": legacy_labeled_join_incomplete,
            "legacy_subcategory_sum_equals_legacy_rows": cat_sum == n_legacy,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    if not args.db.is_file():
        print(json.dumps({"error": "db not found"}))
        return 1
    require_canonical_db_target(args, tool_name="calibration.legacy_report", write_capable=False)
    try:
        print(json.dumps(analyze(args.db), indent=2))
    except CalibrationCanonicalViolationError as e:
        print(json.dumps({"error": str(e)}))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
