#!/usr/bin/env python3
"""RTH guest switch SLA validation — closure harness for LIVE_GUEST_SLA_NOT_PROVEN."""
from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from verification.operator_trust_rth_validation import (
    GUEST_SWITCH_MATRIX,
    build_dry_run_report,
    run_guest_switch_validation,
    write_validation_outputs,
)

DEFAULT_RUNBOOK = _REPO / "reports/ui_transport/rth_guest_switch_validation_runbook_2026-06-18.md"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Do not call live server; classify RTH_VALIDATION_NOT_RUN")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Server base URL for live run")
    parser.add_argument("--audit-date", default=datetime.date.today().isoformat())
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    args = parser.parse_args()

    out_dir = _REPO / "reports/ui_transport"
    json_path = args.output_json or out_dir / f"rth_guest_switch_validation_{args.audit_date}.json"
    md_path = args.output_md or out_dir / f"rth_guest_switch_validation_{args.audit_date}.md"

    if args.dry_run:
        report = build_dry_run_report(
            harness="guest_switch_sla",
            audit_date=args.audit_date,
        )
        report["switch_matrix_required"] = [list(p) for p in GUEST_SWITCH_MATRIX]
        report["endpoints"] = {
            "ticker_switch": "/api/diagnostics/ticker-switch",
            "sqlite_contention": "/api/diagnostics/sqlite-contention",
        }
        report["pass_fail_rules"] = [
            "wrong ticker accepted: FAIL",
            "stale generation accepted: FAIL",
            "cache restored as fresh: FAIL",
            "guest incomplete without visible reason: FAIL",
            "cards_first_render_ms missing after timeout: FAIL",
            "DB degraded present but not surfaced: FAIL",
            "final_switch_state never READY or explicit degraded: FAIL",
        ]
    else:
        result = run_guest_switch_validation(
            base_url=args.base_url,
            dry_run=False,
            audit_date=args.audit_date,
        )
        report = result.to_dict()

    write_validation_outputs(report, json_path=json_path, md_path=md_path)
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
