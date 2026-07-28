"""Study #9: HistGradientBoosting quantile(q=0.5) on forward pts → ternary."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from research.elastic_net_eval_v1.runner import apply_advancement_screen, evaluate_cell
from research.har_rv_eval_v1.runner import har_features
from research.incumbent_eval_v1.runner import invalid_threshold_horizons
from research.tcn_eval_v1.runner import session_safe_log_returns  # RC-31
from research.tcn_eval_v1.runner import CLASSES, _et_date, _load_closes
from timeframe_config import SNAPSHOT_TABLE_1M

PREREG_PATH = Path(__file__).resolve().parent / "prereg_v1.json"


def load_prereg() -> dict[str, Any]:
    return json.loads(PREREG_PATH.read_text(encoding="utf-8"))


def _load_pts_rows(db: Path, ticker: str, hz: str) -> list[tuple[float, str, float]]:
    lab = f"outcome_{hz}"
    pts = f"outcome_{hz}_pts"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    # normalized table may use same names
    cols = {r[1] for r in con.execute(f"PRAGMA table_info({SNAPSHOT_TABLE_1M})")}
    if pts not in cols or lab not in cols:
        con.close()
        return []
    rows = con.execute(
        f"SELECT ts_utc, {lab}, {pts} FROM {SNAPSHOT_TABLE_1M} "
        f"WHERE ticker=? AND {lab} IS NOT NULL AND {pts} IS NOT NULL ORDER BY ts_utc",
        (ticker,),
    ).fetchall()
    con.close()
    out = []
    for t, y, p in rows:
        if str(y) in CLASSES:
            out.append((float(t), str(y), float(p)))
    return out


def _build(ends, closes, rows):
    import bisect

    har = har_features(ends, closes)
    logp = np.log(np.clip(closes, 1e-12, None))
    rets = session_safe_log_returns(ends, closes)   # RC-31: gap returns are NaN
    xs, ys, dates = [], [], []
    pts = []
    for ts, y, p in rows:
        j = bisect.bisect_right(ends, ts) - 1
        if j < 15:
            continue
        feat = np.concatenate([har[j], rets[j - 4 : j + 1]])
        xs.append(feat)
        ys.append(y)
        pts.append(p)
        dates.append(_et_date(ts))
    if not xs:
        return np.zeros((0, 8)), [], [], np.zeros((0,))
    return np.asarray(xs, dtype=np.float64), ys, dates, np.asarray(pts, dtype=np.float64)


def _pts_to_dir(pred: np.ndarray, thr: float) -> list[str]:
    out = []
    for v in pred:
        if v > thr:
            out.append("up")
        elif v < -thr:
            out.append("down")
        else:
            out.append("flat")
    return out


def run_study(db_path: Path | str) -> dict[str, Any]:
    from training_cache import expanding_window_oof_folds

    prereg = load_prereg()
    cfg = prereg["model"]
    seed = int(prereg["randomness"]["seed"])
    n_folds = int(prereg["walk_forward"]["n_folds"])
    invalid_hz = set(invalid_threshold_horizons())
    cells: dict[str, dict[str, Any]] = {}
    for ticker in prereg["family"]["tickers"]:
        ends, closes = _load_closes(Path(db_path), str(ticker))
        for hz in prereg["family"]["horizons"]:
            if hz in invalid_hz:
                continue
            rows = _load_pts_rows(Path(db_path), str(ticker), hz)
            X, ys, dates, pts = _build(ends, closes, rows)
            key = f"{ticker}:{hz}"
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
                nz = np.abs(pts[tr])
                nz = nz[nz > 0]
                thr = float(np.median(nz)) if len(nz) else 0.0
                mdl = HistGradientBoostingRegressor(
                    loss="quantile",
                    quantile=float(cfg["quantile"]),
                    max_depth=int(cfg["max_depth"]),
                    max_iter=int(cfg["max_iter"]),
                    learning_rate=float(cfg["learning_rate"]),
                    random_state=seed,
                )
                mdl.fit(X[tr], pts[tr])
                pred_pts = mdl.predict(X[te])
                all_preds.extend(_pts_to_dir(pred_pts, thr))
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
    path = out / f"quantile_eval_{report['generated_utc'][:10]}_{report['run_id']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "latest.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "reports" / "quantile_eval",
    )
    args = ap.parse_args()
    db = args.db or Path(__import__("db").DB_PATH)
    report = run_study(db)
    path = write_report(report, args.out_dir)
    s = report["summary"]
    print(
        f"quantile_eval_v1 — {s['verdict']} "
        f"({s['n_pass']} PASS / {s['n_fail']} FAIL / {s['n_under_sampled']} under-sampled)"
    )
    for k, t in report["cells"].items():
        print(f"  {k}: n={t.get('n_scored')} mcc={t.get('mcc')} -> {t.get('verdict')}")
    print("report:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
