"""Study #10: competing-risks target/stop/neither → multinomial logistic."""

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

from research.elastic_net_eval_v1.runner import apply_advancement_screen, evaluate_cell
from research.har_rv_eval_v1.runner import har_features
from research.incumbent_eval_v1.runner import invalid_threshold_horizons
from research.tcn_eval_v1.runner import _et_date, _load_closes, _load_labeled_rows

PREREG_PATH = Path(__file__).resolve().parent / "prereg_v1.json"
# Map survival classes onto stats.CLASSES vocabulary for the frozen MCC screen.
_SURV_TO_SCREEN = {"target": "up", "stop": "down", "neither": "flat"}
_HZ_MIN = {"1c": 2, "5c": 6, "15c": 16, "60c": 61}


def load_prereg() -> dict[str, Any]:
    return json.loads(PREREG_PATH.read_text(encoding="utf-8"))


def competing_label(
    ends: np.ndarray,
    closes: np.ndarray,
    j0: int,
    horizon_min: int,
    thr: float,
) -> str:
    c0 = closes[j0]
    # forward bars with bar_end > ends[j0], up to horizon_min minutes of bar starts
    t_limit = ends[j0] + horizon_min * 60.0
    for j in range(j0 + 1, len(closes)):
        if ends[j] > t_limit:
            break
        c = closes[j]
        if c >= c0 + thr:
            return "target"
        if c <= c0 - thr:
            return "stop"
    return "neither"


def _build(ends, closes, labeled_ts, horizon_min, thr_by_day_train=None):
    """Build features; labels use thr from train later — here return pts proxy for thr fit."""
    har = har_features(closes)
    logp = np.log(np.clip(closes, 1e-12, None))
    rets = np.diff(logp, prepend=logp[0])
    xs, js, dates = [], [], []
    for ts, _y in labeled_ts:
        j = bisect.bisect_right(ends, ts) - 1
        if j < 15 or j >= len(closes) - 1:
            continue
        xs.append(np.concatenate([har[j], rets[j - 4 : j + 1]]))
        js.append(j)
        dates.append(_et_date(ts))
    return (
        np.asarray(xs, dtype=np.float64) if xs else np.zeros((0, 8)),
        np.asarray(js, dtype=np.int64),
        dates,
    )


def run_study(db_path: Path | str) -> dict[str, Any]:
    from training_cache import expanding_window_oof_folds

    prereg = load_prereg()
    seed = int(prereg["randomness"]["seed"])
    n_folds = int(prereg["walk_forward"]["n_folds"])
    invalid_hz = set(invalid_threshold_horizons())
    cells: dict[str, dict[str, Any]] = {}
    for ticker in prereg["family"]["tickers"]:
        ends, closes = _load_closes(Path(db_path), str(ticker))
        # use snapshot times that have any outcome as decision clock
        labeled = _load_labeled_rows(Path(db_path), str(ticker), "outcome_1c")
        for hz in prereg["family"]["horizons"]:
            if hz in invalid_hz:
                continue
            hmin = int(_HZ_MIN[hz])
            X, js, dates = _build(ends, closes, labeled, hmin)
            key = f"{ticker}:{hz}"
            day_list = sorted(set(dates))
            folds = expanding_window_oof_folds(day_list, n_folds=n_folds)
            if X.shape[0] == 0 or not folds:
                cells[key] = {
                    "under_sampled": True,
                    "n_scored": 0,
                    "n_distinct_days": 0,
                    "warnings": ["NO_ROWS"],
                    "verdict": "UNDER_SAMPLED",
                    "mcc": None,
                    "accuracy": None,
                    "baselines": {},
                    "bootstrap": None,
                    "shuffle_control": None,
                }
                continue
            date_arr = np.asarray(dates)
            all_preds: list[str] = []
            all_truths: list[str] = []
            all_dates: list[str] = []
            for train_days, test_days in folds:
                tr = np.isin(date_arr, train_days)
                te = np.isin(date_arr, test_days)
                if tr.sum() < 50 or te.sum() < 1:
                    continue
                # thr from train path moves
                moves = []
                for j in js[tr]:
                    if j + 1 < len(closes):
                        moves.append(abs(closes[min(j + hmin, len(closes) - 1)] - closes[j]))
                thr = float(np.median(moves)) if moves else 0.0
                if thr <= 0:
                    thr = float(np.median(np.abs(np.diff(closes)))) if len(closes) > 1 else 0.01
                y_tr = [
                    _SURV_TO_SCREEN[competing_label(ends, closes, int(j), hmin, thr)]
                    for j in js[tr]
                ]
                y_te = [
                    _SURV_TO_SCREEN[competing_label(ends, closes, int(j), hmin, thr)]
                    for j in js[te]
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
                all_preds.extend(str(p) for p in mdl.predict(Xte))
                all_truths.extend(y_te)
                all_dates.extend(date_arr[te].tolist())
            cell = evaluate_cell(all_preds, all_truths, all_dates, prereg)
            cell["warnings"] = list(cell.get("warnings") or []) + [
                "SURVIVAL_MAPPED_TO_UP_DOWN_FLAT_FOR_MCC_SCREEN"
            ]
            cells[key] = cell
    apply_advancement_screen(cells)
    verdicts = [t["verdict"] for t in cells.values()]
    n_pass = verdicts.count("PASS")
    summary = (
        "STOP_SHUFFLE_CONTROL_FAILED"
        if "STOP_SHUFFLE_CONTROL_FAILED" in verdicts
        else "INSUFFICIENT_DATA"
        if all(v == "UNDER_SAMPLED" for v in verdicts)
        else "SIGNAL_DETECTED_IN_SOME_CELLS"
        if n_pass
        else "NO_SIGNAL_DETECTED"
    )
    return {
        "schema_version": "1",
        "prereg_id": prereg["prereg_id"],
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "run_id": uuid.uuid4().hex[:12],
        "db_path": str(Path(db_path).resolve()),
        "cells": cells,
        "summary": {
            "verdict": summary,
            "n_pass": n_pass,
            "n_fail": verdicts.count("FAIL"),
            "n_under_sampled": verdicts.count("UNDER_SAMPLED"),
            "n_cells": len(cells),
        },
    }


def write_report(report, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"survival_eval_{report['generated_utc'][:10]}_{report['run_id']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "latest.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "reports" / "survival_eval",
    )
    args = ap.parse_args()
    db = args.db or Path(__import__("db").DB_PATH)
    report = run_study(db)
    path = write_report(report, args.out_dir)
    s = report["summary"]
    print(
        f"survival_eval_v1 — {s['verdict']} "
        f"({s['n_pass']} PASS / {s['n_fail']} FAIL / {s['n_under_sampled']} under-sampled)"
    )
    for k, t in report["cells"].items():
        print(f"  {k}: n={t.get('n_scored')} mcc={t.get('mcc')} -> {t.get('verdict')}")
    print("report:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
