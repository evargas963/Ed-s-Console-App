"""Study #4 runner: Elastic Net / multinomial logistic walk-forward baseline.

Usage:
  python -m research.elastic_net_eval_v1.runner --db data/ed_console.db

Reuses ml_train.load_data / engineer_features and training_cache session splits.
Frozen params in prereg_v1.json. Report-only.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from research.incumbent_eval_v1 import stats
from research.incumbent_eval_v1.runner import invalid_threshold_horizons
from time_et import ET

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
        raise PreregViolationError(f"family inconsistent: {n} != n_cells={fam.get('n_cells')}")
    m = prereg.get("model") or {}
    if m.get("penalty") != "elasticnet" or m.get("name") != "sklearn.linear_model.LogisticRegression":
        raise PreregViolationError("prereg model diverged from Elastic Net logistic contract")
    return prereg


def _et_date(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=ET).strftime("%Y-%m-%d")


def _fit_predict_cell(
    df: pd.DataFrame,
    *,
    label_col: str,
    train_days: list[str],
    test_days: list[str],
    model_cfg: dict[str, Any],
    seed: int,
) -> tuple[list[str], list[str], list[str]]:
    """Return (preds, truths, et_dates) on the test partition only."""
    from ml_train import engineer_features

    d = df.copy()
    d["_et_date"] = [_et_date(t) for t in d["ts_utc"].astype(float)]
    d = d.sort_values("ts_utc")
    train_mask = d["_et_date"].isin(train_days)
    test_mask = d["_et_date"].isin(test_days)
    if int(train_mask.sum()) < 50 or int(test_mask.sum()) < 1:
        return [], [], []
    # Fit stateful transforms on train prefix only.
    fit_end = int(train_mask.sum())
    # engineer_features expects contiguous iloc[:fit_end] as train — reorder so train first.
    d_ord = pd.concat([d.loc[train_mask], d.loc[test_mask]], axis=0, ignore_index=True)
    X, _names, _maps, _aux = engineer_features(d_ord, fit_end=fit_end)
    y = d_ord[label_col].astype(str).to_numpy()
    X_train, y_train = X[:fit_end], y[:fit_end]
    X_test, y_test = X[fit_end:], y[fit_end:]
    dates_test = d_ord["_et_date"].iloc[fit_end:].tolist()
    # Train-only median impute for non-finite cells (IWM/guest feature sparsity).
    X_train = np.asarray(X_train, dtype=float)
    X_test = np.asarray(X_test, dtype=float)
    med = np.nanmedian(np.where(np.isfinite(X_train), X_train, np.nan), axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    for arr in (X_train, X_test):
        bad = ~np.isfinite(arr)
        if bad.any():
            arr[bad] = np.take(med, np.where(bad)[1])
    if len(y_train) < 50 or len(y_test) < 1:
        return [], [], []
    if len(set(y_train.tolist())) < 2:
        return [], [], []
    # Train-only scale — required for saga+elasticnet numerical stability (not a tuned hyperparam).
    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)
    # sklearn>=1.5 dropped multi_class=; multinomial is the multiclass path for saga+elasticnet.
    mdl = LogisticRegression(
        penalty=str(model_cfg["penalty"]),
        solver=str(model_cfg["solver"]),
        l1_ratio=float(model_cfg["l1_ratio"]),
        C=float(model_cfg["C"]),
        max_iter=int(model_cfg["max_iter"]),
        random_state=seed,
    )
    mdl.fit(X_train, y_train)
    preds = [str(p) for p in mdl.predict(X_test)]
    truths = [str(t) for t in y_test]
    return preds, truths, dates_test


def evaluate_cell(
    preds: list[str],
    truths: list[str],
    et_dates: list[str],
    prereg: dict[str, Any],
) -> dict[str, Any]:
    floors = prereg["sample_floors"]
    rnd = prereg["randomness"]
    days = sorted(set(et_dates))
    cm = stats.confusion_matrix(preds, truths)
    out: dict[str, Any] = {
        "n_scored": len(preds),
        "n_distinct_days": len(days),
        "date_range": [days[0], days[-1]] if days else None,
        "confusion_matrix": cm,
        "mcc": stats.mcc_multiclass(cm),
        "balanced_accuracy": stats.balanced_accuracy(cm),
        "accuracy": stats.accuracy(cm),
        "baselines": stats.baseline_accuracies(preds, truths),
        "warnings": [],
    }
    under = (
        len(preds) < int(floors["min_scored_rows_per_cell"])
        or len(days) < int(floors["min_distinct_days_per_cell"])
    )
    out["under_sampled"] = under
    if under:
        out["warnings"].append("UNDER_SAMPLED")
        out["bootstrap"] = None
        out["shuffle_control"] = None
        return out
    out["bootstrap"] = stats.day_block_bootstrap_mcc(
        preds, truths, et_dates, n_boot=int(rnd["bootstrap_B"]), seed=int(rnd["seed"])
    )
    out["shuffle_control"] = stats.shuffle_control_mcc(
        preds, truths, n_shuffles=int(rnd["shuffle_K"]), seed=int(rnd["seed"])
    )
    return out


def apply_advancement_screen(cells: dict[str, dict[str, Any]]) -> None:
    p_values = {
        k: (t.get("bootstrap") or {}).get("p_value") if not t["under_sampled"] else None
        for k, t in cells.items()
    }
    holm = stats.holm_bonferroni(p_values)
    for key, t in cells.items():
        t["holm"] = holm[key]
        if t["under_sampled"]:
            t["verdict"] = "UNDER_SAMPLED"
            continue
        boot = t.get("bootstrap") or {}
        ci = boot.get("ci95")
        sc = t.get("shuffle_control") or {}
        # Constant/degenerate predictors yield MCC=None and empty shuffle nulls —
        # that is a FAIL (no usable signal), not a leakage STOP.
        # Absence and zero both mean "no usable shuffle control", but they are stated
        # explicitly rather than coerced — `or 0` would silently invent a zero for a
        # missing key (repo-wide silent-zero lock, tests/test_ohlcv_schwab_first.py).
        _n_shuffles = sc.get("n_shuffles")
        _no_shuffles = _n_shuffles is None or int(_n_shuffles) == 0
        if t.get("mcc") is None and _no_shuffles:
            t["verdict"] = "FAIL"
            t["warnings"] = list(t.get("warnings") or []) + ["DEGENERATE_CONSTANT_PREDICTIONS"]
            continue
        shuffle_ok = sc.get("null_q025") is not None and sc["null_q025"] <= 0.0 <= sc["null_q975"]
        if not shuffle_ok:
            t["verdict"] = "STOP_SHUFFLE_CONTROL_FAILED"
            continue
        acc = t["accuracy"]
        base = t["baselines"]
        beats = acc is not None and all(
            base[b] is None or acc >= base[b] for b in ("always_flat", "majority_class", "persistence")
        )
        ci_excludes = bool(ci) and (ci[0] > 0.0 or ci[1] < 0.0)
        sig = holm[key]["significant"] is True
        t["screen"] = {
            "ci95_excludes_zero": ci_excludes,
            "holm_significant": sig,
            "beats_all_baselines": beats,
            "shuffle_control_ok": shuffle_ok,
        }
        t["verdict"] = "PASS" if (ci_excludes and sig and beats) else "FAIL"


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
            cell["n_oos_days"] = len(set(all_dates))
            cell["warnings"].append("EXPANDING_OOF_CONCAT; EMBARGO_61M_NAMED_LIMIT")
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
        "invalid_threshold_horizons_excluded": invalid_hz,
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
    path = out / f"elastic_net_eval_{report['generated_utc'][:10]}_{report['run_id']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "latest.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "reports" / "elastic_net_eval",
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
        f"elastic_net_eval_v1 — {s['verdict']} "
        f"({s['n_pass']} PASS / {s['n_fail']} FAIL / {s['n_under_sampled']} under-sampled)"
    )
    for k, t in report["cells"].items():
        print(f"  {k}: n={t.get('n_scored')} mcc={t.get('mcc')} -> {t.get('verdict')}")
    print("report:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
