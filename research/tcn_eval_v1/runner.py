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


def _load_closes(db: Path, ticker: str, *, session: str = "rth") -> tuple[np.ndarray, np.ndarray]:
    """RC-31: the session universe is an EXPLICIT parameter, sourced from the time_et authority.

    This loader selected ALL of price_bars_1m with no time predicate, and price_bars_1m carries
    extended hours BY DESIGN (~1,000 bars/session, RC-26) — the loader silently assumed
    bars == RTH. Thirteen runners (TCN, HAR, Kalman, quantile, survival, cross-asset, …) import
    it, so every bar-path study inherited overnight and extended-hours bars in its close series.
    `session="rth"` keeps only RTH minutes on real trading days; `session="all"` must be ASKED
    FOR, never assumed. An unknown universe refuses rather than guessing (fail-closed).
    """
    from time_et import is_tradable_session_ts_utc

    if session not in ("rth", "all"):
        raise ValueError(f"unknown session universe {session!r} — 'rth' or 'all', never implicit")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT bar_end_ts_utc, close FROM price_bars_1m WHERE ticker=? ORDER BY bar_end_ts_utc",
        (ticker,),
    ).fetchall()
    con.close()
    if session == "rth":
        rows = [r for r in rows if is_tradable_session_ts_utc(float(r[0]))]
    ends = np.array([float(r[0]) for r in rows], dtype=np.float64)
    closes = np.array([float(r[1]) for r in rows], dtype=np.float64)
    return ends, closes


def session_safe_log_returns(ends: np.ndarray, closes: np.ndarray) -> np.ndarray:
    """RC-31 (reopened): THE one bar-return primitive for every bar-path study.

    r[i] = log(close[i] / close[i-1]) when bars i-1 and i are in the SAME ET session; np.nan at
    r[0] and at every session boundary. The first close was a scope close: TCN's window builder
    was fixed while HAR, Kalman, cross-asset, quantile, survival and cost-aware each ran their
    OWN np.diff over the same closes — reproduced same-turn: har_features(...)[3,0] equalled
    log(MonOpen/FriClose)^2 exactly, the whole weekend as one bar-to-bar r^2.

    NaN, deliberately, not zero: a zeroed gap fabricates calm and silently deflates every
    vol-style feature. NaN cannot be averaged, summed or squared without the consumer noticing —
    it forces EXCLUSION, which is the honest treatment, and any consumer that ignores it gets a
    NaN feature instead of a wrong one (fail-loud, not fail-plausible).
    """
    logc = np.log(np.clip(closes, 1e-12, None))
    rets = np.diff(logc, prepend=logc[0])
    if len(ends):
        rets[0] = np.nan                              # the prepend self-diff is not a return
        days = np.array([_et_date(float(t)) for t in ends])
        if len(days) > 1:
            rets[1:][days[1:] != days[:-1]] = np.nan  # the gap is not a return either
    return rets


def _load_labeled_rows(
    db: Path, ticker: str, label_col: str, *, session: str = "rth"
) -> list[tuple[float, str]]:
    """RC-31 (reopened, operator v7 audit): the LABELS were still ungated.

    The bars got a session universe (`_load_closes`) while this loader kept selecting every
    labeled snapshot row — a weekend/extended-hours label would attach frozen-market outcomes to
    RTH features. Same explicit-universe contract as `_load_closes`: rth by default, "all" must
    be asked for, unknown refuses.
    """
    from time_et import is_tradable_session_ts_utc

    from timeframe_config import SNAPSHOT_TABLE_1M

    if session not in ("rth", "all"):
        raise ValueError(f"unknown session universe {session!r} — 'rth' or 'all', never implicit")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        f"SELECT ts_utc, {label_col} FROM {SNAPSHOT_TABLE_1M} "
        f"WHERE ticker=? AND {label_col} IS NOT NULL ORDER BY ts_utc",
        (ticker,),
    ).fetchall()
    con.close()
    if session == "rth":
        rows = [r for r in rows if is_tradable_session_ts_utc(float(r[0]))]
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
    # RC-31: an OVERNIGHT return must never enter a feature window. Even on session-filtered
    # bars, np.diff at a day boundary (Friday 16:00 close -> Monday 09:31 close) fabricates one
    # giant "one-minute" return spanning the whole gap. Zeroing it would fabricate calm instead;
    # the honest treatment is to EXCLUDE any window that spans a session boundary.
    bar_days = np.array([_et_date(t) for t in ends]) if len(ends) else np.array([])
    xs, ys, dates = [], [], []
    for ts, y in labeled:
        j = bisect.bisect_right(ends, ts) - 1
        if j < lookback:
            continue
        lo = j - lookback + 1
        # rets[i] is the diff from bar i-1 to bar i, so the window's returns REACH BACK to bar
        # lo-1: a window starting at Monday's FIRST bar has same-day endpoints while its first
        # return is the whole weekend gap. Compare from lo-1, not lo. (rets[0] is the prepend
        # self-diff, exactly 0, so lo == 0 is safe.)
        if bar_days[max(lo - 1, 0)] != bar_days[j]:
            continue          # a return in this window spans a session boundary — it is fake
        xs.append(rets[lo : j + 1])
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
