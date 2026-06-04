"""CLI: Phase 3 horizon health from DB latest similar-set."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db import get_db, get_snapshot_sql
from timeframe_config import CANONICAL_TIMEFRAME
from verification.horizon_health import horizon_health_report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    args = ap.parse_args()
    db = get_db()
    tf = CANONICAL_TIMEFRAME
    tkr = args.ticker.upper().strip()
    with db._connect() as conn:
        row = conn.execute(
            get_snapshot_sql("tools/verify_horizon_health.py:25"),
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
    print(json.dumps(horizon_health_report(similar), indent=2, default=str))


if __name__ == "__main__":
    main()
