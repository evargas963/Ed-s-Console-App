"""Measure the shared Schwab socket against the option load it carries (read-only).

For each hour of a session, reports how many additional option contracts the daemon held
(open LEVELONE_OPTIONS coverage epochs, sampled each minute), how many stream recycles
happened, and how the SPY LEVELONE_EQUITIES feed behaved (rows, gaps > 60 s, max gap).
This is the evidence stream_spine.OPTION_CONTRACTS_MAX_HELD moves on: the budget is right
when recycles are ~0 and SPY never goes quiet for a minute at the held counts it allows.

    python tools/stream_socket_budget_probe.py                 # today, 08:30-15:00 CT
    python tools/stream_socket_budget_probe.py --date 2026-09-23 --symbol SPY
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stream_spine import resolve_stream_db_path  # noqa: E402


def measure(db_path: Path, day: dt.date, symbol: str, start_hm=(8, 30), end_hm=(15, 0)) -> list[dict]:
    con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True, timeout=30.0)
    try:
        t0 = time.mktime(dt.datetime(day.year, day.month, day.day, *start_hm).timetuple())
        t1 = time.mktime(dt.datetime(day.year, day.month, day.day, *end_hm).timetuple())
        epochs = con.execute(
            "SELECT started_ts, COALESCE(ended_ts, ?) FROM stream_coverage_epochs "
            "WHERE service='LEVELONE_OPTIONS' AND started_ts < ? AND COALESCE(ended_ts, ?) > ?",
            (t1, t1, t1, t0)).fetchall()
        recycles = [r[0] for r in con.execute(
            "SELECT DISTINCT round(ended_ts, 0) FROM stream_coverage_epochs "
            "WHERE reason='stream_recycle' AND ended_ts BETWEEN ? AND ?", (t0, t1))]
        ticks = [r[0] for r in con.execute(
            "SELECT ts_recv FROM stream_quotes_raw WHERE symbol=? AND src='schwab_l1' "
            "AND ts_recv BETWEEN ? AND ? ORDER BY ts_recv", (symbol, t0, t1))]
    finally:
        con.close()
    rows = []
    h = t0
    while h < t1:
        e = min(h + 3600, t1)
        held = [sum(1 for s, en in epochs if s <= m < en) for m in range(int(h), int(e), 60)]
        tk = [t for t in ticks if h <= t < e]
        gaps = [b - a for a, b in zip(tk, tk[1:])]
        rows.append({
            "hour": dt.datetime.fromtimestamp(h).strftime("%H:%M"),
            "held_avg": round(sum(held) / len(held)) if held else 0,
            "held_max": max(held) if held else 0,
            "recycles": sum(1 for r in recycles if h <= r < e),
            f"{symbol}_rows": len(tk),
            "gaps_over_60s": sum(1 for g in gaps if g > 60),
            "max_gap_s": round(max(gaps)) if gaps else None,
        })
        h = e
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--db", default=None)
    a = ap.parse_args(argv)
    rows = measure(resolve_stream_db_path(a.db), dt.date.fromisoformat(a.date), a.symbol.upper())
    if not rows:
        print("no session window")
        return 1
    keys = list(rows[0])
    print("  ".join(f"{k:>14}" for k in keys))
    for r in rows:
        print("  ".join(f"{str(r[k]):>14}" for k in keys))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
