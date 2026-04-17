#!/usr/bin/env python3
"""
Grid-search movement threshold parameters against governed snapshots (RTH, outcomes present).

Writes calibration/movement_target_threshold_v1.json with atr_multiplier and
min_fraction_of_anchor chosen to target --target-move-rate (default 0.42) while
keeping directional balance among moved rows near 50/50 when possible.

  python tools/calibrate_movement_threshold_v1.py --db data/ed_console.db
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import configure_sqlite_connection
from ml_data_common import rth_where_clause, weekday_where_clause
from movement_target_threshold import movement_threshold_pts_v1
from timeframe_config import CANONICAL_TIMEFRAME

DEFAULT_DB = ROOT / "data" / "ed_console.db"
OUT_PATH = ROOT / "calibration" / "movement_target_threshold_v1.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--horizon-col", type=str, default="outcome_5c_pts")
    ap.add_argument("--target-move-rate", type=float, default=0.42)
    ap.add_argument("--max-rows", type=int, default=250_000)
    ap.add_argument("--dry-run", action="store_true")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="calibrate_movement_threshold_v1", write_capable=not args.dry_run)

    pts_col = str(args.horizon_col).strip()
    if not pts_col.replace("_", "").isalnum():
        raise SystemExit("invalid horizon col")

    conn = sqlite3.connect(str(args.db.resolve()))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    sql = f"""
    SELECT {pts_col} AS pts, atr, spot
    FROM snapshots
    WHERE timeframe = ?
      AND {pts_col} IS NOT NULL
      AND spot IS NOT NULL AND spot > 0
      AND {rth_where_clause()}
      AND ({weekday_where_clause()})
    ORDER BY ts_utc DESC
    LIMIT ?
    """
    rows = conn.execute(sql, (CANONICAL_TIMEFRAME, int(args.max_rows))).fetchall()
    conn.close()
    if len(rows) < 5000:
        print(f"WARN: only {len(rows)} rows; statistics noisy")

    pts_l = [float(r["pts"]) for r in rows]
    atr_l = [float(r["atr"]) if r["atr"] is not None else float("nan") for r in rows]
    spot_l = [float(r["spot"]) for r in rows]
    abs_m = [abs(p) for p in pts_l]

    best = None
    best_score = float("inf")
    tgt = float(args.target_move_rate)

    for k_atr in [x * 0.05 for x in range(2, 25)]:
        for frac in [x * 0.0001 for x in range(3, 40)]:
            params = {"atr_multiplier": k_atr, "min_fraction_of_anchor": frac}
            moves = 0
            up_w = down_w = 0
            for i in range(len(rows)):
                ac = spot_l[i]
                atr = atr_l[i] if not math.isnan(atr_l[i]) and atr_l[i] > 0 else None
                thr = movement_threshold_pts_v1(ac, atr, params)
                if abs_m[i] >= thr:
                    moves += 1
                    if pts_l[i] > 0:
                        up_w += 1
                    elif pts_l[i] < 0:
                        down_w += 1
            rate = moves / max(len(rows), 1)
            bal = abs(up_w - down_w) / max(up_w + down_w, 1)
            # Prefer move rate near target; secondary minimize imbalance
            score = (rate - tgt) ** 2 * 10 + bal * 0.5
            if moves < max(500, len(rows) * 0.05):
                continue
            if score < best_score:
                best_score = score
                best = (params, rate, moves, up_w, down_w, bal)

    if best is None:
        raise SystemExit("no grid point satisfied minimum move count; relax constraints or add data")

    params, rate, moves, up_w, down_w, bal = best
    out = {
        "version": 1,
        "atr_multiplier": round(params["atr_multiplier"], 4),
        "min_fraction_of_anchor": round(params["min_fraction_of_anchor"], 6),
        "method": "max_atr_pts_and_anchor_fraction",
        "calibration": {
            "rows_used": len(rows),
            "pts_column": pts_col,
            "target_move_rate": tgt,
            "achieved_move_rate": round(rate, 4),
            "moves": moves,
            "up_among_moves": up_w,
            "down_among_moves": down_w,
            "balance_penalty": round(bal, 4),
        },
    }
    print(json.dumps(out, indent=2))
    if not args.dry_run:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
