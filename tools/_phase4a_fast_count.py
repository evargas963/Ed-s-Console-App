import json
import sqlite3
from collections import defaultdict
from pathlib import Path

conn = sqlite3.connect(str(Path(__file__).resolve().parent.parent / "data" / "ed_console.db"))
conn.row_factory = sqlite3.Row

total = conn.execute("SELECT COUNT(*) AS n FROM snapshots WHERE timeframe='1m'").fetchone()["n"]
miss = conn.execute(
    """
    SELECT s.snapshot_id, s.ticker, s.ts_utc
    FROM snapshots s
    JOIN (
        SELECT ticker, MIN(bar_end_ts_utc) AS mbe
        FROM price_bars_1m
        GROUP BY ticker
    ) x ON x.ticker = s.ticker
    WHERE s.timeframe = '1m'
      AND s.ts_utc < x.mbe
    """
).fetchall()

bt = defaultdict(int)
for r in miss:
    bt[r["ticker"]] += 1

tr = conn.execute(
    """
    SELECT COUNT(*) AS n
    FROM calibration_decision_log c
    JOIN snapshots s ON s.ticker = c.ticker AND s.ts_utc = c.decision_ts_utc AND s.timeframe = '1m'
    JOIN (
        SELECT ticker, MIN(bar_end_ts_utc) AS mbe
        FROM price_bars_1m
        GROUP BY ticker
    ) x ON x.ticker = s.ticker
    WHERE c.calibration_trust = 'trusted'
      AND s.ts_utc < x.mbe
    """
).fetchone()["n"]

tot_tr = conn.execute(
    "SELECT COUNT(*) FROM calibration_decision_log WHERE calibration_trust = 'trusted'"
).fetchone()[0]

print(
    json.dumps(
        {
            "total_snapshots_1m": total,
            "no_anchor_count": len(miss),
            "pct_of_1m": round(100.0 * len(miss) / total, 6),
            "trusted_no_anchor": tr,
            "trusted_total": tot_tr,
            "pct_trusted": round(100.0 * tr / tot_tr, 6) if tot_tr else 0,
            "unique_tickers": len(bt),
            "by_ticker": dict(sorted(bt.items(), key=lambda x: -x[1])[:30]),
        },
        indent=2,
    )
)
conn.close()
