"""Study #8: causal HAR-RV features → Elastic Net logistic (direction + non-flat)."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import matthews_corrcoef
from sklearn.preprocessing import StandardScaler

from research.elastic_net_eval_v1.runner import apply_advancement_screen, evaluate_cell
from research.incumbent_eval_v1.runner import invalid_threshold_horizons
from research.kalman_eval_v1.runner import _fit_predict
from research.tcn_eval_v1.runner import (_et_date, _load_closes, _load_labeled_rows,
                                         session_safe_log_returns)  # RC-31 primitive

PREREG_PATH = Path(__file__).resolve().parent / "prereg_v1.json"


def load_prereg() -> dict[str, Any]:
    return json.loads(PREREG_PATH.read_text(encoding="utf-8"))


def har_features(ends: np.ndarray, closes: np.ndarray) -> np.ndarray:
    """Per-bar HAR vector using only past completed SAME-SESSION returns (causal, RC-31).

    `ends` is REQUIRED, deliberately: this function cannot be session-safe without knowing when
    each bar ended, and an optional parameter would let a missed caller stay silently blind — a
    missed caller now fails loudly at the call site instead. Reproduced before this fix:
    har_features(...)[3,0] equalled log(MonOpen/FriClose)^2 exactly — the whole weekend entering
    as one bar-to-bar r^2, deterministically inflating every RV mean that touched a Monday.

    Gap returns are EXCLUDED via valid-count denominators (sum over finite r^2 / count of finite
    r^2), never zeroed: a zeroed gap fabricates calm and deflates the mean instead.
    """
    r = session_safe_log_returns(ends, closes)
    r2 = np.square(r)
    valid = np.isfinite(r2)
    v2 = np.where(valid, r2, 0.0)
    csum = np.cumsum(v2)
    ccnt = np.cumsum(valid.astype(np.float64))
    n = len(closes)
    out = np.zeros((n, 3), dtype=np.float64)
    for t in range(n):
        def mean_last(k: int) -> float:
            hi = t  # r2[0:t] end-exclusive: only completed prior returns (strict causality)
            if hi <= 0:
                return 0.0
            lo = max(0, hi - k)
            s = csum[hi - 1] - (csum[lo - 1] if lo > 0 else 0.0)
            c = ccnt[hi - 1] - (ccnt[lo - 1] if lo > 0 else 0.0)
            return float(s / c) if c > 0 else 0.0

        out[t, 0] = mean_last(1)
        out[t, 1] = mean_last(5)
        out[t, 2] = mean_last(15)
    return out


def _build_xy(ends, closes, labeled):
    import bisect

    feats = har_features(ends, closes)
    xs, ys, dates = [], [], []
    for ts, y in labeled:
        j = bisect.bisect_right(ends, ts) - 1
        if j < 15:
            continue
        xs.append(feats[j])
        ys.append(y)
        dates.append(_et_date(ts))
    if not xs:
        return np.zeros((0, 3)), [], []
    return np.asarray(xs, dtype=np.float64), ys, dates


def run_study(db_path: Path | str) -> dict[str, Any]:
    from training_cache import expanding_window_oof_folds

    prereg = load_prereg()
    seed = int(prereg["randomness"]["seed"])
    n_folds = int(prereg["walk_forward"]["n_folds"])
    invalid_hz = set(invalid_threshold_horizons())
    cells: dict[str, dict[str, Any]] = {}
    for ticker in prereg["family"]["tickers"]:
        ends, closes = _load_closes(Path(db_path), str(ticker))
        for hz in prereg["family"]["horizons"]:
            if hz in invalid_hz:
                continue
            labeled = _load_labeled_rows(Path(db_path), str(ticker), f"outcome_{hz}")
            X, ys, dates = _build_xy(ends, closes, labeled)
            day_list = sorted(set(dates))
            folds = expanding_window_oof_folds(day_list, n_folds=n_folds)
            key = f"{ticker}:{hz}"
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
            y_arr = np.asarray(ys)
            all_preds: list[str] = []
            all_truths: list[str] = []
            all_dates: list[str] = []
            all_nf_pred: list[int] = []
            all_nf_true: list[int] = []
            for train_days, test_days in folds:
                tr = np.isin(date_arr, train_days)
                te = np.isin(date_arr, test_days)
                if tr.sum() < 50 or te.sum() < 1:
                    continue
                preds = _fit_predict(X[tr].copy(), y_arr[tr], X[te].copy(), seed)
                all_preds.extend(preds)
                all_truths.extend(y_arr[te].tolist())
                all_dates.extend(date_arr[te].tolist())
                # secondary: non-flat
                ytr_nf = (y_arr[tr] != "flat").astype(int)
                yte_nf = (y_arr[te] != "flat").astype(int)
                if len(set(ytr_nf.tolist())) < 2:
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
                mdl.fit(Xtr, ytr_nf)
                all_nf_pred.extend(mdl.predict(Xte).tolist())
                all_nf_true.extend(yte_nf.tolist())
            cell = evaluate_cell(all_preds, all_truths, all_dates, prereg)
            if all_nf_true:
                cell["secondary_nonflat_mcc"] = float(
                    matthews_corrcoef(all_nf_true, all_nf_pred)
                )
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
    path = out / f"har_rv_eval_{report['generated_utc'][:10]}_{report['run_id']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "latest.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "reports" / "har_rv_eval",
    )
    args = ap.parse_args()
    db = args.db or Path(__import__("db").DB_PATH)
    report = run_study(db)
    path = write_report(report, args.out_dir)
    s = report["summary"]
    print(
        f"har_rv_eval_v1 — {s['verdict']} "
        f"({s['n_pass']} PASS / {s['n_fail']} FAIL / {s['n_under_sampled']} under-sampled)"
    )
    for k, t in report["cells"].items():
        print(
            f"  {k}: n={t.get('n_scored')} mcc={t.get('mcc')} "
            f"nonflat_mcc={t.get('secondary_nonflat_mcc')} -> {t.get('verdict')}"
        )
    print("report:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
