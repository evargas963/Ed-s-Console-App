"""One-off diagnostic: outcome population on snapshots vs snapshots_1m_normalized."""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from db import DB_PATH, get_snapshot_sql

p = DB_PATHif not p.exists():
    print("NO_DB", p)
    raise SystemExit(1)

def counts(c, tbl: str):
    n = c.execute(f"SELECT COUNT(*) FROM {tbl} WHERE timeframe='1m'").fetchone()[0]
    o1 = c.execute(
        f"SELECT COUNT(*) FROM {tbl} WHERE timeframe='1m' AND outcome_1c IS NOT NULL"
    ).fetchone()[0]
    o5 = c.execute(
        f"SELECT COUNT(*) FROM {tbl} WHERE timeframe='1m' AND outcome_5c IS NOT NULL"
    ).fetchone()[0]
    o15 = c.execute(
        f"SELECT COUNT(*) FROM {tbl} WHERE timeframe='1m' AND outcome_15c IS NOT NULL"
    ).fetchone()[0]
    o60 = c.execute(
        f"SELECT COUNT(*) FROM {tbl} WHERE timeframe='1m' AND outcome_60c IS NOT NULL"
    ).fetchone()[0]
    return n, o1, o5, o15, o60


def main():
    c = sqlite3.connect(str(p))
    for tbl in ("snapshots_1m_normalized", "snapshots"):
        try:
            n, o1, o5, o15, o60 = counts(c, tbl)
            print(f"{tbl}: total_1m={n} outcome_1c={o1} outcome_5c={o5} outcome_15c={o15} outcome_60c={o60}")
        except Exception as e:
            print(tbl, "ERR", e)
    # pragma columns normalized
    row = c.execute("SELECT sql FROM sqlite_master WHERE name='snapshots_1m_normalized'").fetchone()
    if row and row[0]:
        s = row[0]
        for col in ("outcome_15c", "outcome_60c"):
            print(f"schema has {col}:", col in s)
    c.close()


def filled_vs_gaps():
    c = sqlite3.connect(str(p))
    q1 = c.execute(
        get_snapshot_sql("tools/_issue16_outcome_counts.py:47")
    ).fetchone()[0]
    q2 = c.execute(
        get_snapshot_sql("tools/_issue16_outcome_counts.py:51")
    ).fetchone()[0]
    qf0 = c.execute(
        get_snapshot_sql("tools/_issue16_outcome_counts.py:55")
    ).fetchone()[0]
    print(f"snapshots outcome_filled=1 but 15c NULL: {q1}")
    print(f"snapshots outcome_filled=1 but 60c NULL: {q2}")
    print(f"snapshots outcome_filled=0: {qf0}")


def last_in_bucket_15c():
    """How often does last snapshot per minute (resampling pick) have 15c?"""
    c = sqlite3.connect(str(p))
    c.row_factory = sqlite3.Row
    rows = c.execute(
        get_snapshot_sql("tools/_issue16_outcome_counts.py:67")
    ).fetchone()
    print(
        "last-per-minute rows:",
        dict(rows) if rows else {},
    )
    c.close()


if __name__ == "__main__":
    main()
    print("---")
    filled_vs_gaps()
    print("---")
    last_in_bucket_15c()
