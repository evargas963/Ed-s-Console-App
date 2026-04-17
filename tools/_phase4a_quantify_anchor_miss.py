"""One-off quantification for Phase 4A — run: python tools/_phase4a_quantify_anchor_miss.py"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "ed_console.db"


def main() -> None:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    total_1m = conn.execute(
        "SELECT COUNT(*) AS n FROM snapshots WHERE timeframe='1m'"
    ).fetchone()["n"]

    miss = conn.execute(
        """
        SELECT s.snapshot_id, s.ticker, s.ts_utc
        FROM snapshots s
        WHERE s.timeframe = '1m'
          AND NOT EXISTS (
            SELECT 1 FROM price_bars_1m p
            WHERE p.ticker = s.ticker AND p.bar_end_ts_utc <= s.ts_utc
          )
        """
    ).fetchall()

    by_ticker: dict[str, int] = defaultdict(int)
    ts_min: dict[str, float] = {}
    ts_max: dict[str, float] = {}
    for r in miss:
        t = r["ticker"]
        by_ticker[t] += 1
        tu = float(r["ts_utc"])
        ts_min[t] = min(ts_min.get(t, tu), tu)
        ts_max[t] = max(ts_max.get(t, tu), tu)

    tr = conn.execute(
        """
        SELECT COUNT(*) AS n FROM calibration_decision_log c
        JOIN snapshots s ON s.ticker = c.ticker AND s.ts_utc = c.decision_ts_utc AND s.timeframe='1m'
        WHERE c.calibration_trust='trusted'
          AND NOT EXISTS (
            SELECT 1 FROM price_bars_1m p WHERE p.ticker = s.ticker AND p.bar_end_ts_utc <= s.ts_utc
          )
        """
    ).fetchone()["n"]

    tot_tr = conn.execute(
        "SELECT COUNT(*) FROM calibration_decision_log WHERE calibration_trust='trusted'"
    ).fetchone()[0]

    out = {
        "total_snapshots_1m": total_1m,
        "no_anchor_count": len(miss),
        "pct_of_all_1m": round(100.0 * len(miss) / total_1m, 6) if total_1m else 0,
        "trusted_calib_no_anchor": tr,
        "trusted_calib_total": tot_tr,
        "pct_trusted_no_anchor": round(100.0 * tr / tot_tr, 6) if tot_tr else 0,
        "unique_tickers_affected": len(by_ticker),
        "by_ticker_miss_count": dict(sorted(by_ticker.items(), key=lambda x: -x[1])),
        "per_ticker_ts_range": {
            t: {"min_ts_utc": ts_min[t], "max_ts_utc": ts_max[t], "n": by_ticker[t]}
            for t in sorted(by_ticker.keys())
        },
    }
    print(json.dumps(out, indent=2))
    conn.close()


if __name__ == "__main__":
    main()
