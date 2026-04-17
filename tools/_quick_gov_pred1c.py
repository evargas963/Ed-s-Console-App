import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOV = """
s.timeframe = '1m' AND s.horizon_outcome_schema_version = 3
AND EXISTS (SELECT 1 FROM price_bars_1m p WHERE p.ticker = s.ticker AND p.bar_end_ts_utc <= s.ts_utc)
AND s.outcome_1c IS NOT NULL AND s.outcome_3c IS NOT NULL AND s.outcome_5c IS NOT NULL
AND s.outcome_8c IS NOT NULL AND s.outcome_13c IS NOT NULL AND s.outcome_15c IS NOT NULL
AND s.outcome_60c IS NOT NULL
"""
c = sqlite3.connect(str(ROOT / "data" / "ed_console.db"))
n = c.execute(f"SELECT COUNT(*) FROM snapshots s WHERE {GOV}").fetchone()[0]
p = c.execute(f"SELECT COUNT(*) FROM snapshots s WHERE {GOV} AND s.pred_1c_up_prob IS NOT NULL").fetchone()[0]
print("governed", n, "pred_1c", p)
