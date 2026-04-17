#!/usr/bin/env python3
"""
Insert missing canonical 1m bars required for BAR_ANCHOR forward lookups when they fall
outside interior gaps (before first stored bar or after last stored bar for a ticker).

Uses **carry-forward / carry-back** of the nearest real bar's close (single row per required
grid point only — does not fabricate every intermediate minute).

Source tag: synthetic_edge_carry_v1 (distinct from interior interpolation repair).
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
from horizon_outcomes import SYNTHETIC_EDGE_CARRY_V1
from timeframe_config import CANONICAL_TIMEFRAME


def _planned_edge_carries(db_path: Path, tz_now: float) -> list[tuple[str, float, float]]:
    """Returns (ticker, bar_start_g, close_price) for each synthetic bar."""
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

    out: list[tuple[str, float, float]] = []
    for tkr, g in need:
        arr = starts_by.get(tkr)
        if not arr:
            continue
        if g in closes:
            continue
        i = bisect.bisect_left(arr, g)
        if i > 0 and i < len(arr) and arr[i - 1] < g < arr[i]:
            continue  # interior — should already be repaired
        if i == 0:
            c = closes[(tkr, arr[0])]
        else:
            c = closes[(tkr, arr[i - 1])]
        out.append((tkr, g, c))

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

    planned = _planned_edge_carries(db_path, tz)
    rep: dict[str, Any] = {
        "schema": "repair_canonical_1m_edge_carry_v1",
        "db_path": str(db_path),
        "dry_run": dry_run,
        "tz_now_utc": tz,
        "bars_to_insert": len(planned),
    }
    if dry_run:
        rep["sample"] = [{"ticker": a[0], "bar_start": a[1], "close": a[2]} for a in planned[:20]]
        return rep

    db = EdDB(db_path, allow_noncanonical=allow_noncanonical)
    batch: dict[str, list[dict[str, Any]]] = {}
    for tkr, g, c in planned:
        batch.setdefault(tkr, []).append(
            {
                "ts": g,
                "open": c,
                "high": c,
                "low": c,
                "close": c,
                "volume": 0.0,
                "source": SYNTHETIC_EDGE_CARRY_V1,
            }
        )

    n_written = 0
    for tkr, bars in batch.items():
        n_written += db.upsert_1m_bars(tkr, bars)
    rep["rows_upserted"] = n_written
    rep["tickers_touched"] = len(batch)
    for tkr in batch:
        db.fill_outcomes(tkr, CANONICAL_TIMEFRAME, tz)
    rep["fill_outcomes_tickers"] = len(batch)
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="Repair edge canonical 1m bars via close carry")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--execute", action="store_true")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="repair_canonical_1m_edge_carry_v1", write_capable=True)
    rep = run_repair(
        args.db,
        dry_run=not args.execute,
        allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)),
    )
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
