#!/usr/bin/env python3
"""RTH DB contention correlation validation — closure harness for DB_CONTENTION_RTH_CORRELATION_NOT_PROVEN."""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from verification.operator_trust_rth_validation import (
    build_dry_run_report,
    capture_runtime_env,
    http_get_json,
    write_validation_outputs,
)

DEFAULT_RUNBOOK = _REPO / "reports/db_contention/rth_db_contention_validation_runbook_2026-06-18.md"


def _evaluate_live(base_url: str) -> dict[str, Any]:
    env = capture_runtime_env()
    failures: list[str] = []
    try:
        sqlite = http_get_json(f"{base_url.rstrip('/')}/api/diagnostics/sqlite-contention")
        switch = http_get_json(f"{base_url.rstrip('/')}/api/diagnostics/ticker-switch")
    except Exception as e:
        return {
            "pass": False,
            "classifications": ["RTH_VALIDATION_NOT_RUN"],
            "failures": [str(e)],
            "runtime_env": env,
        }

    lock_wait = int(sqlite.get("sqlite_lock_wait_count") or 0)
    db_locked = int(sqlite.get("sqlite_database_locked_count") or 0)
    operator = sqlite.get("operator") or {}
    if (lock_wait > 0 or db_locked > 0) and not operator.get("show"):
        failures.append("DB_DEGRADED_NOT_SURFACED_FAIL")

    events = switch.get("events") if isinstance(switch, dict) else []
    classifications = []
    if failures:
        classifications.append("DB_CONTENTION_RTH_CORRELATION_FAIL")
    elif lock_wait == 0 and db_locked == 0:
        classifications.append("RTH_VALIDATION_NOT_RUN")
    else:
        classifications.append("DB_DEGRADED_DURING_SWITCH")

    return {
        "pass": not failures and lock_wait > 0,
        "classifications": classifications,
        "failures": failures,
        "sqlite_metrics": {
            "sqlite_lock_wait_count": lock_wait,
            "sqlite_database_locked_count": db_locked,
            "operator_state": operator.get("state"),
        },
        "switch_events": len(events) if isinstance(events, list) else 0,
        "correlation_targets": [
            "sqlite lock wait counter deltas",
            "STALE pill timing",
            "LOADING duration",
            "ticker switch timing",
            "Tier C payload delay",
        ],
        "runtime_env": env,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--audit-date", default=datetime.date.today().isoformat())
    args = parser.parse_args()

    out_dir = _REPO / "reports/db_contention"
    json_path = out_dir / f"rth_db_contention_validation_{args.audit_date}.json"
    md_path = out_dir / f"rth_db_contention_validation_{args.audit_date}.md"

    if args.dry_run:
        report = build_dry_run_report(harness="db_contention_correlation", audit_date=args.audit_date)
        report["correlation_targets"] = [
            "sqlite lock wait counter deltas",
            "database locked counter deltas",
            "STALE pill timing",
            "LOADING duration",
            "ticker switch timing",
            "Tier C payload delay",
            "snapshot write cadence",
            "normalized row cadence",
        ]
    else:
        live = _evaluate_live(args.base_url)
        report = {
            "schema_version": 1,
            "harness": "db_contention_correlation",
            "audit_date": args.audit_date,
            "dry_run": False,
            **live,
        }

    write_validation_outputs(report, json_path=json_path, md_path=md_path)
    print(f"wrote {json_path}")
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
