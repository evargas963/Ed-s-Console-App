"""Study #6: small causal TCN on 1m log-return sequences → ternary outcomes."""

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
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from research.elastic_net_eval_v1.runner import apply_advancement_screen, evaluate_cell
from research.incumbent_eval_v1.runner import invalid_threshold_horizons
from time_et import ET

PREREG_PATH = Path(__file__).resolve().parent / "prereg_v1.json"
CLASSES = ("down", "flat", "up")


class PreregViolationError(RuntimeError):
    pass


def load_prereg() -> dict[str, Any]:
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    fam = prereg["family"]
    if fam["n_cells"] != len(fam["tickers"]) * len(fam["horizons"]):
        raise PreregViolationError("family n_cells mismatch")
    if prereg["model"]["name"] != "CausalTCN":
        raise PreregViolationError("model name mismatch")
    return prereg


class CausalTCN(nn.Module):
    def __init__(self, lookback: int, channels: list[int], kernel: int, dropout: float, n_classes: int = 3):
        super().__init__()
        layers: list[nn.Module] = []
        in_ch = 1
        for ch in channels:
            pad = kernel - 1
            layers += [
                nn.ConstantPad1d((pad, 0), 0.0),
                nn.Conv1d(in_ch, ch, kernel_size=kernel),
                nn.ReLU(),
                nn.Dropout(dropout),
            ]
            in_ch = ch
        self.backbone = nn.Sequential(*layers)
        self.head = nn.Linear(in_ch, n_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, L)
        h = self.backbone(x.unsqueeze(1))
        return self.head(h[:, :, -1])


def _et_date(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=ET).strftime("%Y-%m-%d")


def _load_closes(db: Path, ticker: str) -> tuple[np.ndarray, np.ndarray]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT bar_end_ts_utc, close FROM price_bars_1m WHERE ticker=? ORDER BY bar_end_ts_utc",
        (ticker,),
    ).fetchall()
    con.close()
    ends = np.array([float(r[0]) for r in rows], dtype=np.float64)
    closes = np.array([float(r[1]) for r in rows], dtype=np.float64)
    return ends, closes


def _load_labeled_rows(db: Path, ticker: str, label_col: str) -> list[tuple[float, str]]:
    from timeframe_config import SNAPSHOT_TABLE_1M

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        f"SELECT ts_utc, {label_col} FROM {SNAPSHOT_TABLE_1M} "
        f"WHERE ticker=? AND {label_col} IS NOT NULL ORDER BY ts_utc",
        (ticker,),
    ).fetchall()
    con.close()
    return [(float(t), str(y)) for t, y in rows if str(y) in CLASSES]


def _build_xy(
    ends: np.ndarray,
    closes: np.ndarray,
    labeled: list[tuple[float, str]],
    lookback: int,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    import bisect

    logc = np.log(np.clip(closes, 1e-12, None))
    rets = np.diff(logc, prepend=logc[0])
    xs, ys, dates = [], [], []
    for ts, y in labeled:
        j = bisect.bisect_right(ends, ts) - 1
        if j < lookback:
            continue
        xs.append(rets[j - lookback + 1 : j + 1])
        ys.append(CLASSES.index(y))
        dates.append(_et_date(ts))
    if not xs:
        return np.zeros((0, lookback)), np.zeros((0,), dtype=np.int64), []
    return np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=np.int64), dates


def _train_predict(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    cfg: dict[str, Any],
    seed: int,
) -> list[str]:
    torch.manual_seed(seed)
    device = torch.device("cpu")
    model = CausalTCN(
        lookback=int(cfg["lookback"]),
        channels=[int(c) for c in cfg["channels"]],
        kernel=int(cfg["kernel_size"]),
        dropout=float(cfg["dropout"]),
    ).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=float(cfg["lr"]))
    loss_fn = nn.CrossEntropyLoss()
    ds = TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train))
    loader = DataLoader(ds, batch_size=int(cfg["batch_size"]), shuffle=True)
    model.train()
    for _ in range(int(cfg["epochs"])):
        for xb, yb in loader:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad()
            loss_fn(model(xb), yb).backward()
            opt.step()
    model.eval()
    with torch.no_grad():
        logits = model(torch.from_numpy(X_test).to(device))
        pred_i = logits.argmax(dim=1).cpu().numpy()
    return [CLASSES[int(i)] for i in pred_i]


def run_study(db_path: Path | str) -> dict[str, Any]:
    from training_cache import expanding_window_oof_folds

    prereg = load_prereg()
    cfg = prereg["model"]
    seed = int(prereg["randomness"]["seed"])
    n_folds = int(prereg["walk_forward"]["n_folds"])
    lookback = int(cfg["lookback"])
    invalid_hz = invalid_threshold_horizons()
    cells: dict[str, dict[str, Any]] = {}
    for ticker in prereg["family"]["tickers"]:
        ends, closes = _load_closes(Path(db_path), str(ticker))
        for hz in prereg["family"]["horizons"]:
            if hz in invalid_hz:
                continue
            labeled = _load_labeled_rows(Path(db_path), str(ticker), f"outcome_{hz}")
            X, y, dates = _build_xy(ends, closes, labeled, lookback)
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
            all_preds: list[str] = []
            all_truths: list[str] = []
            all_dates: list[str] = []
            for train_days, test_days in folds:
                tr = np.isin(date_arr, train_days)
                te = np.isin(date_arr, test_days)
                if tr.sum() < 50 or te.sum() < 1:
                    continue
                preds = _train_predict(X[tr], y[tr], X[te], cfg, seed)
                truths = [CLASSES[int(i)] for i in y[te]]
                all_preds.extend(preds)
                all_truths.extend(truths)
                all_dates.extend(date_arr[te].tolist())
            cells[f"{ticker}:{hz}"] = evaluate_cell(all_preds, all_truths, all_dates, prereg)
    apply_advancement_screen(cells)
    verdicts = [t["verdict"] for t in cells.values()]
    n_pass = verdicts.count("PASS")
    n_stop = verdicts.count("STOP_SHUFFLE_CONTROL_FAILED")
    summary = (
        "STOP_SHUFFLE_CONTROL_FAILED"
        if n_stop
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
    path = out / f"tcn_eval_{report['generated_utc'][:10]}_{report['run_id']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "latest.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "reports" / "tcn_eval",
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
        f"tcn_eval_v1 — {s['verdict']} "
        f"({s['n_pass']} PASS / {s['n_fail']} FAIL / {s['n_under_sampled']} under-sampled)"
    )
    for k, t in report["cells"].items():
        print(f"  {k}: n={t.get('n_scored')} mcc={t.get('mcc')} -> {t.get('verdict')}")
    print("report:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
