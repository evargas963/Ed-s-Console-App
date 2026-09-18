import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from db import DB_PATH

p = DB_PATH
c = sqlite3.connect(str(p))


def cols(tbl):
    return [r[1] for r in c.execute(f"PRAGMA table_info({tbl})").fetchall()]


a, b = set(cols("snapshots")), set(cols("snapshots_1m_normalized"))
print("only in snapshots", sorted(a - b)[:30], "count", len(a - b))
print("only in normalized", sorted(b - a)[:30], "count", len(b - a))

# order-sensitive: outcome_* positions
for tbl in ("snapshots", "snapshots_1m_normalized"):
    col_list = cols(tbl)
    for name in ("outcome_15c", "outcome_60c"):
        if name in col_list:
            print(tbl, name, "index", col_list.index(name))
