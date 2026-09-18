#!/usr/bin/env python3
"""Read-only SQLite evidence for canonical timeframe / horizon audits (Issue 19)."""
from __future__ import annotations

from pathlib import Path

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import DB_PATH, get_snapshot_sql


import argparse
import sqlite3


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("db", nargs="?", type=Path, default=DB_PATH, help="Path to SQLite DB")
    register_allow_noncanonical_flag(p)
    args = p.parse_args()
    require_canonical_db_target(args, tool_name="tools.canonical_timeframe_db_evidence_v1", write_capable=False)
    c = sqlite3.connect(str(args.db))
    bars = [
        r[0]
        for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%bar%'"
        ).fetchall()
    ]
    print("bar_like_tables", bars)
    pn5 = c.execute(
        get_snapshot_sql("tools/canonical_timeframe_db_evidence_v1.py:24")
    ).fetchone()
    print("pin_neutral_5m_min_max_count", pn5)
    s1 = c.execute(
        get_snapshot_sql("tools/canonical_timeframe_db_evidence_v1.py:26")
    ).fetchone()
    print("snapshots_1m_min_max_count", s1)
    print(
        "snapshots_by_tf",
        c.execute(get_snapshot_sql("tools/canonical_timeframe_db_evidence_v1.py:32")).fetchall(),
    )


if __name__ == "__main__":
    main()
