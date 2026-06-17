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
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.canonical_1m_grid_scan import scan_db
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from calibration.repair_canonical_1m_shared import apply_repair_1m_bar_batch_writes, carry_basis_source_sql
from db import configure_sqlite_connection
from horizon_outcomes import SYNTHETIC_INTERIOR_GRID_REPAIR_V1

log = logging.getLogger(__name__)

try:
    from timeframe_config import CANONICAL_TIMEFRAME
except ImportError as e:
    log.warning(
        "timeframe_config.CANONICAL_TIMEFRAME not available — using literal '1m': %s",
        e,
    )
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
    src_clause, src_params = carry_basis_source_sql()
    for r in conn.execute(
        f"SELECT ticker, bar_start_ts_utc, close FROM price_bars_1m WHERE {src_clause}",
        src_params,
    ):
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
    tz_row = conn.execute("SELECT MAX(bar_end_ts_utc) AS m FROM price_bars_1m").fetchone()["m"]
    conn.close()
    if tz_row is None:
        return {
            "schema": "repair_canonical_1m_interior_gaps_v1",
            "db_path": str(db_path),
            "dry_run": dry_run,
            "error": "no_bars_in_price_bars_1m",
            "bars_to_insert": 0,
        }
    tz = float(tz_row)

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

    try:
        n_written, n_tickers = apply_repair_1m_bar_batch_writes(
            db_path,
            batch,
            tz=tz,
            default_source=SYNTHETIC_INTERIOR_GRID_REPAIR_V1,
        )
    except Exception as e:
        rep["error"] = f"repair_failed_rollback:{e!r}"
        rep["rows_upserted"] = 0
        rep["tickers_touched"] = 0
        rep["governed_outcome_refresh_tickers"] = 0
        rep["fill_outcomes_tickers"] = 0
        return rep

    rep["rows_upserted"] = n_written
    rep["tickers_touched"] = n_tickers
    rep["governed_outcome_refresh_tickers"] = n_tickers
    rep["fill_outcomes_tickers"] = n_tickers
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
    return 1 if rep.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
