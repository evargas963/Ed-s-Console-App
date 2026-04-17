#!/usr/bin/env python3
"""
Repair interior holes on the canonical 60s UTC grid between existing price_bars_1m rows.

For each missing grid point g strictly between bar_start_lo and bar_start_hi (both existing),
insert one bar with OHLC linearly interpolated in time between closes at lo and hi.

Does NOT repair "before first bar" or "after last bar" gaps (requires Schwab rehydration).

After inserts, callers should run EdDB.fill_outcomes per ticker and calibration.backfill_outcomes.
"""
from __future__ import annotations

import argparse
import bisect
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.canonical_1m_grid_scan import scan_db
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from db import EdDB, configure_sqlite_connection
from horizon_outcomes import SYNTHETIC_INTERIOR_GRID_REPAIR_V1

try:
    from timeframe_config import CANONICAL_TIMEFRAME
except Exception:
    CANONICAL_TIMEFRAME = "1m"


def _collect_interior_missing(db_path: Path, tz_now: float) -> list[tuple[str, float, float, float, float]]:
    """
    Returns list of (ticker, g, lo, hi, close_g) for synthetic bars to insert.
    lo/hi are neighboring existing bar_start_ts_utc with lo < g < hi on the 60s grid.
    """
    conn = sqlite3.connect(str(db_path), timeout=120.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)

    starts_by: dict[str, list[float]] = {}
    closes: dict[tuple[str, float], float] = {}
    for r in conn.execute("SELECT ticker, bar_start_ts_utc, close FROM price_bars_1m"):
        t = r["ticker"]
        s = float(r["bar_start_ts_utc"])
        starts_by.setdefault(t, []).append(s)
        closes[(t, s)] = float(r["close"])
    for t in starts_by:
        starts_by[t].sort()

    rscan = scan_db(db_path, tz_now_utc=tz_now)
    need: set[tuple[str, float]] = set()
    for rec in rscan.missing_forward:
        need.add((rec["ticker"], float(rec["required_bar_start_ts_utc"])))

    out: list[tuple[str, float, float, float, float]] = []
    for tkr, g in need:
        arr = starts_by.get(tkr)
        if not arr:
            continue
        i = bisect.bisect_left(arr, g)
        if i == 0 or i == len(arr):
            continue
        lo = arr[i - 1]
        hi = arr[i]
        if not (lo < g < hi):
            continue
        c_lo = closes[(tkr, lo)]
        c_hi = closes[(tkr, hi)]
        span = hi - lo
        if span <= 0:
            continue
        frac = (g - lo) / span
        c_g = c_lo + frac * (c_hi - c_lo)
        out.append((tkr, g, lo, hi, c_g))

    conn.close()
    return out


def run_repair(
    db_path: Path,
    *,
    dry_run: bool = True,
    allow_noncanonical: bool = False,
) -> dict[str, Any]:
    db_path = db_path.resolve()
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    tz = float(conn.execute("SELECT MAX(bar_end_ts_utc) AS m FROM price_bars_1m").fetchone()["m"] or time.time())
    conn.close()

    planned = _collect_interior_missing(db_path, tz)
    rep: dict[str, Any] = {
        "schema": "repair_canonical_1m_interior_gaps_v1",
        "db_path": str(db_path),
        "dry_run": dry_run,
        "tz_now_utc": tz,
        "bars_to_insert": len(planned),
    }
    if dry_run:
        rep["sample"] = [{"ticker": a[0], "bar_start": a[1], "interp": a[4]} for a in planned[:15]]
        return rep

    db = EdDB(db_path, allow_noncanonical=allow_noncanonical)
    batch: dict[str, list[dict[str, Any]]] = {}
    for tkr, g, _lo, _hi, c_g in planned:
        batch.setdefault(tkr, []).append(
            {
                "ts": g,
                "open": c_g,
                "high": c_g,
                "low": c_g,
                "close": c_g,
                "volume": 0.0,
                "source": SYNTHETIC_INTERIOR_GRID_REPAIR_V1,
            }
        )

    n_written = 0
    for tkr, bars in batch.items():
        n_written += db.upsert_1m_bars(tkr, bars)
    rep["rows_upserted"] = n_written
    rep["tickers_touched"] = len(batch)

    # Refresh outcomes for touched tickers
    for tkr in batch:
        db.fill_outcomes(tkr, CANONICAL_TIMEFRAME, tz)
    rep["fill_outcomes_tickers"] = len(batch)

    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="Repair interior canonical 1m grid gaps")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--execute", action="store_true", help="Apply (default is dry-run)")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="repair_canonical_1m_interior_gaps_v1", write_capable=True)
    rep = run_repair(
        args.db,
        dry_run=not args.execute,
        allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)),
    )
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
