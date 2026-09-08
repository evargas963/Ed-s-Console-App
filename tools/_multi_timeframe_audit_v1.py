#!/usr/bin/env python3
"""Multi-timeframe data audit — stdout JSON evidence."""
from __future__ import annotations

import argparse
import bisect
import json
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from horizon_outcomes import forward_bar_start_utc  # noqa: E402
from math_exposure import classify_direction_pts  # noqa: E402
from movement_target_threshold import (  # noqa: E402
    load_movement_thresholds_by_horizon_v1,
    threshold_move_pts_for_slug,
)

DEFAULT_DB = ROOT / "data" / "ed_console.db"


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    return float(statistics.median(xs))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    db_path = args.db.resolve()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
    bar_tables = [t for t in tables if "bar" in t.lower() or "candle" in t.lower()]

    inv = conn.execute(
        """
        SELECT timeframe, COUNT(*) AS row_count
        FROM snapshots
        GROUP BY timeframe
        ORDER BY timeframe
        """
    ).fetchall()

    profiles: dict = {}
    struct: dict = {}
    coverage: dict = {}
    outcomes_non1m: dict = {}

    for row in inv:
        tf = row["timeframe"]
        n = int(row["row_count"])

        tickers = int(
            conn.execute("SELECT COUNT(DISTINCT ticker) AS n FROM snapshots WHERE timeframe = ?", (tf,)).fetchone()["n"]
        )
        tsr = conn.execute(
            "SELECT MIN(ts_utc) AS a, MAX(ts_utc) AS b FROM snapshots WHERE timeframe = ?", (tf,)
        ).fetchone()
        days = int(
            conn.execute(
                """
                SELECT COUNT(DISTINCT strftime('%Y-%m-%d', ts_utc, 'unixepoch')) AS n
                FROM snapshots WHERE timeframe = ?
                """,
                (tf,),
            ).fetchone()["n"]
        )

        per_ticker = [
            int(r["c"])
            for r in conn.execute(
                "SELECT COUNT(*) AS c FROM snapshots WHERE timeframe = ? GROUP BY ticker",
                (tf,),
            ).fetchall()
        ]
        rpc = {
            "min": min(per_ticker) if per_ticker else 0,
            "median": _median([float(x) for x in per_ticker]),
            "max": max(per_ticker) if per_ticker else 0,
        }

        dup_groups = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM (
                  SELECT ticker, timeframe, ts_utc, COUNT(*) AS c FROM snapshots
                  WHERE timeframe = ?
                  GROUP BY ticker, timeframe, ts_utc HAVING c > 1
                )
                """,
                (tf,),
            ).fetchone()[0]
        )

        # Consecutive ts deltas per (ticker) — order violations + large gap heuristic
        neg_deltas = 0
        gap_gt_1h = 0
        for trow in conn.execute(
            "SELECT DISTINCT ticker FROM snapshots WHERE timeframe = ?", (tf,)
        ).fetchall():
            tkr = trow["ticker"]
            ts_list = [
                float(r["ts_utc"])
                for r in conn.execute(
                    "SELECT ts_utc FROM snapshots WHERE timeframe = ? AND ticker = ? ORDER BY ts_utc",
                    (tf, tkr),
                ).fetchall()
            ]
            for i in range(1, len(ts_list)):
                d = ts_list[i] - ts_list[i - 1]
                if d < 0:
                    neg_deltas += 1
                if d > 3600:
                    gap_gt_1h += 1

        try:
            oc = conn.execute(
                "SELECT COUNT(*) AS n FROM snapshots WHERE timeframe = ? AND outcome_5c IS NOT NULL",
                (tf,),
            ).fetchone()["n"]
        except sqlite3.OperationalError:
            oc = None

        profiles[tf] = {
            "row_count": n,
            "distinct_tickers": tickers,
            "min_ts_utc": tsr["a"],
            "max_ts_utc": tsr["b"],
            "distinct_utc_days": days,
            "rows_per_ticker_min_median_max": rpc,
        }
        struct[tf] = {
            "duplicate_key_groups_ticker_tf_ts": dup_groups,
            "ordered_ts_violations_negative_delta_count": neg_deltas,
            "gaps_gt_1h_between_consecutive_snapshots": gap_gt_1h,
            "note": "snapshots are event-sampled; uniform spacing is not expected",
        }
        outcomes_non1m[tf] = int(oc) if oc is not None else None

        # Coverage: days with zero rows in range — coarse
        day_rows = [
            int(r["n"])
            for r in conn.execute(
                """
                SELECT COUNT(*) AS n FROM snapshots
                WHERE timeframe = ?
                GROUP BY strftime('%Y-%m-%d', ts_utc, 'unixepoch')
                """,
                (tf,),
            ).fetchall()
        ]
        coverage[tf] = {
            "days_observed_with_at_least_one_row": len(day_rows),
            "min_rows_any_day": min(day_rows) if day_rows else 0,
            "max_rows_any_day": max(day_rows) if day_rows else 0,
        }

    sch_by_tf: dict[str, list] = {}
    for r in inv:
        tf = r["timeframe"]
        sch_by_tf[tf] = [
            {"schema_version": x["v"], "n": int(x["n"])}
            for x in conn.execute(
                """
                SELECT COALESCE(horizon_outcome_schema_version, -1) AS v, COUNT(*) AS n
                FROM snapshots WHERE timeframe = ?
                GROUP BY horizon_outcome_schema_version
                """,
                (tf,),
            ).fetchall()
        ]

    # Step 6 evidence: recompute outcome_5c from price_bars_1m for legacy 5m rows (bar-anchor contract).
    outcome_5m_vs_1m: dict = {
        "5m_outcome_5c_cells_compared": 0,
        "mismatches_vs_bar_anchor_recompute": 0,
    }
    for tkr in conn.execute(
        "SELECT DISTINCT ticker FROM snapshots WHERE timeframe = '5m' AND outcome_5c IS NOT NULL"
    ):
        tkr = tkr[0]
        be = [
            float(x["bar_end_ts_utc"])
            for x in conn.execute(
                "SELECT bar_end_ts_utc FROM price_bars_1m WHERE ticker = ? ORDER BY bar_end_ts_utc ASC",
                (tkr,),
            )
        ]
        bec = [
            float(x["close"])
            for x in conn.execute(
                "SELECT bar_end_ts_utc, close FROM price_bars_1m WHERE ticker = ? ORDER BY bar_end_ts_utc ASC",
                (tkr,),
            )
        ]
        cbs = {
            float(x["bar_start_ts_utc"]): float(x["close"])
            for x in conn.execute(
                "SELECT bar_start_ts_utc, close FROM price_bars_1m WHERE ticker = ?", (tkr,)
            )
        }
        _mcfg = load_movement_thresholds_by_horizon_v1()
        for row in conn.execute(
            "SELECT ts_utc, atr, outcome_5c FROM snapshots WHERE ticker = ? AND timeframe = '5m' AND outcome_5c IS NOT NULL",
            (tkr,),
        ):
            ts = float(row["ts_utc"])
            ai = bisect.bisect_right(be, ts) - 1
            if ai < 0:
                continue
            ac = bec[ai]
            b5 = forward_bar_start_utc(ts, 5)
            fc = cbs.get(float(b5))
            if fc is None:
                continue
            try:
                _atr = float(row["atr"]) if row["atr"] is not None else None
            except (TypeError, ValueError):
                _atr = None
            # Mirror the production writer (db._apply_bar_based_outcome_updates): per-horizon
            # ATR-scaled threshold, not a fixed 0.05% cut, or this recompute reports false mismatches.
            _thr = threshold_move_pts_for_slug("5c", anchor_close=ac, atr=_atr, cfg=_mcfg)
            exp = classify_direction_pts(fc - ac, _thr)
            outcome_5m_vs_1m["5m_outcome_5c_cells_compared"] += 1
            if exp != row["outcome_5c"]:
                outcome_5m_vs_1m["mismatches_vs_bar_anchor_recompute"] += 1

    out = {
        "db_path": str(db_path),
        "sqlite_tables_with_bar_or_candle_in_name": [t for t in tables if "bar" in t.lower() or "candle" in t.lower()],
        "price_like_tables": bar_tables,
        "timeframe_inventory_sql": "SELECT timeframe, COUNT(*) FROM snapshots GROUP BY timeframe ORDER BY timeframe",
        "timeframe_inventory": [{"timeframe": r["timeframe"], "row_count": int(r["row_count"])} for r in inv],
        "per_timeframe_profiles": profiles,
        "structural_integrity": struct,
        "snapshots_with_non_null_outcome_5c_by_timeframe": outcomes_non1m,
        "coverage_by_timeframe": coverage,
        "horizon_outcome_schema_version_by_timeframe": sch_by_tf,
        "step5_stored_higher_tf_ohlc_vs_1m_reconstruction": {
            "status": "N_A",
            "reason": "SQLite has only price_bars_1m; there is no price_bars_5m or other OHLC table to compare reconstructed aggregates against.",
        },
        "step6_outcome_5c_5m_rows_recomputed_from_1m_bars": outcome_5m_vs_1m,
    }
    conn.close()
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
