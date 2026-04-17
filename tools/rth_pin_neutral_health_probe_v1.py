#!/usr/bin/env python3
"""Evidence for forward RTH pin_neutral pipeline (read-only)."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from db import get_snapshot_sql  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--json-out", type=Path, default=None)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="tools.rth_pin_neutral_health_probe_v1", write_capable=False)
    conn = sqlite3.connect(str(args.db), timeout=60)
    conn.row_factory = sqlite3.Row
    now = time.time()
    fourteen_days_ago = now - 14 * 86400.0

    def q(sql, p=()):
        return conn.execute(sql, p).fetchone()

    out = {
        "schema": "rth_pin_neutral_health_probe_v1",
        "generated_ts_utc": now,
        "db_path": str(args.db.resolve()),
        "pin_neutral_1m_recent_14d": dict(
            q(
                get_snapshot_sql("tools/rth_pin_neutral_health_probe_v1.py:pin_1m_14d"),
                (fourteen_days_ago,),
            )
            or {}
        ),
        "pin_neutral_1m_rth_recent_14d": dict(
            q(
                get_snapshot_sql("tools/rth_pin_neutral_health_probe_v1.py:pin_1m_rth_14d"),
                (fourteen_days_ago,),
            )
            or {}
        ),
        "pin_neutral_5m_recent_14d": dict(
            q(
                get_snapshot_sql("tools/rth_pin_neutral_health_probe_v1.py:pin_5m_14d"),
                (fourteen_days_ago,),
            )
            or {}
        ),
        "note": (
            "Live server inserts snapshots with timeframe=CANONICAL_TIMEFRAME ('1m'); "
            "fill_outcomes(ticker,'1m',...) runs per server.py. "
            "5m pin_neutral rows are not filled by that path — repair/backfill only."
        ),
    }
    conn.close()
    text = json.dumps(out, indent=2, default=str) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
