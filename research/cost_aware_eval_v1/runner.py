"""Study #11: cost-aware economic kill on best faint leads (QQQ HAR-RV; QQQ survival 60c)."""

from __future__ import annotations

import argparse
import bisect
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from research.har_rv_eval_v1.runner import _build_xy, har_features
from research.kalman_eval_v1.runner import _fit_predict
from research.survival_eval_v1.runner import _HZ_MIN, _SURV_TO_SCREEN, competing_label
from research.tcn_eval_v1.runner import session_safe_log_returns  # RC-31
from research.tcn_eval_v1.runner import _et_date, _load_closes, _load_labeled_rows

PREREG_PATH = Path(__file__).resolve().parent / "prereg_v1.json"
_HZ_BARS = {"1c": 1, "5c": 5, "15c": 15, "60c": 60}


def load_prereg() -> dict[str, Any]:
    return json.loads(PREREG_PATH.read_text(encoding="utf-8"))


def _forward_ret_bp(closes: np.ndarray, j: int, hz: str) -> float:
    k = int(_HZ_BARS[hz])
    j1 = min(j + k, len(closes) - 1)
    c0 = float(closes[j])
    if c0 <= 0:
        return 0.0
    return 10000.0 * (float(closes[j1]) - c0) / c0


def _day_bootstrap_ci(day_nets: dict[str, list[float]], B: int, seed: int) -> list[float]:
    days = sorted(day_nets)
    if not days:
        return [0.0, 0.0]
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(B):
        sample = rng.choice(days, size=len(days), replace=True)
        vals = [v for d in sample for v in day_nets[d]]
        means.append(float(np.mean(vals)) if vals else 0.0)
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def _score_nets(nets: list[float], dates: list[str], cost_bp: float, B: int, seed: int) -> dict[str, Any]:
    arr = np.asarray(nets, dtype=np.float64)
    day_nets: dict[str, list[float]] = {}
    for d, v in zip(dates, nets):
        day_nets.setdefault(d, []).append(float(v))
    mean_net = float(arr.mean()) if len(arr) else 0.0
    ci = _day_bootstrap_ci(day_nets, B, seed)
    kill = mean_net <= 0.0 or (ci[0] <= 0.0 <= ci[1])
    return {
        "n_scored": len(nets),
        "mean_net_bp": mean_net,
        "median_net_bp": float(np.median(arr)) if len(arr) else 0.0,
        "sum_net_bp": float(arr.sum()) if len(arr) else 0.0,
        "bootstrap_ci95_mean_net_bp": ci,
        "always_abstain_mean_bp": 0.0,
        "cost_round_trip_bp": cost_bp,
        "verdict": "KILL" if kill else "SURVIVE_ECONOMIC",
        "kill_reasons": [
            r
            for r, ok in [
                ("mean_net_bp_le_0", mean_net <= 0.0),
                ("bootstrap_ci_includes_0", ci[0] <= 0.0 <= ci[1]),
            ]
            if ok
        ],
    }


def _run_har_qqq(db: Path, prereg: dict[str, Any]) -> dict[str, Any]:
    from training_cache import expanding_window_oof_folds

    seed = int(prereg["randomness"]["seed"])
    B = int(prereg["randomness"]["bootstrap_B"])
    cost = float(prereg["cost_model"]["round_trip_bp"])
    n_folds = int(prereg["walk_forward"]["n_folds"])
    ends, closes = _load_closes(db, "QQQ")
    cells: dict[str, Any] = {}
    for hz in ["1c", "5c", "15c", "60c"]:
        labeled = _load_labeled_rows(db, "QQQ", f"outcome_{hz}")
        X, ys, dates = _build_xy(ends, closes, labeled)
        # need bar indices for returns
        js = []
        for ts, _y in labeled:
            j = bisect.bisect_right(ends, ts) - 1
            if j < 15:
                continue
            js.append(j)
        js_arr = np.asarray(js, dtype=np.int64)
        date_arr = np.asarray(dates)
        y_arr = np.asarray(ys)
        day_list = sorted(set(dates))
        folds = expanding_window_oof_folds(day_list, n_folds=n_folds)
        nets: list[float] = []
        out_dates: list[str] = []
        n_trades = 0
        for train_days, test_days in folds:
            tr = np.isin(date_arr, train_days)
            te = np.isin(date_arr, test_days)
            if tr.sum() < 50 or te.sum() < 1:
                continue
            preds = _fit_predict(X[tr].copy(), y_arr[tr], X[te].copy(), seed)
            for pred, j, d in zip(preds, js_arr[te], date_arr[te]):
                if pred == "up":
                    sign = 1.0
                elif pred == "down":
                    sign = -1.0
                else:
                    nets.append(0.0)
                    out_dates.append(str(d))
                    continue
                raw = _forward_ret_bp(closes, int(j), hz)
                nets.append(sign * raw - cost)
                out_dates.append(str(d))
                n_trades += 1
        cell = _score_nets(nets, out_dates, cost, B, seed)
        cell["n_trades"] = n_trades
        cell["trade_rate"] = (n_trades / len(nets)) if nets else 0.0
        cells[f"QQQ:{hz}"] = cell
    return cells


