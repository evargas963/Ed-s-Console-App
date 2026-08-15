"""FP-13: stress the sole economic survivor (har_rv QQQ:60c). Not admission."""

from __future__ import annotations

import argparse
import bisect
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from research.cost_aware_eval_v1.runner import _day_bootstrap_ci, _forward_ret_bp
from research.har_rv_eval_v1.runner import _build_xy
from research.kalman_eval_v1.runner import _fit_predict
from research.tcn_eval_v1.runner import _load_closes, _load_labeled_rows

SEED = 20260717
B = 1000
HZ = "60c"
TICKER = "QQQ"


def _oof_signed_raw(db: Path) -> tuple[list[float], list[str], list[float]]:
    """Return (signed_raw_bp per row, dates, signs) with 0 sign = abstain."""
    from training_cache import expanding_window_oof_folds

    ends, closes = _load_closes(db, TICKER)
    labeled = _load_labeled_rows(db, TICKER, f"outcome_{HZ}")
    X, ys, dates = _build_xy(ends, closes, labeled)
    js = []
    for ts, _y in labeled:
        j = bisect.bisect_right(ends, ts) - 1
        if j < 15:
            continue
        js.append(j)
    js_arr = np.asarray(js, dtype=np.int64)
    date_arr = np.asarray(dates)
    y_arr = np.asarray(ys)
    folds = expanding_window_oof_folds(sorted(set(dates)), n_folds=3)
    signed_raw: list[float] = []
    out_dates: list[str] = []
    signs: list[float] = []
    for train_days, test_days in folds:
        tr = np.isin(date_arr, train_days)
        te = np.isin(date_arr, test_days)
        if tr.sum() < 50 or te.sum() < 1:
            continue
        preds = _fit_predict(X[tr].copy(), y_arr[tr], X[te].copy(), SEED)
        for pred, j, d in zip(preds, js_arr[te], date_arr[te]):
            if pred == "up":
                sign = 1.0
            elif pred == "down":
                sign = -1.0
            else:
                signed_raw.append(0.0)
                signs.append(0.0)
                out_dates.append(str(d))
                continue
            raw = _forward_ret_bp(closes, int(j), HZ)
            signed_raw.append(sign * raw)
            signs.append(sign)
            out_dates.append(str(d))
    return signed_raw, out_dates, signs


def evaluate(signed_raw: list[float], dates: list[str], signs: list[float], cost_bp: float) -> dict[str, Any]:
    nets = []
    trade_nets = []
    for sr, sg in zip(signed_raw, signs):
        if sg == 0.0:
            nets.append(0.0)
        else:
            n = sr - cost_bp
            nets.append(n)
            trade_nets.append(n)
    day_nets: dict[str, list[float]] = {}
    for d, v in zip(dates, nets):
        day_nets.setdefault(d, []).append(float(v))
    arr = np.asarray(nets, dtype=np.float64)
    tarr = np.asarray(trade_nets, dtype=np.float64) if trade_nets else np.asarray([0.0])
    ci = _day_bootstrap_ci(day_nets, B, SEED)
    mean_all = float(arr.mean()) if len(arr) else 0.0
    mean_tr = float(tarr.mean()) if trade_nets else 0.0
    kill = mean_all <= 0.0 or (ci[0] <= 0.0 <= ci[1])
    return {
        "cost_round_trip_bp": cost_bp,
        "n_scored": len(nets),
        "n_trades": len(trade_nets),
        "mean_net_bp_all_rows": mean_all,
        "mean_net_bp_trades_only": mean_tr,
        "bootstrap_ci95_mean_net_bp_all_rows": ci,
        "verdict": "KILL" if kill else "SURVIVE",
        "kill_reasons": [
            r
            for r, ok in [
                ("mean_net_bp_le_0", mean_all <= 0.0),
                ("bootstrap_ci_includes_0", ci[0] <= 0.0 <= ci[1]),
            ]
            if ok
        ],
    }


