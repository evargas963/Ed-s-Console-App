#!/usr/bin/env python3
"""Ticker coverage inventory: snapshots 1m per ticker (SQLite evidence)."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db import EdDB  # noqa: E402

DEFAULT_DB = ROOT / "data" / "ed_console.db"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--fail-on-orphans",
        action="store_true",
        help="Exit 1 if any distinct 1m snapshot ticker is missing from logging_universe (Issue 22 drift).",
    )
    args = ap.parse_args()
    conn = sqlite3.connect(str(args.db.resolve()))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT ticker,
               COUNT(*) AS n,
               MIN(ts_utc) AS min_ts,
               MAX(ts_utc) AS max_ts,
               COUNT(DISTINCT strftime('%Y-%m-%d', ts_utc, 'unixepoch')) AS n_days
        FROM snapshots
        WHERE timeframe = '1m'
        GROUP BY ticker
        ORDER BY n ASC
        """
    ).fetchall()

    # logging_universe tickers
    lu: dict[str, str] = {}
    try:
        for r in conn.execute("SELECT ticker, category FROM logging_universe"):
            lu[str(r["ticker"]).upper()] = str(r["category"])
    except sqlite3.OperationalError:
        lu = {}

    per: list[dict] = []
    now = __import__("time").time()
    for r in rows:
        t = r["ticker"]
        ts_list = [
            float(x[0])
            for x in conn.execute(
                "SELECT ts_utc FROM snapshots WHERE timeframe = '1m' AND ticker = ? ORDER BY ts_utc",
                (t,),
            ).fetchall()
        ]
        gaps = [ts_list[i] - ts_list[i - 1] for i in range(1, len(ts_list))]
        max_gap = max(gaps) if gaps else 0.0
        by_day = conn.execute(
            """
            SELECT strftime('%Y-%m-%d', ts_utc, 'unixepoch') AS d, COUNT(*) AS c
            FROM snapshots WHERE timeframe = '1m' AND ticker = ?
            GROUP BY d ORDER BY d
            """,
            (t,),
        ).fetchall()
        day_counts = [int(x["c"]) for x in by_day]
        max_ts = float(r["max_ts"])
        recent_tail = (now - max_ts) < 7 * 86400  # 7d heuristic
        in_lu = lu.get(str(t).upper())
        per.append(
            {
                "ticker": t,
                "row_count": int(r["n"]),
                "min_ts_utc": r["min_ts"],
                "max_ts_utc": r["max_ts"],
                "distinct_utc_days": int(r["n_days"]),
                "per_day_row_count_min_max": [min(day_counts), max(day_counts)] if day_counts else [0, 0],
                "max_gap_seconds_between_consecutive_rows": round(max_gap, 3),
                "logging_universe_category": in_lu,
                "recent_tail_7d_heuristic": recent_tail,
            }
        )

    asc = sorted(per, key=lambda x: x["row_count"])
    desc = sorted(per, key=lambda x: x["row_count"], reverse=True)

    try:
        orphans = EdDB(args.db.resolve()).logging_universe_snapshot_ticker_orphans()
    except Exception:
        snap_tickers = {str(x["ticker"]).upper() for x in rows}
        orphans = sorted(snap_tickers - set(lu.keys()))

    out = {
        "db": str(args.db.resolve()),
        "n_tickers": len(per),
        "tickers_sorted_by_row_count_asc": asc,
        "tickers_sorted_by_row_count_desc": desc,
        "snapshot_tickers_not_in_logging_universe": orphans,
        "logging_universe_row_count": len(lu),
    }
    print(json.dumps(out, indent=2))
    conn.close()
    if args.fail_on_orphans and orphans:
        sys.exit(1)


if __name__ == "__main__":
    main()
