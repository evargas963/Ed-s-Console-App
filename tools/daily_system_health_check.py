#!/usr/bin/env python3
"""
Daily system health check (read-only DB, optional feature-registry validation).

Example:
  python tools/daily_system_health_check.py --all-tickers --primary-horizons --write-report

Exit code: 0 = overall PASS, non-zero = at least one FAIL severity check.
Does not train models or mutate production tables.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verification.daily_health import run_daily_health, write_reports


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily EdWebConsole system health (PASS/FAIL)")
    ap.add_argument("--db", type=Path, default=None, help="SQLite DB path (default: db.DB_PATH)")
    ap.add_argument(
        "--all-tickers",
        action="store_true",
        help="Use union of snapshots + price_bars_1m tickers (filtered by production_universe)",
    )
    ap.add_argument(
        "--primary-horizons",
        action="store_true",
        help="Validate primary horizons 1c/5c/15c/60c only (default behavior of this tool)",
    )
    ap.add_argument(
        "--write-report",
        action="store_true",
        help="Write reports/daily_health/latest_* and history copy",
    )
    ap.add_argument(
        "--feature-contract",
        action="store_true",
        help="Also run validate_feature_contracts (filesystem); failures add explicit FAIL checks",
    )
    ap.add_argument(
        "--universe",
        choices=("auto", "merged", "logging"),
        default="auto",
        help="Ticker universe: auto=logging intersect when logging_universe has rows else merged; "
        "merged=snapshots∪price_bars_1m; logging=intersect with logging_universe (fallback merged+WARN if empty)",
    )
    ap.add_argument(
        "tickers",
        nargs="*",
        metavar="TICKER",
        help="If provided, restrict health check to these tickers (no --all-tickers needed)",
    )
    args = ap.parse_args()

    try:
        from db import DB_PATH
    except Exception:
        DB_PATH = None  # type: ignore[misc, assignment]

    db_path = args.db or (Path(DB_PATH) if DB_PATH else None)
    if not db_path or not Path(db_path).is_file():
        print("daily_system_health_check: need existing --db or db.DB_PATH", file=sys.stderr)
        return 2

    tick_args = [t.strip().upper() for t in args.tickers if t.strip()]
    if tick_args:
        report = run_daily_health(
            db_path,
            all_tickers=False,
            primary_horizons_only=bool(args.primary_horizons or True),
            run_feature_contract=bool(args.feature_contract),
            ticker_filter=tick_args,
            universe_mode=str(args.universe),
        )
    else:
        report = run_daily_health(
            db_path,
            all_tickers=bool(args.all_tickers or True),
            primary_horizons_only=bool(args.primary_horizons or True),
            run_feature_contract=bool(args.feature_contract),
            ticker_filter=None,
            universe_mode=str(args.universe),
        )

    if args.write_report:
        write_reports(report, root=ROOT)

    sm = report.summary or {}
    print(
        f"overall_pass={report.overall_pass} tickers={len(report.tickers)} checks={len(report.checks)} "
        f"fail_checks={sm.get('fail_checks', '?')} warn_checks={sm.get('warn_checks', '?')} "
        f"universe={sm.get('universe_resolution', '')}"
    )
    for c in report.checks:
        print(f"  [{c.get('severity')}] {c.get('id')}: {c.get('message')}")

    return 0 if report.overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