def sign_shuffle_control(signed_raw: list[float], dates: list[str], signs: list[float], cost_bp: float, K: int = 200) -> dict[str, Any]:
    """Shuffle trade signs among trade rows; keep abstain mask. Null mean of mean_net."""
    rng = np.random.default_rng(SEED + 7)
    trade_idx = [i for i, s in enumerate(signs) if s != 0.0]
    _trade_signed = [signed_raw[i] for i in trade_idx]
    null_means = []
    for _ in range(K):
        # flip each trade sign randomly (equivalent to shuffling direction)
        flips = rng.choice([-1.0, 1.0], size=len(trade_idx))
        nets = [0.0] * len(signs)
        for i, fl in zip(trade_idx, flips):
            # original signed_raw already includes direction; divide by sign to get raw then re-sign
            raw_mag = signed_raw[i] / signs[i]
            nets[i] = fl * raw_mag - cost_bp
        null_means.append(float(np.mean(nets)))
    obs = evaluate(signed_raw, dates, signs, cost_bp)["mean_net_bp_all_rows"]
    null_means_a = np.asarray(null_means)
    p = float(np.mean(null_means_a >= obs))
    return {
        "observed_mean_net_bp": obs,
        "null_mean": float(null_means_a.mean()),
        "null_q975": float(np.quantile(null_means_a, 0.975)),
        "p_ge_observed": p,
        "n_shuffles": K,
        "fails_if_p_ge_0_05": p >= 0.05,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    args = ap.parse_args()
    db = args.db or Path(__import__("db").DB_PATH)
    signed_raw, dates, signs = _oof_signed_raw(Path(db))
    costs = [1.0, 2.0, 5.0]
    by_cost = {f"{c:g}bp": evaluate(signed_raw, dates, signs, c) for c in costs}
    shuffle = sign_shuffle_control(signed_raw, dates, signs, 1.0)
    # existence reminder
    har = json.loads(
        (Path(__file__).resolve().parents[2] / "reports" / "har_rv_eval" / "latest.json").read_text(
            encoding="utf-8"
        )
    )
    cell = har["cells"]["QQQ:60c"]
    report = {
        "schema": "fp13_economic_survivor_stress_v1",
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "run_id": uuid.uuid4().hex[:12],
        "target": "har_rv_eval_v1 QQQ:60c",
        "existence_screen": {
            "verdict": cell.get("verdict"),
            "mcc": cell.get("mcc"),
            "beats_all_baselines": (cell.get("screen") or {}).get("beats_all_baselines"),
            "note": "Existence FAIL stands; economic survivor is not admission.",
        },
        "cost_stress": by_cost,
        "sign_shuffle_control_1bp": shuffle,
        "summary": {
            "survives_1bp": by_cost["1bp"]["verdict"] == "SURVIVE",
            "survives_2bp": by_cost["2bp"]["verdict"] == "SURVIVE",
            "survives_5bp": by_cost["5bp"]["verdict"] == "SURVIVE",
            "shuffle_fails": shuffle["fails_if_p_ge_0_05"],
            "verdict": (
                "STRESS_KILL"
                if (
                    by_cost["2bp"]["verdict"] == "KILL"
                    or by_cost["5bp"]["verdict"] == "KILL"
                    or shuffle["fails_if_p_ge_0_05"]
                )
                else "STRESS_SURVIVE"
            ),
        },
    }
    out = Path(__file__).resolve().parents[2] / "reports" / "fp13_survivor_stress_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    s = report["summary"]
    print(f"fp13 stress — {s['verdict']}")
    for k, v in by_cost.items():
        print(
            f"  {k}: mean_all={v['mean_net_bp_all_rows']:.4f} "
            f"mean_tr={v['mean_net_bp_trades_only']:.4f} "
            f"ci={v['bootstrap_ci95_mean_net_bp_all_rows']} -> {v['verdict']}"
        )
    print(
        f"  shuffle_1bp: obs={shuffle['observed_mean_net_bp']:.4f} "
        f"null_q975={shuffle['null_q975']:.4f} p={shuffle['p_ge_observed']:.4f} "
        f"fails={shuffle['fails_if_p_ge_0_05']}"
    )
    print("report:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
