import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))
from db import DB_PATH

conn = sqlite3.connect(str(DB_PATH), timeout=120.0)
conn.row_factory = sqlite3.Row
ts = 1775926978.9349923
r = conn.execute(
    "SELECT * FROM snapshots WHERE ticker=? AND ts_utc=? AND timeframe='1m'",
    ("SPY", ts),
).fetchone()
print(dict(r) if r else None)
# max bar end for SPY
m = conn.execute(
    "SELECT MAX(bar_end_ts_utc) mx FROM price_bars_1m WHERE ticker=?",
    ("SPY",),
).fetchone()
print("max_bar_end", m["mx"])
import time

print("time.time()", time.time())
conn.close()
