"""Study #7: causal Kalman level/slope features → Elastic Net logistic."""

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
from sklearn.preprocessing import StandardScaler

from research.elastic_net_eval_v1.runner import apply_advancement_screen, evaluate_cell
from research.incumbent_eval_v1.runner import invalid_threshold_horizons
from research.tcn_eval_v1.runner import _et_date, _load_closes, _load_labeled_rows

PREREG_PATH = Path(__file__).resolve().parent / "prereg_v1.json"


def load_prereg() -> dict[str, Any]:
    return json.loads(PREREG_PATH.read_text(encoding="utf-8"))


def kalman_ll_trend(log_prices: np.ndarray, q: float, r: float) -> np.ndarray:
    """Causal local-linear-trend Kalman; returns (T,3) = level, slope, innovation."""
    n = len(log_prices)
    out = np.zeros((n, 3), dtype=np.float64)
    # state [level, slope]
    x = np.array([log_prices[0], 0.0], dtype=np.float64)
    P = np.eye(2) * 1.0
    F = np.array([[1.0, 1.0], [0.0, 1.0]])
    H = np.array([[1.0, 0.0]])
    Q = np.array([[q, 0.0], [0.0, q]])
    for t in range(n):
        # predict
        x = F @ x
        P = F @ P @ F.T + Q
        # update
        y = log_prices[t]
        innov = float(y - (H @ x)[0])
        S = float((H @ P @ H.T)[0, 0] + r)
        K = (P @ H.T) / S
        x = x + (K.flatten() * innov)
        P = (np.eye(2) - K @ H) @ P
        out[t, 0] = x[0]
        out[t, 1] = x[1]
        out[t, 2] = innov
    return out


def session_safe_kalman(ends: np.ndarray, log_prices: np.ndarray, q: float, r: float) -> np.ndarray:
    """RC-31 (reopened, operator v7 audit): the FILTER must not carry state across a session gap.

    kalman_ll_trend ran ONE continuous filter over the whole bar sequence, so even on
    RTH-filtered bars the Monday-open innovation measured Friday-close -> Monday-open — the
    whole weekend entering as feature column 2 — and the state update smeared the gap into level
    and slope. Session-filtering the BARS was not enough; the filter itself was session-blind
    (the same scope-vs-class failure as HAR's own np.diff).

    Cure: restart the filter at every ET-day boundary so no state crosses a gap. The restart bar
    itself is NaN'd — a re-initialized slope of 0.0 and innovation of 0.0 are fabricated calm,
    not estimates. Exclusion, never zeroing (RC-31 doctrine).
    """
    n = len(log_prices)
    out = np.full((n, 3), np.nan, dtype=np.float64)
    days = [_et_date(float(t)) for t in ends]
    i = 0
    while i < n:
        j = i
        while j < n and days[j] == days[i]:
            j += 1
        out[i:j] = kalman_ll_trend(log_prices[i:j], q, r)
        out[i] = np.nan  # day-restart bar: its state is not an estimate
        i = j
    return out


def _build_xy(ends, closes, labeled, q, r):
    import bisect

    logp = np.log(np.clip(closes, 1e-12, None))
    states = session_safe_kalman(ends, logp, q, r)
    xs, ys, dates = [], [], []
    for ts, y in labeled:
        j = bisect.bisect_right(ends, ts) - 1
        if j < 1:
            continue
        if not np.isfinite(states[j]).all():
            continue  # RC-31: day-restart bar — excluded, never median-imputed into a feature
        xs.append(states[j])
        ys.append(y)
        dates.append(_et_date(ts))
    if not xs:
        return np.zeros((0, 3)), [], []
    return np.asarray(xs, dtype=np.float64), ys, dates


def _fit_predict(Xtr, ytr, Xte, seed: int) -> list[str]:
    med = np.nanmedian(Xtr, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    for arr in (Xtr, Xte):
        bad = ~np.isfinite(arr)
        if bad.any():
            arr[bad] = np.take(med, np.where(bad)[1])
    sc = StandardScaler()
    Xtr = sc.fit_transform(Xtr)
    Xte = sc.transform(Xte)
    mdl = LogisticRegression(
        penalty="elasticnet", solver="saga", l1_ratio=0.5, C=1.0, max_iter=2000, random_state=seed
    )
    mdl.fit(Xtr, ytr)
    return [str(p) for p in mdl.predict(Xte)]


def run_study(db_path: Path | str) -> dict[str, Any]:
    from training_cache import expanding_window_oof_folds

    prereg = load_prereg()
    q = float(prereg["model"]["process_var"])
    r = float(prereg["model"]["obs_var"])
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
            X, ys, dates = _build_xy(ends, closes, labeled, q, r)
            day_list = sorted(set(dates))
            folds = expanding_window_oof_folds(day_list, n_folds=n_folds)
            if X.shape[0] == 0 or not folds:
                cells[f"{ticker}:{hz}"] = {
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
            for train_days, test_days in folds:
                tr = np.isin(date_arr, train_days)
                te = np.isin(date_arr, test_days)
                if tr.sum() < 50 or te.sum() < 1:
                    continue
                preds = _fit_predict(X[tr].copy(), y_arr[tr], X[te].copy(), seed)
                all_preds.extend(preds)
                all_truths.extend(y_arr[te].tolist())
                all_dates.extend(date_arr[te].tolist())
            cells[f"{ticker}:{hz}"] = evaluate_cell(all_preds, all_truths, all_dates, prereg)
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
    path = out / f"kalman_eval_{report['generated_utc'][:10]}_{report['run_id']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "latest.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "reports" / "kalman_eval",
    )
    args = ap.parse_args()
    db = args.db or Path(__import__("db").DB_PATH)
    report = run_study(db)
    path = write_report(report, args.out_dir)
    s = report["summary"]
    print(
        f"kalman_eval_v1 — {s['verdict']} "
        f"({s['n_pass']} PASS / {s['n_fail']} FAIL / {s['n_under_sampled']} under-sampled)"
    )
    for k, t in report["cells"].items():
        print(f"  {k}: n={t.get('n_scored')} mcc={t.get('mcc')} -> {t.get('verdict')}")
    print("report:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
