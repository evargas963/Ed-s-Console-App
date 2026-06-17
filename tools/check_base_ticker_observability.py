#!/usr/bin/env python3
"""
Base money-path ticker RTH observability checker (SPY / QQQ / IWM).

Usage:
  python tools/check_base_ticker_observability.py --date 2026-06-16 --tickers SPY QQQ IWM
  python tools/check_base_ticker_observability.py --date 2026-06-16 --json-out reports/money_path/obs_2026-06-16.json

Exit 0 only when every listed base ticker is PASS_BASE_OBSERVABILITY.
Read-only — no DB mutation.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from db import DB_PATH
from money_path_ticker_tiers import BASE_MONEY_PATH_TICKERS, is_base_money_path_ticker
from verification.base_ticker_observability import (
    PASS_BASE_OBSERVABILITY,
    base_ticker_observability_report,
    format_observability_markdown,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Base ticker RTH observability gate")
    ap.add_argument("--date", required=True, help="Session date YYYY-MM-DD")
    ap.add_argument("--tickers", nargs="+", default=list(BASE_MONEY_PATH_TICKERS))
    ap.add_argument("--db", type=Path, default=Path(DB_PATH))
    ap.add_argument("--json-out", type=Path, default=None)
    ap.add_argument("--markdown-out", type=Path, default=None)
    ap.add_argument(
        "--skip-calibration-requirement",
        action="store_true",
        help="Do not fail on missing calibration_decision_log rows",
    )
    args = ap.parse_args(argv)

    tickers = [t.upper() for t in args.tickers]
    for t in tickers:
        if not is_base_money_path_ticker(t):
            print(f"WARN: {t} is not a base money-path ticker — guest symbols use lower trust tier", file=sys.stderr)

    day = datetime.date.fromisoformat(args.date.strip())
    report = base_ticker_observability_report(
        day=day,
        tickers=tickers,
        db_path=args.db,
        require_calibration_log=not args.skip_calibration_requirement,
    )

    print(format_observability_markdown(report))
    print(
        f"Summary: pass={report['summary']['pass_count']} fail={report['summary']['fail_count']} "
        f"universe_ready={report['meta']['base_universe_ready']}"
    )

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("Wrote", args.json_out)
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(format_observability_markdown(report), encoding="utf-8")
        print("Wrote", args.markdown_out)

    ok = all(r["coverage_status"] == PASS_BASE_OBSERVABILITY for r in report["tickers"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
