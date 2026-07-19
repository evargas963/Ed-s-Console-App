"""Study #24: hedging-flow / charm → Elastic Net logistic."""

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
from research.tcn_eval_v1.runner import _et_date

PREREG_PATH = Path(__file__).resolve().parent / "prereg_v1.json"
NUM_FEATS = ["hedging_flow_score", "charm_net", "net_delta", "net_gamma"]
MAG_ORD = {"negligible": 0.0, "small": 1.0, "moderate": 2.0, "large": 3.0}
DIR_ORD = {"selling": -1.0, "neutral": 0.0, "buying": 1.0}
N_FEATS = 6


def load_prereg() -> dict[str, Any]:
    return json.loads(PREREG_PATH.read_text(encoding="utf-8"))


def _load_rows(db: Path, ticker: str, hz: str):
    import sqlite3

    label = f"outcome_{hz}"
    cols = ", ".join(NUM_FEATS + ["charm_magnitude", "hedging_flow_direction"])
    q = (
        f"SELECT ts_utc, {label}, {cols} FROM snapshots_1m_normalized "
        f"WHERE ticker=? AND timeframe='1m' AND {label} IS NOT NULL"
    )
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = c.execute(q, (ticker,)).fetchall()
    c.close()
    xs, ys, dates = [], [], []
    for r in rows:
        ts = float(r[0])
        y = str(r[1])
        nums = []
        ok = True
        for i in range(len(NUM_FEATS)):
            v = r[i + 2]
            if v is None:
                ok = False
                break
            try:
                fv = float(v)
            except (TypeError, ValueError):
                ok = False
                break
            if not np.isfinite(fv):
                ok = False
                break
            nums.append(fv)
        if not ok:
            continue
        mag = MAG_ORD.get(str(r[2 + len(NUM_FEATS)] or "").lower())
        direction = DIR_ORD.get(str(r[3 + len(NUM_FEATS)] or "").lower())
        if mag is None or direction is None:
            continue
        xs.append(nums + [mag, direction])
        ys.append(y)
        dates.append(_et_date(ts))
    if not xs:
        return np.zeros((0, N_FEATS)), [], []
    return np.asarray(xs, dtype=np.float64), ys, dates


def run_study(db_path: Path | str) -> dict[str, Any]:
    from training_cache import expanding_window_oof_folds

    prereg = load_prereg()
    seed = int(prereg["randomness"]["seed"])
    n_folds = int(prereg["walk_forward"]["n_folds"])
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
                all_preds.extend(str(p) for p in mdl.predict(Xte))
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
        f"hedging_flow_eval_{report['generated_utc'][:10]}_{report['run_id']}.json"
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
        default=Path(__file__).resolve().parents[2] / "reports" / "hedging_flow_eval",
    )
    args = ap.parse_args()
    db = args.db or Path(__import__("db").DB_PATH)
    report = run_study(db)
    path = write_report(report, args.out_dir)
    s = report["summary"]
    print(
        f"hedging_flow_eval_v1 — {s['verdict']} "
        f"({s['n_pass']} PASS / {s['n_fail']} FAIL / {s['n_under_sampled']} under-sampled)"
    )
    for k, t in report["cells"].items():
        print(f"  {k}: n={t.get('n_scored')} mcc={t.get('mcc')} -> {t.get('verdict')}")
    print("report:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
