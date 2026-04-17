#!/usr/bin/env python3
"""
Phase 4A — Anchor coverage for snapshots that occur before the first stored price_bars_1m bar_end.

For each affected ticker, inserts exactly **one** canonical 1m bar with:
  bar_end_ts_utc = floor(min(ts_utc) / 60) * 60
  bar_start_ts_utc = bar_end_ts_utc - 60
  OHLC = first real bar's close (carry) for that ticker

This guarantees EXISTS(bar_end <= ts) for every snapshot at or after that minute for pre-history rows
(anchor = last completed bar <= ts; see db._apply_bar_based_outcome_updates bisect on bar_ends).

Does not replace real Schwab history; tags source for audit.

Usage:
  python -m calibration.repair_anchor_coverage_pad_v1 --db data/ed_console.db --execute
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from db import EdDB, configure_sqlite_connection
from horizon_outcomes import SYNTHETIC_ANCHOR_COVERAGE_PAD_V1
from timeframe_config import CANONICAL_TIMEFRAME


def _tickers_needing_pad(conn: sqlite3.Connection) -> list[tuple[str, float]]:
    """(ticker, min_ts_utc) for tickers with snapshots before first bar_end (no anchor)."""
    rows = conn.execute(
        """
        SELECT s.ticker AS tkr, MIN(s.ts_utc) AS mn
        FROM snapshots s
        JOIN (
            SELECT ticker, MIN(bar_end_ts_utc) AS mbe
            FROM price_bars_1m
            GROUP BY ticker
        ) x ON x.ticker = s.ticker
        WHERE s.timeframe = '1m'
          AND s.ts_utc < x.mbe
        GROUP BY s.ticker
        """
    ).fetchall()
    return [(r["tkr"], float(r["mn"])) for r in rows]


def run(db_path: Path, *, dry_run: bool, allow_noncanonical: bool) -> dict[str, Any]:
    db_path = db_path.resolve()
    conn = sqlite3.connect(str(db_path), timeout=120.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    tz = float(conn.execute("SELECT MAX(bar_end_ts_utc) AS m FROM price_bars_1m").fetchone()["m"] or time.time())

    need = _tickers_needing_pad(conn)
    rep: dict[str, Any] = {
        "schema": "repair_anchor_coverage_pad_v1",
        "db_path": str(db_path),
        "dry_run": dry_run,
        "tickers_needing_pad": len(need),
        "pairs": [],
    }

    planned: list[tuple[str, float, float, float]] = []
    for tkr, min_ts in need:
        r0 = conn.execute(
            """
            SELECT bar_start_ts_utc, close FROM price_bars_1m
            WHERE ticker = ? ORDER BY bar_start_ts_utc ASC LIMIT 1
            """,
            (tkr,),
        ).fetchone()
        if r0 is None:
            rep.setdefault("skipped_no_bars_at_all", []).append(tkr)
            continue
        c0 = float(r0["close"])
        bar_end = math.floor(float(min_ts) / 60.0) * 60.0
        bar_start = bar_end - 60.0
        if bar_start <= 0:
            rep.setdefault("skipped_bad_ts", []).append({"ticker": tkr, "min_ts": min_ts})
            continue
        planned.append((tkr, bar_start, bar_end, c0))
        rep["pairs"].append({"ticker": tkr, "min_ts": min_ts, "bar_start": bar_start, "bar_end": bar_end, "close": c0})

    conn.close()

    if dry_run:
        rep["would_insert"] = len(planned)
        return rep

    db = EdDB(db_path, allow_noncanonical=allow_noncanonical)
    n = 0
    for tkr, bar_start, bar_end, c0 in planned:
        n += db.upsert_1m_bars(
            tkr,
            [
                {
                    "ts": bar_start,
                    "open": c0,
                    "high": c0,
                    "low": c0,
                    "close": c0,
                    "volume": 0.0,
                    "source": SYNTHETIC_ANCHOR_COVERAGE_PAD_V1,
                }
            ],
        )

    rep["rows_upserted"] = n
    for tkr, _, _, _ in planned:
        db.fill_outcomes(tkr, CANONICAL_TIMEFRAME, tz)
    rep["fill_outcomes_tickers"] = len(planned)
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--execute", action="store_true")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="repair_anchor_coverage_pad_v1", write_capable=True)
    r = run(
        args.db,
        dry_run=not args.execute,
        allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)),
    )
    print(json.dumps(r, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
