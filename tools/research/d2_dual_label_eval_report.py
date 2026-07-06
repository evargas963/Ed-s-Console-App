#!/usr/bin/env python3
"""
D2 dual-label backtest — learnability A/B eval (research-only; operator-approved
mission D2_DUAL_LABEL_BACKTEST_EXECUTE, 2026-07-06).

Bounded pilot design (NOT the production stack): for each ticker x horizon, one
XGBoost multiclass model per label family (fixed outcome_{hz} vs triple-barrier
outcome_tb_{hz}) trained on the IDENTICAL feature matrix and IDENTICAL
chronological 80/20 split — rows restricted to those where BOTH labels exist so
the comparison is row-for-row fair. Features come from the production
ml_train.engineer_features with fit_end at the split boundary (no leakage).
This answers "which label geometry is more learnable"; the full production-stack
matrix (LSTM/Transformer/meta + ablation survivors) remains operator-run.

Outputs: JSON + markdown report under --out. No production DB access at all —
reads only the scratch DB built by d2_build_dual_label_scratch_db.py.

Schwab CSV authority checked: yes
CSV row(s): NO_SCHWAB_EQUIVALENT — research training/eval over the scratch DB;
  no production market field read, derivation, emission, or actionability
  logic changed.
Derived-field disposition: none required (research-only outputs).
All consumers checked: yes — reads scratch DB only; writes report files only.
SCHWAB_CSV_CHECKED
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HORIZONS = ("5c", "15c")
TICKERS_BASE = ("SPY", "QQQ", "IWM")
TICKERS_GUEST = ("AAPL", "TSLA")
CLASSES = ("up", "down", "flat")
TRAIN_FRACTION = 0.8
XGB_PARAMS = dict(
    n_estimators=300, max_depth=5, learning_rate=0.08, subsample=0.9,
    colsample_bytree=0.8, objective="multi:softprob", num_class=3,
    tree_method="hist", random_state=7, n_jobs=4, verbosity=0,
)


def _metrics(y_true: np.ndarray, proba: np.ndarray) -> dict:
    from sklearn.metrics import matthews_corrcoef

    pred = proba.argmax(axis=1)
    top = proba.max(axis=1)
    n = len(y_true)
    acc = float((pred == y_true).mean())
    counts = np.bincount(y_true, minlength=3)
    maj = counts.argmax()
    baseline = float(counts[maj] / n)
    # directional metrics: predictions of class 0/1 (up/down)
    dir_mask = pred != 2
    dir_prec = float((pred[dir_mask] == y_true[dir_mask]).mean()) if dir_mask.any() else None
    dir_base = float(((y_true == 0) | (y_true == 1)).mean() / 2)  # avg one-direction base rate
    flat_mask = pred == 2
    flat_prec = float((y_true[flat_mask] == 2).mean()) if flat_mask.any() else None
    flat_base = float((y_true == 2).mean())
    # ECE (10 equal-width bins on top prob) + high-bin gap
    ece = 0.0
    hi_gap = None
    for lo in np.arange(0.0, 1.0, 0.1):
        m = (top >= lo) & (top < lo + 0.1)
        if not m.any():
            continue
        gap = float((pred[m] == y_true[m]).mean() - top[m].mean())
        ece += (m.sum() / n) * abs(gap)
    m_hi = top >= 0.6
    if m_hi.any():
        hi_gap = float((pred[m_hi] == y_true[m_hi]).mean() - top[m_hi].mean())
    # confidence-bucket monotonicity (Spearman of bucket index vs realized acc)
    buckets = []
    for lo in (0.33, 0.40, 0.45, 0.50, 0.60):
        hi = 1.01 if lo == 0.60 else {0.33: 0.40, 0.40: 0.45, 0.45: 0.50, 0.50: 0.60}[lo]
        m = (top >= lo) & (top < hi)
        if m.sum() >= 30:
            buckets.append(float((pred[m] == y_true[m]).mean()))
    mono = None
    if len(buckets) >= 3:
        from scipy.stats import spearmanr

        mono = float(spearmanr(range(len(buckets)), buckets).statistic)
    # tradeable-subset directional accuracy (proxy gate: top>=0.45, margin>=0.08)
    srt = np.sort(proba, axis=1)
    margin = srt[:, -1] - srt[:, -2]
    gate = (top >= 0.45) & (margin >= 0.08) & dir_mask
    gate_acc = float((pred[gate] == y_true[gate]).mean()) if gate.any() else None
    return {
        "n_test": int(n),
        "mcc": round(float(matthews_corrcoef(y_true, pred)), 4),
        "accuracy": round(acc, 4),
        "majority_baseline": round(baseline, 4),
        "acc_minus_baseline_pp": round(100 * (acc - baseline), 1),
        "directional_precision": None if dir_prec is None else round(dir_prec, 4),
        "directional_pred_n": int(dir_mask.sum()),
        "directional_base_rate": round(dir_base, 4),
        "flat_precision": None if flat_prec is None else round(flat_prec, 4),
        "flat_base_rate": round(flat_base, 4),
        "ece": round(float(ece), 4),
        "high_bin_gap_060": None if hi_gap is None else round(hi_gap, 4),
        "bucket_monotonicity_spearman": None if mono is None else round(mono, 3),
        "tradeable_subset_acc": None if gate_acc is None else round(gate_acc, 4),
        "tradeable_subset_n": int(gate.sum()),
    }


def run_cell(df: pd.DataFrame, hz: str, exclude_truncated: bool) -> dict | None:
    """One ticker x horizon cell: fixed vs TB on identical rows/features/split."""
    from xgboost import XGBClassifier
    from ml_train import engineer_features

    fixed_col, tb_col = f"outcome_{hz}", f"outcome_tb_{hz}"
    sub = df[df[fixed_col].isin(CLASSES) & df[tb_col].isin(CLASSES)].copy()
    if exclude_truncated:
        sub = sub[sub[f"tb_truncated_{hz}"].fillna(0).astype(int) == 0]
    sub = sub.sort_values("ts_utc").reset_index(drop=True)
    if len(sub) < 1500:
        return None
    n_train = int(len(sub) * TRAIN_FRACTION)
    X, names, _cats, _aux = engineer_features(sub, fit_end=n_train)
    X = np.asarray(X, dtype=float)
    cls_idx = {c: i for i, c in enumerate(CLASSES)}
    out = {"n_rows": int(len(sub)), "n_train": n_train, "n_features": len(names)}
    for fam, col in (("fixed", fixed_col), ("tb", tb_col)):
        y = sub[col].map(cls_idx).to_numpy()
        model = XGBClassifier(**XGB_PARAMS)
        model.fit(X[:n_train], y[:n_train])
        proba = model.predict_proba(X[n_train:])
        out[fam] = _metrics(y[n_train:], proba)
        # class balance of the test labels themselves
        cb = np.bincount(y[n_train:], minlength=3) / max(len(y) - n_train, 1)
        out[fam]["test_label_balance"] = {c: round(float(cb[i]), 3) for c, i in cls_idx.items()}
    out["mcc_delta_tb_minus_fixed"] = round(out["tb"]["mcc"] - out["fixed"]["mcc"], 4)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="D2 dual-label learnability A/B")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "research" / "d2_dual_label.db")
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "d2_dual_label")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    from ml_data_common import filter_df_to_rth_ts_utc, stamp_et_clock_columns, attach_net_gamma_prev_column

    conn = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    t0 = time.time()
    report: dict = {"schema": "d2_dual_label_pilot_v1", "db": str(args.db),
                    "design": "xgb_learnability_ab_identical_rows_features_split",
                    "results": {}}
    for tkr in TICKERS_BASE + TICKERS_GUEST:
        df = pd.read_sql_query(
            "SELECT * FROM snapshots WHERE ticker=? AND timeframe='1m' ORDER BY ts_utc",
            conn, params=(tkr,))
        if df.empty:
            continue
        df = filter_df_to_rth_ts_utc(df)
        df = stamp_et_clock_columns(df)
        df = attach_net_gamma_prev_column(df)
        for hz in HORIZONS:
            for policy, excl in (("all_rows", False), ("excl_truncated", True)):
                cell = run_cell(df, hz, exclude_truncated=excl)
                if cell is not None:
                    report["results"][f"{tkr}_{hz}_{policy}"] = cell
    conn.close()
    report["elapsed_s"] = round(time.time() - t0, 1)
    (args.out / "d2_dual_label_pilot.json").write_text(
        json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    # verdict per the approved acceptance rule (base tickers, excl_truncated policy)
    verdict_cells = {}
    for tkr in TICKERS_BASE:
        for hz in HORIZONS:
            c = report["results"].get(f"{tkr}_{hz}_excl_truncated")
            if c:
                verdict_cells[f"{tkr}_{hz}"] = {
                    "mcc_fixed": c["fixed"]["mcc"], "mcc_tb": c["tb"]["mcc"],
                    "delta": c["mcc_delta_tb_minus_fixed"],
                    "tb_dir_prec_above_base": (
                        c["tb"]["directional_precision"] is not None
                        and c["tb"]["directional_precision"] > c["tb"]["directional_base_rate"]
                    ),
                    "tb_ece_no_worse": c["tb"]["ece"] <= c["fixed"]["ece"] + 0.01,
                }
    per_hz_pass = {}
    for hz in HORIZONS:
        wins = sum(
            1 for tkr in TICKERS_BASE
            if (v := verdict_cells.get(f"{tkr}_{hz}"))
            and v["delta"] >= 0.05 and v["tb_dir_prec_above_base"] and v["tb_ece_no_worse"]
        )
        per_hz_pass[hz] = wins
    if all(w >= 2 for w in per_hz_pass.values()):
        verdict = "ADOPT_SIGNAL"
    elif all(
        (v["delta"] <= 0 for v in verdict_cells.values())
    ) or all(not v["tb_dir_prec_above_base"] for v in verdict_cells.values()):
        verdict = "REJECT"
    else:
        verdict = "MIXED_MORE_RESEARCH"
    report_summary = {"verdict": verdict, "per_hz_base_ticker_wins": per_hz_pass,
                      "cells": verdict_cells}
    (args.out / "d2_dual_label_verdict.json").write_text(
        json.dumps(report_summary, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(report_summary, indent=1, sort_keys=True))
    print(f"full report: {args.out / 'd2_dual_label_pilot.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
