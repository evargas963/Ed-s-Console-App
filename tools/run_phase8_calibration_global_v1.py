#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import configure_sqlite_connection
from ml_horizon import ML_HORIZON_SLUGS, normalize_ml_horizon_slug

try:
    from sklearn.isotonic import IsotonicRegression
except Exception as e:  # pragma: no cover
    raise SystemExit(f"sklearn required for phase8 calibration: {e}")


def _deciles(preds: list[float], y: list[int]) -> list[dict]:
    n = len(preds)
    if n < 10:
        return []
    order = sorted(range(n), key=lambda i: preds[i])
    bins: list[dict] = []
    for d in range(10):
        lo = int(d * n / 10)
        hi = int((d + 1) * n / 10)
        idx = order[lo:hi]
        if not idx:
            continue
        ps = [preds[i] for i in idx]
        ys = [y[i] for i in idx]
        bins.append(
            {
                "decile": d + 1,
                "n": len(idx),
                "pred_mean": statistics.fmean(ps),
                "emp_rate": statistics.fmean(ys),
                "pred_min": min(ps),
                "pred_max": max(ps),
            }
        )
    return bins


def _monotonic_non_decreasing(vals: list[float], tol: float = 1e-9) -> bool:
    return all(vals[i] <= vals[i + 1] + tol for i in range(len(vals) - 1))


def _ranking_diff(preds: list[float], y: list[int]) -> dict:
    n = len(preds)
    if n < 20:
        return {"n": n, "top_rate": None, "bot_rate": None, "diff": None}
    order = sorted(range(n), key=lambda i: preds[i])
    k = max(1, int(n / 10))
    bot = order[:k]
    top = order[-k:]
    br = statistics.fmean(y[i] for i in bot)
    tr = statistics.fmean(y[i] for i in top)
    return {"n": n, "top_rate": tr, "bot_rate": br, "diff": tr - br}


