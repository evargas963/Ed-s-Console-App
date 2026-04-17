"""CLI: Phase 6 threshold stress on latest similar-set for a ticker."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db import get_db
from timeframe_config import CANONICAL_TIMEFRAME
from verification.threshold_stress import threshold_stress_on_similar


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    args = ap.parse_args()
    db = get_db()
    tf = CANONICAL_TIMEFRAME
    tkr = args.ticker.upper().strip()
    with db._connect() as conn:
        row = conn.execute(
            get_snapshot_sql("tools/verify_threshold_stress.py:25"),
            (tkr, tf),
        ).fetchone()
    if not row:
        print(json.dumps({"error": "no rows"}))
        return
    d = dict(row)
    similar = db.get_similar_setups(
        ticker=tkr,
        timeframe=tf,
        zone=d["zone"] or "unknown",
        vwap_side=d["vwap_side"] or "above",
        nearest_above_dist=d["nearest_above_dist"],
        nearest_below_dist=d["nearest_below_dist"],
    )
    print(json.dumps(threshold_stress_on_similar(similar), indent=2, default=str))


if __name__ == "__main__":
    main()
