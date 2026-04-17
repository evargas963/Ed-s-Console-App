"""One-off diagnostic: compare legacy vs Issue-14 trainable counts (run from repo root)."""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db import DB_PATH
from ml_data_common import rth_where_clause, weekday_where_clause
from timeframe_config import CANONICAL_TIMEFRAME, SNAPSHOT_TABLE_1M

p = DB_PATH
if not p.exists():
    print("NO_DB at", p)
    raise SystemExit(0)

conn = sqlite3.connect(str(p))
tf = CANONICAL_TIMEFRAME
base = f"timeframe='{tf}' AND {rth_where_clause()} AND ({weekday_where_clause()})"


def c(sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0])


n_old = c(
    f"SELECT COUNT(*) FROM {SNAPSHOT_TABLE_1M} WHERE {base} "
    "AND outcome_filled=1 AND outcome_1c IS NOT NULL"
)
n_new = c(
    f"SELECT COUNT(*) FROM {SNAPSHOT_TABLE_1M} WHERE {base} AND outcome_1c IS NOT NULL"
)
n5 = c(f"SELECT COUNT(*) FROM {SNAPSHOT_TABLE_1M} WHERE {base} AND outcome_5c IS NOT NULL")
n15 = c(f"SELECT COUNT(*) FROM {SNAPSHOT_TABLE_1M} WHERE {base} AND outcome_15c IS NOT NULL")
n60 = c(f"SELECT COUNT(*) FROM {SNAPSHOT_TABLE_1M} WHERE {base} AND outcome_60c IS NOT NULL")
conn.close()
print("LIVE_DB_ROW_COUNTS (RTH weekday, snapshots_1m_normalized):")
print("  legacy (outcome_filled=1 AND outcome_1c):", n_old)
print("  Issue14 1c (outcome_1c IS NOT NULL):     ", n_new)
print("  outcome_5c IS NOT NULL:                  ", n5)
print("  outcome_15c IS NOT NULL:                 ", n15)
print("  outcome_60c IS NOT NULL:                 ", n60)
print("  extra 1c-eligible rows after fix:       ", n_new - n_old)