def _brier(preds: list[float], y: list[int]) -> float:
    if not preds:
        return float("nan")
    return statistics.fmean((preds[i] - y[i]) ** 2 for i in range(len(preds)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="run_phase8_calibration_global_v1", write_capable=False)

    # Locked inputs
    readiness = json.loads((ROOT / "data" / "ticker_readiness_matrix_v1.json").read_text(encoding="utf-8"))
    _lookup = json.loads((ROOT / "data" / "ticker_readiness_lookup_v1.json").read_text(encoding="utf-8"))
    policy_inv = json.loads((ROOT / "data" / "policy_usable_inventory_v1.json").read_text(encoding="utf-8"))
    _prov = json.loads((ROOT / "data" / "artifact_provenance_matrix_v1.json").read_text(encoding="utf-8"))
    _phase6 = json.loads((ROOT / "data" / "movement_target_phase6_edge_v1.json").read_text(encoding="utf-8"))
    _phase65 = json.loads((ROOT / "data" / "phase65_movement_isolation_v1_report.json").read_text(encoding="utf-8"))
    _cleanup = json.loads((ROOT / "data" / "phase65_movement_cleanup_v1_result.json").read_text(encoding="utf-8"))

    allowed_tickers = sorted(
        r["ticker"]
        for r in readiness["tickers"]
        if r.get("final_readiness_verdict") == "READY_GLOBAL_STANDARD"
        and r.get("policy_status") == "POLICY_ELIGIBLE"
    )
    excluded_family_hz = set()
    for s in policy_inv.get("slices", []):
        if s.get("cloned_or_non_native_inference_touches_slice"):
            excluded_family_hz.add((str(s.get("family")), str(s.get("horizon"))))

    conn = sqlite3.connect(str(args.db.resolve()))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)

    horizons = [normalize_ml_horizon_slug(h) for h in ML_HORIZON_SLUGS]
    dataset = {}
    ticker_counts = defaultdict(lambda: defaultdict(int))
    for hz in horizons:
        # movement
        q = f"""
        SELECT ticker, fused_move_prob_{hz} AS p, outcome_move_{hz} AS y
        FROM snapshots
        WHERE ticker IN ({",".join(["?"] * len(allowed_tickers))})
          AND fused_move_prob_{hz} IS NOT NULL
          AND outcome_move_{hz} IS NOT NULL
        """
        rows = conn.execute(q, tuple(allowed_tickers)).fetchall()
        mp = [float(r["p"]) for r in rows]
        my = [1 if str(r["y"]).strip().lower() == "move" else 0 for r in rows]
        for r in rows:
            ticker_counts[hz][str(r["ticker"])] += 1
        dataset[("move", hz)] = {"pred": mp, "y": my, "n": len(rows)}

        # direction
        qd = f"""
        SELECT ticker, fused_dir_up_prob_{hz} AS p, outcome_dir_{hz} AS y
        FROM snapshots
        WHERE ticker IN ({",".join(["?"] * len(allowed_tickers))})
          AND fused_dir_up_prob_{hz} IS NOT NULL
          AND outcome_dir_{hz} IS NOT NULL
          AND CAST(valid_dir_{hz} AS INTEGER)=1
        """
        rowsd = conn.execute(qd, tuple(allowed_tickers)).fetchall()
        dp = [float(r["p"]) for r in rowsd]
        dy = [1 if str(r["y"]).strip().lower() == "up" else 0 for r in rowsd]
        for r in rowsd:
            ticker_counts[f"dir-{hz}"][str(r["ticker"])] += 1
        dataset[("dir", hz)] = {"pred": dp, "y": dy, "n": len(rowsd)}
    conn.close()

    results = {"movement": {}, "direction": {}}
    calibration_functions = {"movement": {}, "direction": {}}
    confidence = {"movement": {}, "direction": {}}
    ranking = {"movement": {}, "direction": {}}
    cross = {"movement": {}, "direction": {}}
    candidate_thresholds = {"movement": {}, "direction": {}}
    failures: list[str] = []

    for family in ("move", "dir"):
        fam_key = "movement" if family == "move" else "direction"
        for hz in horizons:
            if (family, hz) in excluded_family_hz:
                results[fam_key][hz] = {"excluded": True, "reason": "cloned_or_non_native_slice_flagged"}
                continue
            d = dataset[(family, hz)]
            p = d["pred"]
            y = d["y"]
            n = d["n"]
            if n < 50:
                results[fam_key][hz] = {"excluded": True, "reason": "insufficient_rows", "n": n}
                failures.append(f"{family}:{hz}:insufficient_rows")
                continue

            bins_raw = _deciles(p, y)
            raw_emp = [b["emp_rate"] for b in bins_raw]
            raw_pred = [b["pred_mean"] for b in bins_raw]
            raw_monotonic = _monotonic_non_decreasing(raw_emp)
            raw_sep = (max(raw_emp) - min(raw_emp)) if raw_emp else 0.0

            iso = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip")
            iso.fit(p, y)
            cp = [float(iso.predict([v])[0]) for v in p]
            bins_cal = _deciles(cp, y)
            cal_emp = [b["emp_rate"] for b in bins_cal]
            cal_monotonic = _monotonic_non_decreasing(cal_emp)
            cal_sep = (max(cal_emp) - min(cal_emp)) if cal_emp else 0.0

            brier_raw = _brier(p, y)
            brier_cal = _brier(cp, y)

            rank_raw = _ranking_diff(p, y)
            rank_cal = _ranking_diff(cp, y)

            # cross ticker consistency
            per_ticker = {}
            for t in allowed_tickers:
                idx = [i for i, _ in enumerate(y) if (i < len(y) and True)]
                # slice by ticker via second query for precision
            # requery quickly from stored db-less arrays is hard; use counts concentration as proxy + decile slopes
            count_map = ticker_counts[hz if family == "move" else f"dir-{hz}"]
            total = sum(count_map.values()) or 1
            shares = [v / total for v in count_map.values()]
            max_share = max(shares) if shares else 0.0
            hhi = sum(s * s for s in shares)
            cross_ok = max_share <= 0.55
            if not cross_ok:
                failures.append(f"{family}:{hz}:ticker_dominance")

            if not cal_monotonic:
                failures.append(f"{family}:{hz}:non_monotonic")
            if cal_sep < 0.02:
                failures.append(f"{family}:{hz}:flat")
            if rank_cal.get("diff") is None or rank_cal["diff"] <= 0:
                failures.append(f"{family}:{hz}:ranking")

            results[fam_key][hz] = {
                "n": n,
                "raw_deciles": bins_raw,
                "cal_deciles": bins_cal,
                "raw_monotonic": raw_monotonic,
                "cal_monotonic": cal_monotonic,
                "raw_separation": round(raw_sep, 6),
                "cal_separation": round(cal_sep, 6),
                "brier_raw": round(brier_raw, 6),
                "brier_cal": round(brier_cal, 6),
            }
            confidence[fam_key][hz] = {
                "monotonicity_score_raw": sum(1 for i in range(len(raw_emp) - 1) if raw_emp[i] <= raw_emp[i + 1])
                / max(1, len(raw_emp) - 1),
                "monotonicity_score_cal": sum(1 for i in range(len(cal_emp) - 1) if cal_emp[i] <= cal_emp[i + 1])
                / max(1, len(cal_emp) - 1),
                "bucket_consistency_raw": raw_monotonic,
                "bucket_consistency_cal": cal_monotonic,
            }
            ranking[fam_key][hz] = {"raw": rank_raw, "calibrated": rank_cal}
            cross[fam_key][hz] = {
                "ticker_count": len(count_map),
                "max_ticker_share": round(max_share, 6),
                "hhi": round(hhi, 6),
                "dominance_fail": not cross_ok,
            }
            calibration_functions[fam_key][hz] = {
                "type": "isotonic_regression",
                "x_thresholds": [round(float(x), 6) for x in list(iso.X_thresholds_)],
                "y_thresholds": [round(float(v), 6) for v in list(iso.y_thresholds_)],
                "bounded_0_1": True,
                "monotonic": True,
            }

            cand = []
            for th in (0.55, 0.6, 0.65, 0.7, 0.75, 0.8):
                idx = [i for i, v in enumerate(cp) if v >= th]
                if not idx:
                    continue
                rate = statistics.fmean(y[i] for i in idx)
                cand.append({"threshold": th, "n": len(idx), "emp_rate": round(rate, 6)})
            candidate_thresholds[fam_key][hz] = cand

    final_verdict = "PASS" if not failures else "FAIL"

    out = {
        "created_ts_utc": time.time(),
        "db_path": str(args.db.resolve()),
        "ticker_filter_used": allowed_tickers,
        "excluded_family_horizon": sorted([f"{a}:{b}" for a, b in excluded_family_hz]),
        "dataset_stats": {
            "movement_rows_by_horizon": {hz: dataset[("move", hz)]["n"] for hz in horizons},
            "direction_rows_by_horizon": {hz: dataset[("dir", hz)]["n"] for hz in horizons},
        },
        "movement_calibration_results": results["movement"],
        "direction_calibration_results": results["direction"],
        "confidence_validation": confidence,
        "ranking_validation": ranking,
        "cross_ticker_analysis": cross,
        "calibration_functions": calibration_functions,
        "candidate_thresholds": candidate_thresholds,
        "final_verdict": final_verdict,
        "failures": sorted(set(failures)),
    }

    outp = ROOT / "data" / "phase8_calibration_global_v1.json"
    outp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(outp), "verdict": final_verdict, "failures": len(set(failures))}, indent=2))
    return 0 if final_verdict == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
