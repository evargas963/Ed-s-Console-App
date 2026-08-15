"""FP-19: cost-aware kill on IWM L1:1c and IWM order_flow:1c faint leads."""

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

from research.cost_aware_eval_v1.runner import _day_bootstrap_ci, _forward_ret_bp
from research.tcn_eval_v1.runner import _load_closes

SEED = 20260717
B = 1000
COST = 1.0


def _eval_xy(
    X: np.ndarray,
    ys: list[str],
    dates: list[str],
    js: np.ndarray,
    closes: np.ndarray,
    hz: str,
) -> dict[str, Any]:
    from training_cache import expanding_window_oof_folds

    date_arr = np.asarray(dates)
    y_arr = np.asarray(ys)
    folds = expanding_window_oof_folds(sorted(set(dates)), n_folds=3)
    nets: list[float] = []
    out_dates: list[str] = []
    n_trades = 0
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
            random_state=SEED,
        )
        mdl.fit(Xtr, y_arr[tr])
        preds = [str(p) for p in mdl.predict(Xte)]
        for pred, j, d in zip(preds, js[te], date_arr[te]):
            if pred == "up":
                sign = 1.0
            elif pred == "down":
                sign = -1.0
            else:
                nets.append(0.0)
                out_dates.append(str(d))
                continue
            nets.append(sign * _forward_ret_bp(closes, int(j), hz) - COST)
            out_dates.append(str(d))
            n_trades += 1
    day_nets: dict[str, list[float]] = {}
    for d, v in zip(out_dates, nets):
        day_nets.setdefault(d, []).append(float(v))
    arr = np.asarray(nets, dtype=np.float64) if nets else np.asarray([0.0])
    mean_net = float(arr.mean()) if len(nets) else 0.0
    ci = _day_bootstrap_ci(day_nets, B, SEED)
    kill = mean_net <= 0.0 or (ci[0] <= 0.0 <= ci[1])
    return {
        "n_scored": len(nets),
        "n_trades": n_trades,
        "mean_net_bp": mean_net,
        "bootstrap_ci95_mean_net_bp": ci,
        "cost_round_trip_bp": COST,
        "verdict": "KILL" if kill else "SURVIVE_ECONOMIC",
    }


def _load_l1_with_js(db: Path, ticker: str, hz: str):
    import bisect
    import sqlite3

    label = f"outcome_{hz}"
    q = (
        f"SELECT ts_utc, {label}, bid_size, ask_size, spread, last_size "
        f"FROM snapshots_1m_normalized "
        f"WHERE ticker=? AND timeframe='1m' AND {label} IS NOT NULL"
    )
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = c.execute(q, (ticker,)).fetchall()
    c.close()
    ends, closes = _load_closes(db, ticker)
    xs, ys, dates, js = [], [], [], []
    from research.tcn_eval_v1.runner import _et_date

    for ts, y, bid, ask, spread, last in rows:
        if any(v is None for v in (bid, ask, spread, last)):
            continue
        bid_f, ask_f, sp_f, last_f = float(bid), float(ask), float(spread), float(last)
        if not all(np.isfinite(v) for v in (bid_f, ask_f, sp_f, last_f)):
            continue
        denom = bid_f + ask_f
        if denom <= 0:
            continue
        j = bisect.bisect_right(ends, float(ts)) - 1
        if j < 0:
            continue
        xs.append([(bid_f - ask_f) / denom, sp_f, last_f])
        ys.append(str(y))
        dates.append(_et_date(float(ts)))
        js.append(j)
    return (
        np.asarray(xs, dtype=np.float64) if xs else np.zeros((0, 3)),
        ys,
        dates,
        np.asarray(js, dtype=np.int64),
        closes,
    )


def _load_of_with_js(db: Path, ticker: str, hz: str):
    import bisect
    import sqlite3

    from research.order_flow_eval_v1.runner import FEATS
    from research.tcn_eval_v1.runner import _et_date

    label = f"outcome_{hz}"
    cols = ", ".join(FEATS)
    q = (
        f"SELECT ts_utc, {label}, {cols} FROM snapshots_1m_normalized "
        f"WHERE ticker=? AND timeframe='1m' AND {label} IS NOT NULL"
    )
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = c.execute(q, (ticker,)).fetchall()
    c.close()
    ends, closes = _load_closes(db, ticker)
    xs, ys, dates, js = [], [], [], []
    for r in rows:
        ts = float(r[0])
        y = str(r[1])
        feats = [r[i + 2] for i in range(len(FEATS))]
        if any(v is None or not np.isfinite(float(v)) for v in feats):
            continue
        j = bisect.bisect_right(ends, ts) - 1
        if j < 0:
            continue
        xs.append([float(v) for v in feats])
        ys.append(y)
        dates.append(_et_date(ts))
        js.append(j)
    return (
        np.asarray(xs, dtype=np.float64) if xs else np.zeros((0, len(FEATS))),
        ys,
        dates,
        np.asarray(js, dtype=np.int64),
        closes,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    args = ap.parse_args()
    db = Path(args.db or __import__("db").DB_PATH)
    cells = {}
    X, ys, dates, js, closes = _load_l1_with_js(db, "IWM", "1c")
    cells["l1_book:IWM:1c"] = _eval_xy(X, ys, dates, js, closes, "1c")
    X, ys, dates, js, closes = _load_of_with_js(db, "IWM", "1c")
    cells["order_flow:IWM:1c"] = _eval_xy(X, ys, dates, js, closes, "1c")
    verdicts = [v["verdict"] for v in cells.values()]
    report = {
        "schema": "fp19_faint_lead_economic_kill_v1",
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "run_id": uuid.uuid4().hex[:12],
        "cost_model_id": "COST_V1_UNDERLYING_SPY",
        "cells": cells,
        "summary": {
            "verdict": "ECONOMIC_KILL" if all(v == "KILL" for v in verdicts) else "MIXED",
            "n_kill": verdicts.count("KILL"),
            "n_survive": verdicts.count("SURVIVE_ECONOMIC"),
        },
    }
    out = Path("reports/fp19_faint_lead_kill_latest.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"fp19 — {report['summary']['verdict']}")
    for k, v in cells.items():
        print(
            f"  {k}: mean_net_bp={v['mean_net_bp']:.4f} ci={v['bootstrap_ci95_mean_net_bp']} "
            f"trades={v['n_trades']} -> {v['verdict']}"
        )
    print("report:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
