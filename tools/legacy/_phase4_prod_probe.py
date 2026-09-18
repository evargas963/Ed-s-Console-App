"""One-off probe; delete after Phase 4."""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))
from db import DB_PATH

conn = sqlite3.connect(str(DB_PATH), timeout=120.0)
conn.row_factory = sqlite3.Row
r = conn.execute(
    "SELECT id,ticker,decision_ts_utc,outcome_5c FROM calibration_decision_log WHERE calibration_trust='trusted'"
).fetchone()
print("trusted", dict(r) if r else None)
if r:
    s = conn.execute(
        "SELECT ts_utc,timeframe,outcome_5c FROM snapshots WHERE ticker=? AND ts_utc=?",
        (r["ticker"], r["decision_ts_utc"]),
    ).fetchall()
    print("snapshots", [dict(x) for x in s])
conn.close()
