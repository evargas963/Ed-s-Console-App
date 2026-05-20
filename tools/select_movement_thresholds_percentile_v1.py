#!/usr/bin/env python3
"""
Per-horizon movement threshold search using empirical |outcome_*_pts| distribution (RTH, governed rows).

Evaluates candidate percentiles {50,60,70,80} of abs(pts). For each, reports coverage, balances,
majority baselines, and selects threshold_move_pts per rules (coverage >= 25%, prefer >= 30%,
up/down 40/60..60/40 when possible). Marks invalid_for_dir_target when no candidate viable.

Writes:
  - calibration/movement_target_thresholds_by_horizon_v1.json (selected thresholds)
  - data/movement_threshold_search_report_v1.json (full search table)

  python tools/select_movement_thresholds_percentile_v1.py --db data/ed_console.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import configure_sqlite_connection
from horizon_outcomes import OUTCOME_BAR_SPECS
from ml_data_common import head_rth_df_from_ts_utc, weekday_where_clause
from timeframe_config import CANONICAL_TIMEFRAME

DEFAULT_DB = ROOT / "data" / "ed_console.db"
OUT_CFG = ROOT / "calibration" / "movement_target_thresholds_by_horizon_v1.json"
OUT_REPORT = ROOT / "data" / "movement_threshold_search_report_v1.json"

PERCENTILES = (50, 60, 70, 80)
_RTH_FETCH_OVERSAMPLE = 4


def _pct_sorted(vals: list[float], p: int) -> float:
    if not vals:
        return 0.0
    xs = sorted(vals)
    k = max(0, min(len(xs) - 1, int(round((p / 100.0) * (len(xs) - 1)))))
    return float(xs[k])


def _eval_threshold(abs_pts: list[float], thr: float) -> dict:
    n = len(abs_pts)
    if n == 0:
        return {"n": 0}
    move = [x for x in abs_pts if x >= thr]
    nomove = [x for x in abs_pts if x < thr]
    # dir balance needs signed pts aligned — use paired list in caller
    cov = len(move) / n
    maj_move = max(len(move), len(nomove)) / n if n else 0.0
    return {
        "n": n,
        "retained_coverage": round(cov, 6),
        "move_vs_no_move": {"move": len(move), "no_move": len(nomove)},
        "majority_baseline_move_head": round(maj_move, 6),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--max-rows", type=int, default=800_000)
    ap.add_argument("--dry-run", action="store_true")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(
        args, tool_name="select_movement_thresholds_percentile_v1", write_capable=not args.dry_run
    )

    dbp = args.db.resolve()
    if not dbp.is_file():
        print(json.dumps({"error": "db_missing", "path": str(dbp)}))
        raise SystemExit(2)

    max_rows = int(args.max_rows)
    fetch_limit = max(max_rows * _RTH_FETCH_OVERSAMPLE, max_rows)

    conn = sqlite3.connect(str(dbp))
    configure_sqlite_connection(conn)

    report: dict = {"db": str(dbp), "horizons": {}}
    selected: dict = {"version": 2, "method": "percentile_abs_pts_rth", "horizons": {}}

    for odir, opt, _nmin in OUTCOME_BAR_SPECS:
        slug = odir.replace("outcome_", "")
        pts_col = opt
        sql = f"""
        SELECT ts_utc, {pts_col} AS pts FROM snapshots
        WHERE timeframe = ?
          AND {pts_col} IS NOT NULL
          AND ({weekday_where_clause()})
        ORDER BY ts_utc DESC
        LIMIT ?
        """
        df = pd.read_sql_query(sql, conn, params=(CANONICAL_TIMEFRAME, fetch_limit))
        df = head_rth_df_from_ts_utc(df, max_rows)
        signed = df["pts"].astype(float).tolist()
        abs_pts = [abs(x) for x in signed]
        n0 = len(abs_pts)
        horizon_entry: dict = {
            "n_eligible": n0,
            "candidates": [],
            "selected": None,
        }
        if n0 < 1000:
            horizon_entry["verdict"] = "INSUFFICIENT"
            selected["horizons"][slug] = {
                "threshold_move_pts": None,
                "invalid_for_dir_target": True,
                "reason": "insufficient_samples",
            }
            report["horizons"][slug] = horizon_entry
            continue

        best = None
        best_score = -1.0
        for p in PERCENTILES:
            thr = _pct_sorted(abs_pts, p)
            if thr <= 0:
                continue
            retained_idx = [i for i, a in enumerate(abs_pts) if a >= thr]
            cov = len(retained_idx) / n0
            if cov < 0.25:
                continue
            ups = sum(1 for i in retained_idx if signed[i] > 0)
            dns = sum(1 for i in retained_idx if signed[i] < 0)
            tdir = ups + dns
            bal = abs(ups - dns) / tdir if tdir else 1.0
            maj_dir = max(ups, dns) / tdir if tdir else 0.5
            ev = _eval_threshold(abs_pts, thr)
            cand = {
                "percentile": p,
                "threshold_move_pts": round(thr, 8),
                "retained_coverage": cov,
                "up_in_retained": ups,
                "down_in_retained": dns,
                "dir_imbalance": round(bal, 6),
                "conditional_majority_baseline_dir": round(maj_dir, 6),
                "move_head": ev,
            }
            horizon_entry["candidates"].append(cand)
            # Score: prefer coverage >= 0.30, balance, then separability proxy (1-bal)
            if cov < 0.25:
                continue
            score = 0.0
            if cov >= 0.30:
                score += 2.0
            else:
                score += cov
            score += (1.0 - bal) * 3.0
            if bal <= 0.2:
                score += 1.0
            if score > best_score and cov >= 0.25:
                best_score = score
                best = cand

        if best is None:
            horizon_entry["verdict"] = "INVALID_FOR_DIR_TARGET"
            selected["horizons"][slug] = {
                "threshold_move_pts": float(_pct_sorted(abs_pts, 60)),
                "invalid_for_dir_target": True,
                "selected_percentile": 60,
                "note": "No candidate met gates; move head uses p60, dir target disabled",
            }
        else:
            horizon_entry["verdict"] = "SELECTED"
            horizon_entry["selected"] = best
            invalid = bool(best["dir_imbalance"] > 0.35 and best["retained_coverage"] < 0.28)
            selected["horizons"][slug] = {
                "threshold_move_pts": best["threshold_move_pts"],
                "invalid_for_dir_target": invalid,
                "selected_percentile": best["percentile"],
                "coverage_at_selection": round(best["retained_coverage"], 6),
            }
        report["horizons"][slug] = horizon_entry

    conn.close()

    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(json.dumps(selected, indent=2))
    if not args.dry_run:
        OUT_CFG.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT_CFG, "w", encoding="utf-8") as f:
            json.dump(selected, f, indent=2)
        print(f"Wrote {OUT_CFG} and {OUT_REPORT}")


if __name__ == "__main__":
    main()
