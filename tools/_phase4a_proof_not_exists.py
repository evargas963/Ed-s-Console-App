import sqlite3
from pathlib import Path

conn = sqlite3.connect(str(Path(__file__).resolve().parent.parent / "data" / "ed_console.db"))
n = conn.execute(
    """
    SELECT COUNT(*) FROM snapshots s
    WHERE s.timeframe = '1m'
      AND NOT EXISTS (
        SELECT 1 FROM price_bars_1m p
        WHERE p.ticker = s.ticker AND p.bar_end_ts_utc <= s.ts_utc
      )
    """
).fetchone()[0]
print("NOT_EXISTS_NO_ANCHOR_COUNT", n)
conn.close()
