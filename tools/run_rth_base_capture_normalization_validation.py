#!/usr/bin/env python3
"""RTH base capture / normalization validation — SPY/QQQ/IWM row cadence proof."""
from __future__ import annotations

import argparse
import datetime
import sqlite3
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from verification.operator_trust_rth_validation import (
    build_dry_run_report,
    capture_runtime_env,
    write_validation_outputs,
)

DEFAULT_RUNBOOK = _REPO / "reports/base_capture/rth_base_capture_normalization_runbook_2026-06-18.md"
BASE_TICKERS = ("SPY", "QQQ", "IWM")


def _count_rows(db_path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"raw": {}, "normalized": {}}
    if not db_path.is_file():
        return {"error": f"db missing: {db_path}", **out}
    conn = sqlite3.connect(str(db_path))
    try:
        for t in BASE_TICKERS:
            try:
                out["raw"][t] = conn.execute(
                    "SELECT COUNT(*) FROM snapshots_1m WHERE ticker = ?", (t,)
                ).fetchone()[0]
            except sqlite3.Error:
                out["raw"][t] = None
            try:
                out["normalized"][t] = conn.execute(
                    "SELECT COUNT(*) FROM snapshots_1m_normalized WHERE ticker = ?", (t,)
                ).fetchone()[0]
            except sqlite3.Error:
                out["normalized"][t] = None
    finally:
        conn.close()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db-path", type=Path, default=_REPO / "data" / "ed_console.db")
    parser.add_argument("--audit-date", default=datetime.date.today().isoformat())
    args = parser.parse_args()

    out_dir = _REPO / "reports/base_capture"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"rth_base_capture_normalization_validation_{args.audit_date}.json"
    md_path = out_dir / f"rth_base_capture_normalization_validation_{args.audit_date}.md"

    if args.dry_run:
        report = build_dry_run_report(harness="base_capture_normalization", audit_date=args.audit_date)
        report["base_tickers"] = list(BASE_TICKERS)
    else:
        counts = _count_rows(args.db_path)
        failures = []
        for t in BASE_TICKERS:
            if not counts.get("raw", {}).get(t):
                failures.append(f"base_raw_starved:{t}")
            if not counts.get("normalized", {}).get(t):
                failures.append(f"base_normalized_starved:{t}")
        env = capture_runtime_env()
        report = {
            "schema_version": 1,
            "harness": "base_capture_normalization",
            "audit_date": args.audit_date,
            "dry_run": False,
            "pass": not failures,
            "classifications": (
                ["BASE_CAPTURE_NORMALIZATION_PASS"] if not failures else ["BASE_CAPTURE_NORMALIZATION_FAIL"]
            ),
            "failures": failures,
            "row_counts": counts,
            "runtime_env": env,
        }
        if not env.get("ED_CALIBRATION_LOG_enabled"):
            report["classifications"].append("EVIDENCE_GAP_ED_CALIBRATION_LOG_DISABLED")
            report["pass"] = False

    write_validation_outputs(report, json_path=json_path, md_path=md_path)
    print(f"wrote {json_path}")
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
