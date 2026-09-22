"""Verify normalized outcome_15c/60c matches last snapshot in same minute bucket (sample)."""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from db import DB_PATH, get_snapshot_sql

p = DB_PATH
c = sqlite3.connect(str(p))
c.row_factory = sqlite3.Row

row = c.execute(
    """
    SELECT ticker, ts_utc, outcome_15c, outcome_60c, outcome_15c_pts, outcome_60c_pts
    FROM snapshots_1m_normalized
    WHERE ticker = 'SPY' AND outcome_15c IS NOT NULL AND outcome_60c IS NOT NULL
    ORDER BY ts_utc DESC
    LIMIT 1
    """
).fetchone()
if not row:
    print("no sample row")
else:
    bucket = int(float(row["ts_utc"]) // 60)
    s = c.execute(
        get_snapshot_sql("tools/_issue16_verify_row_match.py:22"),
        (bucket,),
    ).fetchone()
    print("normalized ts_utc", row["ts_utc"], "15c", row["outcome_15c"], "60c", row["outcome_60c"])
    if s:
        print("snapshots last same bucket ts_utc", s["ts_utc"])
        ok = (
            row["outcome_15c"] == s["outcome_15c"]
            and row["outcome_60c"] == s["outcome_60c"]
            and abs(float(row["outcome_15c_pts"] or 0) - float(s["outcome_15c_pts"] or 0)) < 1e-4
            and abs(float(row["outcome_60c_pts"] or 0) - float(s["outcome_60c_pts"] or 0)) < 1e-4
        )
        print("match", ok)
    else:
        print("no snapshot in bucket")

c.close()
