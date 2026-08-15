"""Study #30: LightGBM on microstructure stack."""

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

from research.elastic_net_eval_v1.runner import apply_advancement_screen, evaluate_cell
from research.incumbent_eval_v1.runner import invalid_threshold_horizons
from research.micro_stack_eval_v1.runner import FEATS, _load_rows

PREREG_PATH = Path(__file__).resolve().parent / "prereg_v1.json"


def load_prereg() -> dict[str, Any]:
    return json.loads(PREREG_PATH.read_text(encoding="utf-8"))


def run_study(db_path: Path | str) -> dict[str, Any]:
    from training_cache import expanding_window_oof_folds

    prereg = load_prereg()
    seed = int(prereg["randomness"]["seed"])
    n_folds = int(prereg["walk_forward"]["n_folds"])
    hp = prereg["model"]["hyperparams"]
    invalid_hz = set(invalid_threshold_horizons())
    cells: dict[str, dict[str, Any]] = {}
    for ticker in prereg["family"]["tickers"]:
        for hz in prereg["family"]["horizons"]:
            if hz in invalid_hz:
                continue
            key = f"{ticker}:{hz}"
            X, ys, dates = _load_rows(Path(db_path), str(ticker), str(hz))
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
            for train_days, test_days in folds:
                tr = np.isin(date_arr, train_days)
                te = np.isin(date_arr, test_days)
                if tr.sum() < 50 or te.sum() < 1:
                    continue
                if len(set(y_arr[tr].tolist())) < 2:
                    continue
                mdl = lgb.LGBMClassifier(
                    objective=str(hp["objective"]),
                    num_leaves=int(hp["num_leaves"]),
                    learning_rate=float(hp["learning_rate"]),
                    n_estimators=int(hp["n_estimators"]),
                    subsample=float(hp["subsample"]),
                    colsample_bytree=float(hp["colsample_bytree"]),
                    random_state=seed,
                    verbose=-1,
                )
                mdl.fit(X[tr], y_arr[tr])
                all_preds.extend(str(p) for p in mdl.predict(X[te]))
                all_truths.extend(y_arr[te].tolist())
                all_dates.extend(date_arr[te].tolist())
            cells[key] = evaluate_cell(all_preds, all_truths, all_dates, prereg)
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
        "feature_names": list(FEATS),
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
    path = out / (
        f"lgbm_micro_eval_{report['generated_utc'][:10]}_{report['run_id']}.json"
    )
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "latest.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "reports" / "lgbm_micro_eval",
    )
    args = ap.parse_args()
    db = args.db or Path(__import__("db").DB_PATH)
    report = run_study(db)
    path = write_report(report, args.out_dir)
    s = report["summary"]
    print(
        f"lgbm_micro_eval_v1 — {s['verdict']} "
        f"({s['n_pass']} PASS / {s['n_fail']} FAIL / {s['n_under_sampled']} under-sampled)"
    )
    for k, t in report["cells"].items():
        print(f"  {k}: n={t.get('n_scored')} mcc={t.get('mcc')} -> {t.get('verdict')}")
    print("report:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
