#!/usr/bin/env python3
"""
Validate persisted movement/direction predictions on governed 1m snapshots.

  python tools/validate_movement_prediction_coverage_v1.py --db data/ed_console.db
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import configure_sqlite_connection
from ml_horizon import ML_HORIZON_SLUGS, normalize_ml_horizon_slug

TOL = 0.002

GOV_WHERE = """
timeframe = '1m'
AND COALESCE(horizon_outcome_schema_version, 3) = 3
AND outcome_1c IS NOT NULL AND outcome_1c_pts IS NOT NULL
AND outcome_3c IS NOT NULL AND outcome_3c_pts IS NOT NULL
AND outcome_5c IS NOT NULL AND outcome_5c_pts IS NOT NULL
AND outcome_8c IS NOT NULL AND outcome_8c_pts IS NOT NULL
AND outcome_13c IS NOT NULL AND outcome_13c_pts IS NOT NULL
AND outcome_15c IS NOT NULL AND outcome_15c_pts IS NOT NULL
AND outcome_60c IS NOT NULL AND outcome_60c_pts IS NOT NULL
AND EXISTS (
  SELECT 1 FROM price_bars_1m p
  WHERE p.ticker = snapshots.ticker AND p.bar_end_ts_utc <= snapshots.ts_utc
)
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    ap.add_argument("--sample-sum-check", type=int, default=8000)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="validate_movement_prediction_coverage_v1", write_capable=False)

    dbp = args.db.resolve()
    if not dbp.is_file():
        print(json.dumps({"error": "missing db"}))
        return 2

    conn = sqlite3.connect(str(dbp))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)

    total = int(conn.execute(f"SELECT COUNT(*) FROM snapshots WHERE {GOV_WHERE}").fetchone()[0])
    horizons = [normalize_ml_horizon_slug(h) for h in ML_HORIZON_SLUGS]

    per_h: dict = {}
    verdict = "PASS"
    reasons: list[str] = []

    for hz in horizons:
        pm = f"fused_move_prob_{hz}"
        pu = f"fused_dir_up_prob_{hz}"
        n_m = int(
            conn.execute(
                f"SELECT COUNT(*) FROM snapshots WHERE {GOV_WHERE} AND {pm} IS NOT NULL"
            ).fetchone()[0]
        )
        n_d = int(
            conn.execute(
                f"SELECT COUNT(*) FROM snapshots WHERE {GOV_WHERE} AND {pu} IS NOT NULL"
            ).fetchone()[0]
        )
        cov_m = n_m / total if total else 0.0
        cov_d = n_d / total if total else 0.0
        st = {
            "total_governed": total,
            "non_null_move": n_m,
            "non_null_dir_up": n_d,
            "coverage_move": round(cov_m, 6),
            "coverage_dir": round(cov_d, 6),
        }
        if cov_m < 0.95:
            st["verdict_move"] = "FAIL"
            verdict = "FAIL"
            reasons.append(f"{hz} coverage_move {cov_m:.4f} < 0.95")
        else:
            st["verdict_move"] = "PASS"
            if cov_m < 0.99:
                st["verdict_move"] = "WARN"
                reasons.append(f"{hz} coverage_move {cov_m:.4f} < 0.99 (target)")
        if cov_d < 0.95:
            st["verdict_dir"] = "FAIL"
            verdict = "FAIL"
            reasons.append(f"{hz} coverage_dir {cov_d:.4f} < 0.95")
        else:
            st["verdict_dir"] = "PASS"
            if cov_d < 0.99:
                st["verdict_dir"] = "WARN"
                reasons.append(f"{hz} coverage_dir {cov_d:.4f} < 0.99 (target)")
        per_h[hz] = st

    lim = max(1, int(args.sample_sum_check))
    rows = conn.execute(
        f"""
        SELECT * FROM snapshots
        WHERE {GOV_WHERE}
          AND fused_move_prob_5c IS NOT NULL
        LIMIT ?
        """,
        (lim,),
    ).fetchall()

    bad_sum = 0
    bad_nan = 0
    neg = 0
    move_samples: list[float] = []
    dir_samples: list[float] = []
    for r in rows:
        d = dict(r)
        for hz in horizons:
            pm = d.get(f"fused_move_prob_{hz}")
            pu = d.get(f"fused_dir_up_prob_{hz}")
            fc = d.get(f"fused_confidence_{hz}")
            for v in (pm, pu, fc):
                if v is None:
                    continue
                fv = float(v)
                if not math.isfinite(fv):
                    bad_nan += 1
                if fv < -1e-9 or fv > 1.0 + 1e-9:
                    neg += 1
            if pm is not None and hz == "5c":
                move_samples.append(float(pm))
            if pu is not None and hz == "5c":
                dir_samples.append(float(pu))

    def _dist(xs: list[float]) -> dict:
        if len(xs) < 2:
            return {"n": len(xs), "std": None, "min": None, "max": None}
        return {
            "n": len(xs),
            "mean": round(statistics.fmean(xs), 6),
            "std": round(statistics.pstdev(xs), 6) if len(xs) > 1 else 0.0,
            "min": round(min(xs), 6),
            "max": round(max(xs), 6),
        }

    degenerate_move = len(move_samples) >= 10 and _dist(move_samples).get("std") == 0.0
    degenerate_dir = len(dir_samples) >= 10 and _dist(dir_samples).get("std") == 0.0

    integrity = {
        "sample_rows_checked": len(rows),
        "bad_sum_pairs": bad_sum,
        "note": "Fusion policy columns have no XGB move/no_move pair; bad_sum_pairs reserved",
        "bad_nonfinite": bad_nan,
        "negative_values": neg,
        "fused_move_prob_5c_distribution": _dist(move_samples),
        "fused_dir_up_prob_5c_distribution": _dist(dir_samples),
        "degenerate_constant_move": degenerate_move,
        "degenerate_constant_dir": degenerate_dir,
    }
    if degenerate_move or degenerate_dir:
        verdict = "FAIL"
        reasons.append("degenerate probability distribution on sample")

    out = {
        "governed_total": total,
        "per_horizon": per_h,
        "integrity_sample": integrity,
        "overall_verdict": verdict,
        "reasons": reasons,
    }
    conn.close()
    outp = ROOT / "data" / "validate_movement_prediction_coverage_v1.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0 if verdict == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
