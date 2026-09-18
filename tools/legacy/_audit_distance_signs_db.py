"""Emit distance sign stats for Option A migration planning (read-only)."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from db import DB_PATH, get_snapshot_sql

DB = DB_PATH

from timeframe_config import CANONICAL_TIMEFRAME

_TF = CANONICAL_TIMEFRAME


def main() -> None:
    if not DB.is_file():
        print(json.dumps({"error": "db_not_found", "path": str(DB)}))
        return
    c = sqlite3.connect(str(DB))
    out: dict = {}

    def q(sql: str, params: tuple = ()) -> int:
        return int(c.execute(sql, params).fetchone()[0])

    out["timeframe_scope"] = _TF
    out["snapshots_total"] = q(
        get_snapshot_sql("tools/_audit_distance_signs_db.py:31"), (_TF,)
    )
    out["snapshots_outcome_1c_not_null"] = q(
        get_snapshot_sql("tools/_audit_distance_signs_db.py:34"), (_TF,)
    )
    out["nad_negative"] = q(
        get_snapshot_sql("tools/_audit_distance_signs_db.py:37"), (_TF,)
    )
    out["nad_nonnegative_or_null"] = q(
        get_snapshot_sql("tools/_audit_distance_signs_db.py:40"),
        (_TF,),
    )
    out["nbd_negative"] = q(
        get_snapshot_sql("tools/_audit_distance_signs_db.py:44"), (_TF,)
    )
    out["nbd_nonnegative_nonnull"] = q(
        get_snapshot_sql("tools/_audit_distance_signs_db.py:47"),
        (_TF,),
    )
    out["nbd_null"] = q(
        get_snapshot_sql("tools/_audit_distance_signs_db.py:51"), (_TF,)
    )
    out["both_nonnegative_nonnull_optionA"] = q(
        get_snapshot_sql("tools/_audit_distance_signs_db.py:54"),
        (_TF,),
    )
    row = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='snapshots_1m_normalized'"
    ).fetchone()
    if row:
        out["snapshots_1m_normalized_rows"] = q("SELECT COUNT(*) FROM snapshots_1m_normalized")
        out["snapshots_1m_normalized_nbd_negative"] = q(
            "SELECT COUNT(*) FROM snapshots_1m_normalized WHERE nearest_below_dist < 0"
        )
    else:
        out["snapshots_1m_normalized_rows"] = None
    c.close()
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
