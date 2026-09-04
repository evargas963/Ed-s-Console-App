"""
Diagnostic only — not referenced by production runbooks or schedulers.

Compares Issue-14 trainable row counts on snapshots_1m_normalized using RTH from ts_utc
(DST-aware via is_rth_ts_utc), not stored et_hour SQL (FIND-CAL-TS).

  python tools/_issue14_rowcount_proof.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db import DB_PATH
from ml_data_common import weekday_where_clause
from app.domain.time_et import is_rth_ts_utc
from timeframe_config import CANONICAL_TIMEFRAME, SNAPSHOT_TABLE_1M

p = DB_PATH
if not p.exists():
    print("NO_DB at", p)
    raise SystemExit(0)

conn = sqlite3.connect(str(p))
tf = CANONICAL_TIMEFRAME
base = f"timeframe='{tf}' AND ({weekday_where_clause()})"


def count_rth(extra_where: str) -> int:
    rows = conn.execute(
        f"SELECT ts_utc FROM {SNAPSHOT_TABLE_1M} WHERE {base} AND {extra_where}"
    ).fetchall()
    n = 0
    for (ts_utc,) in rows:
        try:
            if is_rth_ts_utc(float(ts_utc)):
                n += 1
        except (TypeError, ValueError):
            continue
    return n


n_old = count_rth("outcome_filled=1 AND outcome_1c IS NOT NULL")
n_new = count_rth("outcome_1c IS NOT NULL")
n5 = count_rth("outcome_5c IS NOT NULL")
n15 = count_rth("outcome_15c IS NOT NULL")
n60 = count_rth("outcome_60c IS NOT NULL")
conn.close()
print("LIVE_DB_ROW_COUNTS (RTH weekday via ts_utc, snapshots_1m_normalized):")
print("  legacy (outcome_filled=1 AND outcome_1c):", n_old)
print("  Issue14 1c (outcome_1c IS NOT NULL):     ", n_new)
print("  outcome_5c IS NOT NULL:                  ", n5)
print("  outcome_15c IS NOT NULL:                 ", n15)
print("  outcome_60c IS NOT NULL:                 ", n60)
print("  extra 1c-eligible rows after fix:       ", n_new - n_old)
