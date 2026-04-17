"""Compare stored BAR_ANCHOR_V1 outcomes to recomputation from current price_bars_1m (all governed horizons)."""
from __future__ import annotations

import argparse
import bisect
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from horizon_outcomes import OUTCOME_BAR_SPECS, forward_bar_start_utc  # noqa: E402
from math_exposure import classify_direction  # noqa: E402

DEFAULT_DB = ROOT / "data" / "ed_console.db"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    db_path = args.db.resolve()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    outcome_cols = [s[0] for s in OUTCOME_BAR_SPECS]
    mism_by_h: dict[str, int] = {c: 0 for c in outcome_cols}
    mism_by_ticker: dict[str, int] = defaultdict(int)
    total_with_any = 0
    rows_checked = 0

    for trow in conn.execute(
        """
        SELECT DISTINCT ticker FROM snapshots
        WHERE timeframe = '1m'
          AND COALESCE(horizon_outcome_schema_version, 3) = 3
        """
    ):
        tkr = trow["ticker"]
        bar_end_rows = conn.execute(
            "SELECT bar_end_ts_utc, close FROM price_bars_1m WHERE ticker = ? ORDER BY bar_end_ts_utc ASC",
            (tkr,),
        ).fetchall()
        bar_ends = [float(r["bar_end_ts_utc"]) for r in bar_end_rows]
        bar_end_closes = [float(r["close"]) for r in bar_end_rows]
        close_by_start = {
            float(r["bar_start_ts_utc"]): float(r["close"])
            for r in conn.execute(
                "SELECT bar_start_ts_utc, close FROM price_bars_1m WHERE ticker = ?",
                (tkr,),
            ).fetchall()
        }
        for row in conn.execute(
            """
            SELECT snapshot_id, ts_utc, outcome_1c, outcome_3c, outcome_5c, outcome_8c,
                   outcome_13c, outcome_15c, outcome_60c
            FROM snapshots
            WHERE ticker = ? AND timeframe = '1m'
              AND COALESCE(horizon_outcome_schema_version, 3) = 3
            """,
            (tkr,),
        ):
            rows_checked += 1
            t_snap = float(row["ts_utc"])
            ai = bisect.bisect_right(bar_ends, t_snap) - 1
            if ai < 0:
                continue
            ac = bar_end_closes[ai]
            has_stored = any(row[c] is not None for c in outcome_cols)
            if has_stored:
                total_with_any += 1
            for odir, _opt, n_min in OUTCOME_BAR_SPECS:
                if row[odir] is None:
                    continue
                b_start = forward_bar_start_utc(t_snap, n_min)
                fc = close_by_start.get(float(b_start))
                if fc is None:
                    mism_by_h[odir] += 1
                    mism_by_ticker[tkr] += 1
                    continue
                exp = classify_direction(fc - ac, ac)
                if exp != row[odir]:
                    mism_by_h[odir] += 1
                    mism_by_ticker[tkr] += 1

    conn.close()

    total_mism = sum(mism_by_h.values())
    out = {
        "db_path": str(db_path),
        "snapshot_rows_scanned_bar_anchor_v1": rows_checked,
        "rows_with_any_stored_outcome": total_with_any,
        "mismatch_cells_total": total_mism,
        "mismatch_by_horizon_column": mism_by_h,
        "mismatch_ticker_count": len([k for k, v in mism_by_ticker.items() if v > 0]),
        "top_tickers_by_mismatch": sorted(
            [{"ticker": k, "mismatch_cells": v} for k, v in mism_by_ticker.items() if v > 0],
            key=lambda x: -x["mismatch_cells"],
        )[:25],
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
