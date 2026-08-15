"""Study #5 runner: LightGBM walk-forward on the same track as Study #4."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from research.elastic_net_eval_v1.runner import (
    apply_advancement_screen,
    evaluate_cell,
    _et_date,
)
from research.incumbent_eval_v1.runner import invalid_threshold_horizons

PREREG_PATH = Path(__file__).resolve().parent / "prereg_v1.json"


class PreregViolationError(RuntimeError):
    pass


def load_prereg() -> dict[str, Any]:
    try:
        prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PreregViolationError(f"cannot load prereg {PREREG_PATH}: {e}") from e
    fam = prereg.get("family") or {}
    n = len(fam.get("tickers") or []) * len(fam.get("horizons") or [])
    if n != fam.get("n_cells"):
        raise PreregViolationError(f"family inconsistent: {n} != n_cells")
    if (prereg.get("model") or {}).get("name") != "lightgbm.LGBMClassifier":
        raise PreregViolationError("prereg model is not LightGBM")
    return prereg


def _fit_predict_cell(
    df: pd.DataFrame,
    *,
    label_col: str,
    train_days: list[str],
    test_days: list[str],
    model_cfg: dict[str, Any],
    seed: int,
) -> tuple[list[str], list[str], list[str]]:
    from ml_train import engineer_features

    d = df.copy()
    d["_et_date"] = [_et_date(t) for t in d["ts_utc"].astype(float)]
    d = d.sort_values("ts_utc")
    train_mask = d["_et_date"].isin(train_days)
    test_mask = d["_et_date"].isin(test_days)
    if int(train_mask.sum()) < 50 or int(test_mask.sum()) < 1:
        return [], [], []
    fit_end = int(train_mask.sum())
    d_ord = pd.concat([d.loc[train_mask], d.loc[test_mask]], axis=0, ignore_index=True)
    X, _names, _maps, _aux = engineer_features(d_ord, fit_end=fit_end)
    y = d_ord[label_col].astype(str).to_numpy()
    X_train, y_train = X[:fit_end], y[:fit_end]
    X_test, y_test = X[fit_end:], y[fit_end:]
    dates_test = d_ord["_et_date"].iloc[fit_end:].tolist()
    # LightGBM accepts NaN natively — do not drop sparse IWM/guest rows.
    X_train = np.asarray(X_train, dtype=float)
    X_test = np.asarray(X_test, dtype=float)
    if len(y_train) < 50 or len(y_test) < 1 or len(set(y_train.tolist())) < 2:
        return [], [], []
    mdl = lgb.LGBMClassifier(
        objective=str(model_cfg["objective"]),
        num_leaves=int(model_cfg["num_leaves"]),
        learning_rate=float(model_cfg["learning_rate"]),
        n_estimators=int(model_cfg["n_estimators"]),
        subsample=float(model_cfg["subsample"]),
        colsample_bytree=float(model_cfg["colsample_bytree"]),
        min_child_samples=int(model_cfg["min_child_samples"]),
        reg_lambda=float(model_cfg["reg_lambda"]),
        random_state=seed,
        verbosity=-1,
    )
    mdl.fit(X_train, y_train)
    preds = [str(p) for p in mdl.predict(X_test)]
    truths = [str(t) for t in y_test]
    return preds, truths, dates_test


def run_study(db_path: Path | str) -> dict[str, Any]:
    from ml_train import load_data
    from training_cache import (
        db_distinct_rth_et_dates_for_ticker,
        expanding_window_oof_folds,
    )

    prereg = load_prereg()
    fam = prereg["family"]
    model_cfg = prereg["model"]
    seed = int(prereg["randomness"]["seed"])
    n_folds = int((prereg.get("walk_forward") or {}).get("n_folds") or 3)
    invalid_hz = invalid_threshold_horizons()
    horizons = [h for h in fam["horizons"] if h not in invalid_hz]
    cells: dict[str, dict[str, Any]] = {}
    for ticker in fam["tickers"]:
        for hz in horizons:
            label_col = f"outcome_{hz}"
            days = db_distinct_rth_et_dates_for_ticker(
                str(db_path), str(ticker), label_column=label_col
            )
            folds = expanding_window_oof_folds(days, n_folds=n_folds)
            if not folds:
                cells[f"{ticker}:{hz}"] = {
                    "under_sampled": True,
                    "n_scored": 0,
                    "n_distinct_days": 0,
                    "warnings": ["NO_HOLDOUT"],
                    "verdict": "UNDER_SAMPLED",
                    "mcc": None,
                    "accuracy": None,
                    "baselines": {},
                    "bootstrap": None,
                    "shuffle_control": None,
                }
                continue
            df = load_data(
                db_path=str(db_path),
                ticker=str(ticker),
                label_column=label_col,
                ml_horizon_slug=hz,
            )
            if df is None or df.empty:
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
            all_preds: list[str] = []
            all_truths: list[str] = []
            all_dates: list[str] = []
            fold_n = 0
            for train_days, test_days in folds:
                preds, truths, dates = _fit_predict_cell(
                    df,
                    label_col=label_col,
                    train_days=list(train_days),
                    test_days=list(test_days),
                    model_cfg=model_cfg,
                    seed=seed,
                )
                all_preds.extend(preds)
                all_truths.extend(truths)
                all_dates.extend(dates)
                fold_n += 1
            cell = evaluate_cell(all_preds, all_truths, all_dates, prereg)
            cell["n_folds_scored"] = fold_n
            cells[f"{ticker}:{hz}"] = cell
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
        "family": fam,
        "cells": cells,
        "summary": {
            "verdict": summary,
            "n_cells": len(cells),
            "n_pass": n_pass,
            "n_fail": verdicts.count("FAIL"),
            "n_under_sampled": verdicts.count("UNDER_SAMPLED"),
            "not_an_admission_packet": prereg["explicitly_not"]["not_an_admission_packet"],
        },
    }


def write_report(report: dict[str, Any], out_dir: Path | str) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"lightgbm_eval_{report['generated_utc'][:10]}_{report['run_id']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "latest.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "reports" / "lightgbm_eval",
    )
    args = ap.parse_args()
    db = args.db
    if db is None:
        from db import DB_PATH

        db = Path(DB_PATH)
    report = run_study(db)
    path = write_report(report, args.out_dir)
    s = report["summary"]
    print(
        f"lightgbm_eval_v1 — {s['verdict']} "
        f"({s['n_pass']} PASS / {s['n_fail']} FAIL / {s['n_under_sampled']} under-sampled)"
    )
    for k, t in report["cells"].items():
        print(f"  {k}: n={t.get('n_scored')} mcc={t.get('mcc')} -> {t.get('verdict')}")
    print("report:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
