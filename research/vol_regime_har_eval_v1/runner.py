"""Study #18: HAR with train-fold realized_vol tercile conditioning."""

from __future__ import annotations

import argparse
import bisect
import json
import sqlite3
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
from research.tcn_eval_v1.runner import _et_date, _load_closes

PREREG_PATH = Path(__file__).resolve().parent / "prereg_v1.json"
MIN_BUCKET = 200


def load_prereg() -> dict[str, Any]:
    return json.loads(PREREG_PATH.read_text(encoding="utf-8"))


def _load_rows(db: Path, ticker: str, hz: str):
    label = f"outcome_{hz}"
    q = (
        f"SELECT ts_utc, {label}, realized_vol FROM snapshots_1m_normalized "
        f"WHERE ticker=? AND timeframe='1m' AND {label} IS NOT NULL "
        f"AND realized_vol IS NOT NULL"
    )
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = c.execute(q, (ticker,)).fetchall()
    c.close()
    return [(float(ts), str(y), float(rv)) for ts, y, rv in rows]


def _bucketize(rv: np.ndarray, edges: tuple[float, float]) -> np.ndarray:
    lo, hi = edges
    out = np.empty(len(rv), dtype=object)
    out[rv <= lo] = "low"
    out[(rv > lo) & (rv <= hi)] = "mid"
    out[rv > hi] = "high"
    return out


def _fit_predict(
    Xtr, ytr, rv_tr, Xte, rv_te, seed: int
) -> list[str]:
    q33, q66 = np.quantile(rv_tr, [1 / 3, 2 / 3])
    edges = (float(q33), float(q66))
    b_tr = _bucketize(rv_tr, edges)
    b_te = _bucketize(rv_te, edges)
    sc_p = StandardScaler()
    Xp = sc_p.fit_transform(Xtr)
    mdl_p = LogisticRegression(
        penalty="elasticnet",
        solver="saga",
        l1_ratio=0.5,
        C=1.0,
        max_iter=2000,
        random_state=seed,
    )
    if len(set(ytr.tolist())) < 2:
        maj = str(ytr[0]) if len(ytr) else "flat"
        return [maj] * len(Xte)
    mdl_p.fit(Xp, ytr)
    preds = [str(p) for p in mdl_p.predict(sc_p.transform(Xte))]
    for bucket in ("low", "mid", "high"):
        mask_tr = b_tr == bucket
        if int(mask_tr.sum()) < MIN_BUCKET:
            continue
        y_sub = ytr[mask_tr]
        if len(set(y_sub.tolist())) < 2:
            continue
        sc = StandardScaler()
        Xsub = sc.fit_transform(Xtr[mask_tr])
        mdl = LogisticRegression(
            penalty="elasticnet",
            solver="saga",
            l1_ratio=0.5,
            C=1.0,
            max_iter=2000,
            random_state=seed,
        )
        mdl.fit(Xsub, y_sub)
        mask_te = b_te == bucket
        if not mask_te.any():
            continue
        p_sub = [str(p) for p in mdl.predict(sc.transform(Xte[mask_te]))]
        for i, p in zip(np.where(mask_te)[0], p_sub):
            preds[int(i)] = p
    return preds


def run_study(db_path: Path | str) -> dict[str, Any]:
    from training_cache import expanding_window_oof_folds

    prereg = load_prereg()
    seed = int(prereg["randomness"]["seed"])
    n_folds = int(prereg["walk_forward"]["n_folds"])
    invalid_hz = set(invalid_threshold_horizons())
    cells: dict[str, dict[str, Any]] = {}
    for ticker in prereg["family"]["tickers"]:
        ends, closes = _load_closes(Path(db_path), str(ticker))
        feats = har_features(ends, closes)
        for hz in prereg["family"]["horizons"]:
            if hz in invalid_hz:
                continue
            key = f"{ticker}:{hz}"
            labeled = _load_rows(Path(db_path), str(ticker), str(hz))
            xs, ys, rvs, dates = [], [], [], []
            for ts, y, rv in labeled:
                j = bisect.bisect_right(ends, ts) - 1
                if j < 15 or not np.isfinite(rv):
                    continue
                xs.append(feats[j])
                ys.append(y)
                rvs.append(rv)
                dates.append(_et_date(ts))
            X = np.asarray(xs, dtype=np.float64) if xs else np.zeros((0, 3))
            rv_arr = np.asarray(rvs, dtype=np.float64)
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
                preds = _fit_predict(
                    X[tr], y_arr[tr], rv_arr[tr], X[te], rv_arr[te], seed
                )
                all_preds.extend(preds)
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
    path = out / f"vol_regime_har_eval_{report['generated_utc'][:10]}_{report['run_id']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "latest.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "reports" / "vol_regime_har_eval",
    )
    args = ap.parse_args()
    db = args.db or Path(__import__("db").DB_PATH)
    report = run_study(db)
    path = write_report(report, args.out_dir)
    s = report["summary"]
    print(
        f"vol_regime_har_eval_v1 — {s['verdict']} "
        f"({s['n_pass']} PASS / {s['n_fail']} FAIL / {s['n_under_sampled']} under-sampled)"
    )
    for k, t in report["cells"].items():
        print(f"  {k}: n={t.get('n_scored')} mcc={t.get('mcc')} -> {t.get('verdict')}")
    print("report:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
