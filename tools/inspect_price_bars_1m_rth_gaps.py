#!/usr/bin/env python3
"""
List RTH-clock same-ET-date intraday gaps in price_bars_1m (diagnostic for daily health data_severe_intraday_gap).

Uses the same rules as verification.daily_health._gap_stats_bars for severe pairs, and can emit
the first N gap intervals with ET timestamps for Ed triage.

Example:
  python tools/inspect_price_bars_1m_rth_gaps.py --db data/ed_console.db --ticker AAPL --limit 20
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verification.daily_health import (  # noqa: E402
    INTRADAY_SEVERE_GAP_SEC,
    OVERNIGHT_GAP_SEC,
    _et_date,
    _et_weekday_mon0_sun6,
    _gap_stats_bars,
    _is_rth_bar_start,
)


def _et_hhmm(ts: float) -> str:
    from datetime import datetime, timezone

    from time_et import ET

    dt = datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(ET)
    return dt.strftime("%H:%M")


def iter_severe_pairs(conn: sqlite3.Connection, ticker: str, *, weekday_only: bool, limit: int):
    rows = [
        float(r[0])
        for r in conn.execute(
            "SELECT bar_start_ts_utc FROM price_bars_1m WHERE ticker=? ORDER BY bar_start_ts_utc ASC",
            (ticker,),
        ).fetchall()
    ]
    out = []
    for i in range(1, len(rows)):
        gap = rows[i] - rows[i - 1]
        if gap > OVERNIGHT_GAP_SEC or gap <= INTRADAY_SEVERE_GAP_SEC:
            continue
        if _et_date(rows[i]) != _et_date(rows[i - 1]):
            continue
        if not (_is_rth_bar_start(rows[i - 1]) and _is_rth_bar_start(rows[i])):
            continue
        if weekday_only and _et_weekday_mon0_sun6(rows[i]) >= 5:
            continue
        missing = max(0, int(gap // 60) - 1)
        out.append(
            {
                "ticker": ticker,
                "et_date": _et_date(rows[i]),
                "et_weekday": _et_weekday_mon0_sun6(rows[i]),
                "prior_bar_start_ts_utc": rows[i - 1],
                "next_bar_start_ts_utc": rows[i],
                "gap_sec": round(gap, 3),
                "expected_missing_1m_bars": missing,
                "prior_et_hhmm": _et_hhmm(rows[i - 1]),
                "next_et_hhmm": _et_hhmm(rows[i]),
            }
        )
        if len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect RTH-clock intraday 1m bar gaps (read-only)")
    ap.add_argument("--db", type=Path, required=True, help="SQLite DB path")
    ap.add_argument("--ticker", type=str, required=True, help="Ticker as stored in price_bars_1m")
    ap.add_argument("--limit", type=int, default=20, help="Max gap intervals to print")
    ap.add_argument(
        "--include-weekend-et",
        action="store_true",
        help="Also count gaps on Sat/Sun ET (daily health FAIL uses weekday-only)",
    )
    args = ap.parse_args()
    db_path = args.db
    if not db_path.is_file():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 2
    tkr = args.ticker.strip()
    conn = sqlite3.connect(str(db_path.resolve()))
    try:
        gs = _gap_stats_bars(conn, tkr)
        pairs = iter_severe_pairs(conn, tkr, weekday_only=not args.include_weekend_et, limit=args.limit)
        out = {"gap_stats": gs, "first_gap_intervals": pairs}
        print(json.dumps(out, indent=2))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
