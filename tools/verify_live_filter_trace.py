"""CLI: Phase 2 similar-set + empirical trace for one or more tickers (latest snapshot params)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db import get_db, get_snapshot_sql
from timeframe_config import CANONICAL_TIMEFRAME
from verification.similar_set_trace import full_similar_and_empirical_trace


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="+", help="e.g. SPY QQQ")
    ap.add_argument("--as-of-replay", action="store_true", help="use ts_utc < latest bar (honest replay cut)")
    args = ap.parse_args()
    db = get_db()
    tf = CANONICAL_TIMEFRAME
    for tkr in args.tickers:
        tkr = tkr.upper().strip()
        with db._connect() as conn:
            row = conn.execute(
                get_snapshot_sql("tools/verify_live_filter_trace.py:27"),
                (tkr, tf),
            ).fetchone()
        if not row:
            print(json.dumps({"ticker": tkr, "error": "no rows"}, indent=2))
            continue
        d = dict(row)
        as_of = float(d["ts_utc"]) if args.as_of_replay else None
        trace = full_similar_and_empirical_trace(
            db,
            ticker=tkr,
            timeframe=tf,
            zone=d["zone"] or "unknown",
            vwap_side=d["vwap_side"] or "above",
            nearest_above_dist=d["nearest_above_dist"],
            nearest_below_dist=d["nearest_below_dist"],
            as_of_ts_utc=as_of,
        )
        print(json.dumps(trace, indent=2, default=str))


if __name__ == "__main__":
    main()
