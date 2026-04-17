"""CLI: Phase 1 database coverage (SPY, QQQ, IWM by default)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from verification.db_coverage import db_coverage_report


def main() -> None:
    ap = argparse.ArgumentParser(description="DB coverage verification")
    ap.add_argument("tickers", nargs="*", default=["SPY", "QQQ", "IWM"])
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()
    r = db_coverage_report([t.upper() for t in args.tickers])
    print(r["human_summary"])
    if args.json_out:
        args.json_out.write_text(json.dumps(r["machine"], indent=2, default=str), encoding="utf-8")
        print("Wrote", args.json_out)
    else:
        print("--- machine JSON ---")
        print(json.dumps(r["machine"], indent=2, default=str))


if __name__ == "__main__":
    main()
