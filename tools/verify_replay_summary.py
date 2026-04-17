"""CLI: Phase 5 replay summary (SPY vs QQQ by default)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db import get_db
from verification.replay_diagnostic import replay_summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="SPY,QQQ", help="comma-separated")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--stride", type=int, default=2)
    ap.add_argument("--no-as-of", action="store_true", help="disable ts_utc < bar replay cut")
    args = ap.parse_args()
    db = get_db()
    tk = tuple(x.strip().upper() for x in args.tickers.split(",") if x.strip())
    out = replay_summary(
        db,
        tickers=tk,
        limit_bars=args.limit,
        stride=args.stride,
        as_of_honest=not args.no_as_of,
    )
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
