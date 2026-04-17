#!/usr/bin/env python3
"""Verify calibration_decision_log schema exists and is writable. Exit 0 on success."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from calibration.canonical_enforcement import (
    CalibrationCanonicalViolationError,
    enforce_calibration_decision_log_only_1m,
)
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from calibration.schema import ensure_calibration_schema

try:
    from db import configure_sqlite_connection
except Exception:

    def configure_sqlite_connection(conn, **kwargs):
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    if not args.db.is_file():
        print(f"MISSING_DB {args.db}", file=sys.stderr)
        return 2
    require_canonical_db_target(args, tool_name="calibration.validate_logging", write_capable=False)
    conn = sqlite3.connect(str(args.db))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    try:
        enforce_calibration_decision_log_only_1m(conn)
    except CalibrationCanonicalViolationError as e:
        print(f"CANONICAL_ENFORCEMENT_FAIL {e}", file=sys.stderr)
        conn.close()
        return 2
    n = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    nt = conn.execute(
        "SELECT COUNT(*) FROM calibration_decision_log WHERE calibration_trust = 'trusted'"
    ).fetchone()[0]
    nl = conn.execute(
        "SELECT COUNT(*) FROM calibration_decision_log WHERE calibration_trust = 'legacy'"
    ).fetchone()[0]
    conn.close()
    print(
        f"OK schema_ready row_count={n} trusted={nt} legacy={nl} canonical_1m_gate=pass"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