def _run_survival_qqq_60c(db: Path, prereg: dict[str, Any]) -> dict[str, Any]:
    from training_cache import expanding_window_oof_folds

    seed = int(prereg["randomness"]["seed"])
    B = int(prereg["randomness"]["bootstrap_B"])
    cost = float(prereg["cost_model"]["round_trip_bp"])
    n_folds = int(prereg["walk_forward"]["n_folds"])
    hz = "60c"
    hmin = int(_HZ_MIN[hz])
    ends, closes = _load_closes(db, "QQQ")
    labeled = _load_labeled_rows(db, "QQQ", "outcome_1c")
    har = har_features(ends, closes)
    rets = session_safe_log_returns(ends, closes)   # RC-31: gap returns are NaN
    xs, js, dates = [], [], []
    for ts, _y in labeled:
        j = bisect.bisect_right(ends, ts) - 1
        if j < 15 or j >= len(closes) - 1:
            continue
        xs.append(np.concatenate([har[j], rets[j - 4 : j + 1]]))
        js.append(j)
        dates.append(_et_date(ts))
    X = np.asarray(xs, dtype=np.float64) if xs else np.zeros((0, 8))
    js_arr = np.asarray(js, dtype=np.int64)
    date_arr = np.asarray(dates)
    folds = expanding_window_oof_folds(sorted(set(dates)), n_folds=n_folds)
    nets: list[float] = []
    out_dates: list[str] = []
    n_trades = 0
    for train_days, test_days in folds:
        tr = np.isin(date_arr, train_days)
        te = np.isin(date_arr, test_days)
        if tr.sum() < 50 or te.sum() < 1:
            continue
        moves = []
        for j in js_arr[tr]:
            moves.append(abs(closes[min(int(j) + hmin, len(closes) - 1)] - closes[int(j)]))
        thr = float(np.median(moves)) if moves else 0.0
        if thr <= 0:
            thr = float(np.median(np.abs(np.diff(closes)))) if len(closes) > 1 else 0.01
        y_tr = [
            _SURV_TO_SCREEN[competing_label(ends, closes, int(j), hmin, thr)]
            for j in js_arr[tr]
        ]
        if len(set(y_tr)) < 2:
            continue
        sc = StandardScaler()
        Xtr = sc.fit_transform(X[tr])
        Xte = sc.transform(X[te])
        mdl = LogisticRegression(
            penalty="elasticnet",
            solver="saga",
            l1_ratio=0.5,
            C=1.0,
            max_iter=2000,
            random_state=seed,
        )
        mdl.fit(Xtr, y_tr)
        preds = [str(p) for p in mdl.predict(Xte)]
        for pred, j, d in zip(preds, js_arr[te], date_arr[te]):
            # survival map: up=target long, down=stop short, flat=abstain
            if pred == "up":
                sign = 1.0
            elif pred == "down":
                sign = -1.0
            else:
                nets.append(0.0)
                out_dates.append(str(d))
                continue
            raw = _forward_ret_bp(closes, int(j), hz)
            nets.append(sign * raw - cost)
            out_dates.append(str(d))
            n_trades += 1
    cell = _score_nets(nets, out_dates, cost, B, seed)
    cell["n_trades"] = n_trades
    cell["trade_rate"] = (n_trades / len(nets)) if nets else 0.0
    cell["warnings"] = ["SURVIVAL_TARGET_STOP_MAPPED_TO_LONG_SHORT"]
    return {f"QQQ:{hz}": cell}


def run_study(db_path: Path | str) -> dict[str, Any]:
    prereg = load_prereg()
    db = Path(db_path)
    har_cells = _run_har_qqq(db, prereg)
    surv_cells = _run_survival_qqq_60c(db, prereg)
    all_cells = {f"har_rv:{k}": v for k, v in har_cells.items()}
    all_cells.update({f"survival:{k}": v for k, v in surv_cells.items()})
    verdicts = [c["verdict"] for c in all_cells.values()]
    n_survive = verdicts.count("SURVIVE_ECONOMIC")
    return {
        "schema_version": "1",
        "prereg_id": prereg["prereg_id"],
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "run_id": uuid.uuid4().hex[:12],
        "db_path": str(db.resolve()),
        "cost_model_id": prereg["cost_model"]["id"],
        "cells": all_cells,
        "summary": {
            "verdict": "ECONOMIC_KILL" if n_survive == 0 else "ECONOMIC_SURVIVOR",
            "n_survive": n_survive,
            "n_kill": verdicts.count("KILL"),
            "n_cells": len(all_cells),
            "note": "No signal-existence PASS cells existed; this is a hard economic kill on residual faint leads.",
        },
    }


def write_report(report, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"cost_aware_eval_{report['generated_utc'][:10]}_{report['run_id']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "latest.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "reports" / "cost_aware_eval",
    )
    args = ap.parse_args()
    db = args.db or Path(__import__("db").DB_PATH)
    report = run_study(db)
    path = write_report(report, args.out_dir)
    s = report["summary"]
    print(f"cost_aware_eval_v1 — {s['verdict']} ({s['n_survive']} survive / {s['n_kill']} kill)")
    for k, t in report["cells"].items():
        print(
            f"  {k}: mean_net_bp={t.get('mean_net_bp'):.4f} "
            f"ci={t.get('bootstrap_ci95_mean_net_bp')} trades={t.get('n_trades')} -> {t.get('verdict')}"
        )
    print("report:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
