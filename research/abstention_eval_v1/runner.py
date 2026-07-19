"""Study #20: HAR logistic with train-chosen probability abstention threshold."""

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
from research.har_rv_eval_v1.runner import _build_xy
from research.incumbent_eval_v1.runner import invalid_threshold_horizons
from research.tcn_eval_v1.runner import _load_closes, _load_labeled_rows

PREREG_PATH = Path(__file__).resolve().parent / "prereg_v1.json"
TAUS = (0.40, 0.45, 0.50, 0.55, 0.60)


def load_prereg() -> dict[str, Any]:
    return json.loads(PREREG_PATH.read_text(encoding="utf-8"))


def _pick_tau(proba, y, classes, seed) -> float:
    best_tau, best_mcc = 0.5, -2.0
    for tau in TAUS:
        mask = proba.max(axis=1) >= tau
        if mask.mean() < 0.20 or mask.sum() < 30:
            continue
        pred = classes[proba[mask].argmax(axis=1)]
        m = float(matthews_corrcoef(y[mask], pred))
        if m > best_mcc:
            best_mcc, best_tau = m, float(tau)
    return best_tau


def run_study(db_path: Path | str) -> dict[str, Any]:
    from training_cache import expanding_window_oof_folds

    prereg = load_prereg()
    seed = int(prereg["randomness"]["seed"])
    n_folds = int(prereg["walk_forward"]["n_folds"])
    min_cov = float(prereg["sample_floors"]["min_oos_coverage"])
    invalid_hz = set(invalid_threshold_horizons())
    cells: dict[str, dict[str, Any]] = {}
    for ticker in prereg["family"]["tickers"]:
        ends, closes = _load_closes(Path(db_path), str(ticker))
        for hz in prereg["family"]["horizons"]:
            if hz in invalid_hz:
                continue
            key = f"{ticker}:{hz}"
            labeled = _load_labeled_rows(Path(db_path), str(ticker), f"outcome_{hz}")
            X, ys, dates = _build_xy(ends, closes, labeled)
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
            y_arr = np.asarray(ys)
            all_preds: list[str] = []
            all_truths: list[str] = []
            all_dates: list[str] = []
            n_te = 0
            n_traded = 0
            taus_used = []
            for train_days, test_days in folds:
                tr = np.isin(date_arr, train_days)
                te = np.isin(date_arr, test_days)
                if tr.sum() < 50 or te.sum() < 1:
                    continue
                if len(set(y_arr[tr].tolist())) < 2:
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
                mdl.fit(Xtr, y_arr[tr])
                classes = np.asarray(mdl.classes_)
                ptr = mdl.predict_proba(Xtr)
                tau = _pick_tau(ptr, y_arr[tr], classes, seed)
                taus_used.append(tau)
                pte = mdl.predict_proba(Xte)
                conf = pte.max(axis=1)
                trade = conf >= tau
                n_te += int(te.sum())
                n_traded += int(trade.sum())
                if trade.sum() < 1:
                    continue
                preds = classes[pte[trade].argmax(axis=1)]
                all_preds.extend(str(p) for p in preds)
                all_truths.extend(y_arr[te][trade].tolist())
                all_dates.extend(date_arr[te][trade].tolist())
            cov = (n_traded / n_te) if n_te else 0.0
            if not all_preds or cov < min_cov:
                cells[key] = {
                    "under_sampled": True,
                    "n_scored": len(all_preds),
                    "n_distinct_days": len(set(all_dates)),
                    "warnings": [f"LOW_COVERAGE cov={cov:.4f}"],
                    "verdict": "UNDER_SAMPLED",
                    "mcc": None,
                    "accuracy": None,
                    "baselines": {},
                    "bootstrap": None,
                    "shuffle_control": None,
                    "oos_coverage": cov,
                }
                continue
            cell = evaluate_cell(all_preds, all_truths, all_dates, prereg)
            cell["oos_coverage"] = cov
            cell["tau_mean"] = float(np.mean(taus_used)) if taus_used else None
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
    path = out / f"abstention_eval_{report['generated_utc'][:10]}_{report['run_id']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "latest.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "reports" / "abstention_eval",
    )
    args = ap.parse_args()
    db = args.db or Path(__import__("db").DB_PATH)
    report = run_study(db)
    path = write_report(report, args.out_dir)
    s = report["summary"]
    print(
        f"abstention_eval_v1 — {s['verdict']} "
        f"({s['n_pass']} PASS / {s['n_fail']} FAIL / {s['n_under_sampled']} under-sampled)"
    )
    for k, t in report["cells"].items():
        print(
            f"  {k}: n={t.get('n_scored')} cov={t.get('oos_coverage')} "
            f"mcc={t.get('mcc')} -> {t.get('verdict')}"
        )
    print("report:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
