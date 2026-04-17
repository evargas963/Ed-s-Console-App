#!/usr/bin/env python3
"""
audit_snapshot_data.py - Factual audit of snapshots table
=========================================================
Runs SQL against the actual DB to verify:
- Timestamp spacing (avg/min/max gap)
- Rows per minute
- Intrabar OHLC behavior
- Reset cadence

Run: python audit_snapshot_data.py
"""
from db import get_snapshot_sql

import sys
if sys.stdout.encoding and "cp1252" in sys.stdout.encoding.lower():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import sqlite3
from pathlib import Path
from collections import defaultdict

from db import DB_PATH

TICKERS = ["SPY", "QQQ", "IWM"]


def connect():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB not found: {DB_PATH}")
    return sqlite3.connect(str(DB_PATH))


def run_audit():
    conn = connect()
    conn.row_factory = sqlite3.Row

    print("=" * 72)
    print("SNAPSHOT DATA AUDIT - Code + DB Evidence")
    print("=" * 72)

    for ticker in TICKERS:
        print(f"\n{'-' * 72}")
        print(f"TICKER: {ticker}")
        print("-" * 72)

        # A. Timestamp spacing
        rows = conn.execute(get_snapshot_sql("audit_snapshot_data.py:48"), (ticker,)).fetchall()

        if len(rows) < 2:
            print(f"  [SKIP] Only {len(rows)} rows")
            continue

        gaps = []
        for i in range(1, len(rows)):
            gap = rows[i]["ts_utc"] - rows[i - 1]["ts_utc"]
            gaps.append(gap)

        print(f"\n  A. Timestamp spacing (consecutive rows):")
        print(f"     Rows: {len(rows)}")
        print(f"     Avg gap: {sum(gaps)/len(gaps):.1f} sec")
        print(f"     Min gap: {min(gaps):.1f} sec")
        print(f"     Max gap: {max(gaps):.1f} sec")

        # B. Rows per minute
        minute_counts = defaultdict(int)
        for r in rows:
            # ts_utc is unix; bucket by minute (ET-aligned via ts_et for display, but use utc for grouping)
            bucket = int(r["ts_utc"] // 60)
            minute_counts[bucket] += 1

        counts = list(minute_counts.values())
        print(f"\n  B. Rows per minute bucket:")
        print(f"     Minutes with data: {len(minute_counts)}")
        if counts:
            print(f"     Avg rows/min: {sum(counts)/len(counts):.1f}")
            print(f"     Min rows/min: {min(counts)}")
            print(f"     Max rows/min: {max(counts)}")

        # C. Intrabar behavior — sample consecutive rows
        print(f"\n  C. Sample consecutive rows (first 15):")
        print(f"     {'ts_et':<22} {'gap':>6} {'open':>8} {'high':>8} {'low':>8} {'close':>8} {'vol':>10}")
        for i in range(min(15, len(rows))):
            r = rows[i]
            gap = (rows[i]["ts_utc"] - rows[i - 1]["ts_utc"]) if i > 0 else 0
            print(f"     {str(r['ts_et']):<22} {gap:>5.0f}s {r['candle_open'] or 0:>8.2f} {r['candle_high'] or 0:>8.2f} {r['candle_low'] or 0:>8.2f} {r['candle_close'] or 0:>8.2f} {r['candle_volume'] or 0:>10.0f}")

        # D. Reset cadence - when does open change? (exclude gaps > 600s = likely session break)
        open_changes = []
        prev_open = None
        prev_ts = None
        for r in rows:
            o = r["candle_open"]
            if o is not None and prev_open is not None and abs(float(o) - float(prev_open)) > 0.001:
                gap = r["ts_utc"] - prev_ts if prev_ts else 0
                open_changes.append((prev_ts, r["ts_utc"], gap))
            if o is not None:
                prev_open = o
            prev_ts = r["ts_utc"]

        # Intra-session only (gap < 10 min) to avoid overnight skew
        in_session = [c[2] for c in open_changes if 0 < c[2] < 600]
        print(f"\n  D. Reset cadence (open changes = new bar):")
        print(f"     Open changed {len(open_changes)} times total")
        if in_session:
            print(f"     In-session (gap < 10min): {len(in_session)} bar boundaries")
            print(f"     Avg bar length: {sum(in_session)/len(in_session):.0f} sec ({sum(in_session)/len(in_session)/60:.2f} min)")
            print(f"     Min: {min(in_session):.0f}s  Max: {max(in_session):.0f}s")

    # Cross-ticker summary
    print(f"\n{'=' * 72}")
    print("SUMMARY: timeframe distribution")
    print("=" * 72)
    for row in conn.execute(get_snapshot_sql("audit_snapshot_data.py:119")).fetchall():
        print(f"  timeframe={row['timeframe']!r}: {row['c']:,} rows")

    conn.close()
    print()


if __name__ == "__main__":
    run_audit()
