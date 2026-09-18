#!/usr/bin/env python3
"""
Read-only evidence bundle for docs/issue19_bar_history_recovery_audit.md.

Usage (from repo root):
  python tools/bar_history_recovery_audit_v1.py --db data/ed_console.db
  python tools/bar_history_recovery_audit_v1.py --db data/ed_console.db --json-out data/bar_history_recovery_audit_last.json

Programmatic:
  from tools.bar_history_recovery_audit_v1 import collect_bar_recovery_audit, connect_bar_audit
"""
from __future__ import annotations

from db import get_snapshot_sql


import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
from timeframe_config import CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME


def connect_bar_audit(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path.resolve()), timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def collect_bar_recovery_audit(conn: sqlite3.Connection, db_path: Path) -> dict:
    """Build audit dict (caller owns connection lifecycle)."""
    out: dict = {
        "schema": "bar_history_recovery_audit_v1",
        "db_path": str(db_path.resolve()),
        "generated_ts_utc": time.time(),
    }

    out["price_bars_1m_global"] = dict(
        conn.execute(
            """
            SELECT
              COUNT(*) AS n_rows,
              COUNT(DISTINCT ticker) AS n_tickers,
              MIN(bar_start_ts_utc) AS min_bar_start_ts_utc,
              MAX(bar_end_ts_utc) AS max_bar_end_ts_utc
            FROM price_bars_1m
            """
        ).fetchone()
    )
    out["price_bars_1m_source_counts"] = [
        dict(r)
        for r in conn.execute(
            "SELECT source, COUNT(*) AS n FROM price_bars_1m GROUP BY source ORDER BY n DESC"
        ).fetchall()
    ]

    out["pin_neutral_scope"] = dict(
        conn.execute(
            get_snapshot_sql("tools/bar_history_recovery_audit_v1.py:63"),
            (
                CANONICAL_TIMEFRAME,
                DERIVED_TIMEFRAME,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            ),
        ).fetchone()
    )

    anchor_ok = int(
        conn.execute(
            get_snapshot_sql("tools/bar_history_recovery_audit_v1.py:82"),
            (
                CANONICAL_TIMEFRAME,
                DERIVED_TIMEFRAME,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            ),
        ).fetchone()["n"]
    )
    scope_n = int(out["pin_neutral_scope"]["n"])
    out["pin_neutral_anchor_feasible_count"] = anchor_ok
    out["pin_neutral_anchor_infeasible_count"] = scope_n - anchor_ok

    rows_tf = conn.execute(
        get_snapshot_sql("tools/bar_history_recovery_audit_v1.py:106"),
        (
            CANONICAL_TIMEFRAME,
            DERIVED_TIMEFRAME,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
        ),
    ).fetchall()
    out["pin_neutral_by_timeframe"] = {r["timeframe"]: int(r["n"]) for r in rows_tf}

    ts_bounds = conn.execute(
        get_snapshot_sql("tools/bar_history_recovery_audit_v1.py:124"),
        (
            CANONICAL_TIMEFRAME,
            DERIVED_TIMEFRAME,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
        ),
    ).fetchone()
    out["pin_neutral_ts_utc_bounds"] = dict(ts_bounds)

    per_ticker = conn.execute(
        get_snapshot_sql("tools/bar_history_recovery_audit_v1.py:144"),
        (
            CANONICAL_TIMEFRAME,
            DERIVED_TIMEFRAME,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
        ),
    ).fetchall()

    ticker_bar_bounds: list[dict] = []
    for r in per_ticker:
        tkr = r["ticker"]
        br = conn.execute(
            """
            SELECT
              COUNT(*) AS n_bars,
              MIN(bar_start_ts_utc) AS min_start,
              MAX(bar_end_ts_utc) AS max_end
            FROM price_bars_1m WHERE ticker = ?
            """,
            (tkr,),
        ).fetchone()
        gap = None
        if br["min_start"] is not None:
            gap = float(r["min_snap_ts"]) - float(br["min_start"])
        ticker_bar_bounds.append(
            {
                "ticker": tkr,
                "n_pin_neutral_snapshots": int(r["n_snapshots"]),
                "min_snap_ts_utc": r["min_snap_ts"],
                "max_snap_ts_utc": r["max_snap_ts"],
                "n_bars_1m_rows": int(br["n_bars"]),
                "bars_min_start_ts_utc": br["min_start"],
                "bars_max_end_ts_utc": br["max_end"],
                "min_snap_minus_min_bar_start_sec": gap,
            }
        )
    out["per_ticker_pin_neutral_vs_bars"] = ticker_bar_bounds

    candle_stats = conn.execute(
        get_snapshot_sql("tools/bar_history_recovery_audit_v1.py:197"),
        (
            CANONICAL_TIMEFRAME,
            DERIVED_TIMEFRAME,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
        ),
    ).fetchone()
    out["pin_neutral_snapshot_candle_columns"] = dict(candle_stats)

    out["spx_family_ticker_rows"] = [
        dict(r)
        for r in conn.execute(
            """
            SELECT ticker, COUNT(*) AS n FROM price_bars_1m
            WHERE ticker IN ('SPX', '$SPX', 'spx', '$spx')
            GROUP BY ticker
            """
        ).fetchall()
    ]

    tables_like = [
        r[0]
        for r in conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    ]
    out["sqlite_tables"] = tables_like
    out["tables_matching_bar_or_price"] = [
        n for n in tables_like if "bar" in n.lower() or n.startswith("price_")
    ]

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--json-out", type=Path, default=None)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="tools.bar_history_recovery_audit_v1", write_capable=False)

    conn = connect_bar_audit(args.db)
    try:
        out = collect_bar_recovery_audit(conn, args.db)
    finally:
        conn.close()

    txt = json.dumps(out, indent=2, default=str) + "\n"
    print(txt)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    main()
