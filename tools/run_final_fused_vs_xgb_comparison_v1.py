#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import configure_sqlite_connection
from ml_horizon import ML_HORIZON_SLUGS
from sklearn.isotonic import IsotonicRegression


def _brier(preds: list[float], y: list[int]) -> float:
    if not preds:
        return float("nan")
    return float(statistics.fmean((preds[i] - y[i]) ** 2 for i in range(len(preds))))


def _decile_bins(preds: list[float], y: list[int]) -> list[dict[str, float | int]]:
    n = len(preds)
    if n < 20:
        return []
    order = sorted(range(n), key=lambda i: preds[i])
    out: list[dict[str, float | int]] = []
    for d in range(10):
        lo = int(d * n / 10)
        hi = int((d + 1) * n / 10)
        idx = order[lo:hi]
        if not idx:
            continue
        ps = [preds[i] for i in idx]
        ys = [y[i] for i in idx]
        out.append(
            {
                "decile": d + 1,
                "n": len(idx),
                "pred_mean": float(statistics.fmean(ps)),
                "emp_rate": float(statistics.fmean(ys)),
            }
        )
    return out


def _monotonic_non_decreasing(vals: list[float], tol: float = 1e-9) -> bool:
    return all(vals[i] <= vals[i + 1] + tol for i in range(len(vals) - 1))


def _ranking_spread(preds: list[float], y: list[int]) -> float:
    n = len(preds)
    if n < 20:
        return float("nan")
    order = sorted(range(n), key=lambda i: preds[i])
    k = max(1, n // 10)
    bot = order[:k]
    top = order[-k:]
    return float(statistics.fmean(y[i] for i in top) - statistics.fmean(y[i] for i in bot))


def _bucket_mae(bins: list[dict[str, float | int]]) -> float:
    if not bins:
        return float("nan")
    return float(statistics.fmean(abs(float(b["pred_mean"]) - float(b["emp_rate"])) for b in bins))


def _calibrate_isotonic(preds: list[float], y: list[int]) -> list[float]:
    if len(preds) < 50:
        return preds[:]
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip")
    iso.fit(preds, y)
    return [float(iso.predict([v])[0]) for v in preds]


def _classify_winner(x: float, f: float, *, lower_is_better: bool, eps: float = 1e-6) -> str:
    if math.isnan(x) or math.isnan(f):
        return "INCONCLUSIVE"
    if lower_is_better:
        if f < x - eps:
            return "FUSED_BETTER"
        if x < f - eps:
            return "XGB_BETTER"
        return "FUSED_EQUAL"
    if f > x + eps:
        return "FUSED_BETTER"
    if x > f + eps:
        return "XGB_BETTER"
    return "FUSED_EQUAL"


def _signal_metrics(move_probs: list[float], dir_up_probs: list[float], y_move: list[int], y_up: list[int], move_thr: float, dir_thr: float) -> dict[str, Any]:
    n = len(move_probs)
    sig = 0
    wins = 0
    for i in range(n):
        m = move_probs[i]
        d = dir_up_probs[i]
        if m < move_thr:
            continue
        signal = 0
        if d >= dir_thr:
            signal = 1
        elif d <= (1.0 - dir_thr):
            signal = -1
        if signal == 0:
            continue
        sig += 1
        if y_move[i] == 1 and ((signal == 1 and y_up[i] == 1) or (signal == -1 and y_up[i] == 0)):
            wins += 1
    signal_rate = (sig / n) if n else 0.0
    no_trade_rate = 1.0 - signal_rate if n else 1.0
    hit_rate = (wins / sig) if sig else float("nan")
    baseline = float(statistics.fmean(y_move)) if y_move else float("nan")
    edge_delta = (hit_rate - baseline) if sig and not math.isnan(baseline) else float("nan")
    return {
        "sample_size": n,
        "signals": sig,
        "signal_rate": signal_rate,
        "no_trade_rate": no_trade_rate,
        "hit_rate": hit_rate,
        "edge_delta": edge_delta,
        "accepted_signal_quality": hit_rate,
    }


def _winner_from_votes(votes: list[str]) -> str:
    if not votes:
        return "INCONCLUSIVE"
    counts = defaultdict(int)
    for v in votes:
        counts[v] += 1
    if counts["FUSED_BETTER"] and counts["XGB_BETTER"]:
        return "MIXED"
    if counts["FUSED_BETTER"] > 0:
        return "FUSED_BETTER"
    if counts["XGB_BETTER"] > 0:
        return "XGB_BETTER"
    if counts["FUSED_EQUAL"] > 0:
        return "FUSED_EQUAL"
    return "INCONCLUSIVE"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    ap.add_argument("--move-threshold", type=float, default=0.60)
    ap.add_argument("--dir-threshold", type=float, default=0.55)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="run_final_fused_vs_xgb_comparison_v1", write_capable=False)

    conn = sqlite3.connect(str(args.db.resolve()))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)

    final_intersection: dict[str, Any] = {}
    phase8: dict[str, Any] = {}
    phase9: dict[str, Any] = {}
    stability: dict[str, Any] = {"by_horizon": {}, "by_ticker": {}, "by_month": {}}
    winner_by_hz: dict[str, str] = {}

    overall_xgb_move: list[float] = []
    overall_fused_move: list[float] = []
    overall_y_move: list[int] = []
    overall_xgb_dir: list[float] = []
    overall_fused_dir: list[float] = []
    overall_y_up: list[int] = []

    for hz in ML_HORIZON_SLUGS:
        q = f"""
        SELECT
          ticker,
          ts_utc,
          pred_move_prob_{hz} AS xgb_move,
          fused_move_prob_{hz} AS fused_move,
          pred_dir_up_prob_{hz} AS xgb_dir_up,
          fused_dir_up_prob_{hz} AS fused_dir_up,
          fused_confidence_{hz} AS fused_conf,
          outcome_move_{hz} AS outcome_move,
          outcome_dir_{hz} AS outcome_dir,
          valid_dir_{hz} AS valid_dir
        FROM snapshots
        WHERE timeframe = '1m'
          AND pred_move_prob_{hz} IS NOT NULL
          AND fused_move_prob_{hz} IS NOT NULL
          AND outcome_move_{hz} IS NOT NULL
        """
        rows = conn.execute(q).fetchall()
        if not rows:
            final_intersection[hz] = {"rows": 0}
            phase8[hz] = {"status": "INCONCLUSIVE", "reason": "no_rows"}
            phase9[hz] = {"status": "INCONCLUSIVE", "reason": "no_rows"}
            winner_by_hz[hz] = "INCONCLUSIVE"
            continue

        tickers = sorted({str(r["ticker"]) for r in rows})
        ts_min = min(float(r["ts_utc"]) for r in rows)
        ts_max = max(float(r["ts_utc"]) for r in rows)
        final_intersection[hz] = {
            "rows": len(rows),
            "ticker_coverage": len(tickers),
            "tickers": tickers,
            "ts_utc_min": ts_min,
            "ts_utc_max": ts_max,
        }

        xgb_move = [float(r["xgb_move"]) for r in rows]
        fused_move = [float(r["fused_move"]) for r in rows]
        y_move = [1 if str(r["outcome_move"]).strip().lower() == "move" else 0 for r in rows]

        xgb_move_cal = _calibrate_isotonic(xgb_move, y_move)
        fused_move_cal = _calibrate_isotonic(fused_move, y_move)

        bins_x_raw = _decile_bins(xgb_move, y_move)
        bins_f_raw = _decile_bins(fused_move, y_move)
        bins_x_cal = _decile_bins(xgb_move_cal, y_move)
        bins_f_cal = _decile_bins(fused_move_cal, y_move)

        conf_rows = [r for r in rows if r["fused_conf"] is not None]
        conf_use = {"available_rows": len(conf_rows), "status": "INCONCLUSIVE"}
        if len(conf_rows) >= 100:
            cvals = [float(r["fused_conf"]) for r in conf_rows]
            cy = [1 if str(r["outcome_move"]).strip().lower() == "move" else 0 for r in conf_rows]
            order = sorted(range(len(cvals)), key=lambda i: cvals[i])
            k = max(1, len(cvals) // 5)
            bot = order[:k]
            top = order[-k:]
            bot_rate = float(statistics.fmean(cy[i] for i in bot))
            top_rate = float(statistics.fmean(cy[i] for i in top))
            conf_use = {
                "available_rows": len(conf_rows),
                "bottom_quintile_hit": bot_rate,
                "top_quintile_hit": top_rate,
                "spread": top_rate - bot_rate,
                "status": "USEFUL" if top_rate > bot_rate else "NOT_USEFUL",
            }

        phase8_votes = [
            _classify_winner(_brier(xgb_move, y_move), _brier(fused_move, y_move), lower_is_better=True),
            _classify_winner(_brier(xgb_move_cal, y_move), _brier(fused_move_cal, y_move), lower_is_better=True),
            _classify_winner(_ranking_spread(xgb_move, y_move), _ranking_spread(fused_move, y_move), lower_is_better=False),
            _classify_winner(_bucket_mae(bins_x_cal), _bucket_mae(bins_f_cal), lower_is_better=True),
        ]
        phase8[hz] = {
            "brier": {
                "xgb_raw": _brier(xgb_move, y_move),
                "fused_raw": _brier(fused_move, y_move),
                "xgb_calibrated": _brier(xgb_move_cal, y_move),
                "fused_calibrated": _brier(fused_move_cal, y_move),
            },
            "ranking_decile_spread": {
                "xgb_raw": _ranking_spread(xgb_move, y_move),
                "fused_raw": _ranking_spread(fused_move, y_move),
                "xgb_calibrated": _ranking_spread(xgb_move_cal, y_move),
                "fused_calibrated": _ranking_spread(fused_move_cal, y_move),
            },
            "bucket_accuracy": {
                "xgb_bucket_mae_calibrated": _bucket_mae(bins_x_cal),
                "fused_bucket_mae_calibrated": _bucket_mae(bins_f_cal),
            },
            "monotonicity_calibration_status": {
                "xgb_raw_monotonic": _monotonic_non_decreasing([float(b["emp_rate"]) for b in bins_x_raw]),
                "fused_raw_monotonic": _monotonic_non_decreasing([float(b["emp_rate"]) for b in bins_f_raw]),
                "xgb_calibrated_monotonic": _monotonic_non_decreasing([float(b["emp_rate"]) for b in bins_x_cal]),
                "fused_calibrated_monotonic": _monotonic_non_decreasing([float(b["emp_rate"]) for b in bins_f_cal]),
            },
            "confidence_usefulness": conf_use,
            "winner": _winner_from_votes(phase8_votes),
        }

        rows_phase9 = [
            r
            for r in rows
            if r["xgb_dir_up"] is not None
            and r["fused_dir_up"] is not None
            and r["outcome_dir"] in ("up", "down")
            and int(r["valid_dir"] or 0) == 1
        ]
        xgb_move_9 = [float(r["xgb_move"]) for r in rows_phase9]
        fused_move_9 = [float(r["fused_move"]) for r in rows_phase9]
        xgb_dir = [float(r["xgb_dir_up"]) for r in rows_phase9]
        fused_dir = [float(r["fused_dir_up"]) for r in rows_phase9]
        y_move_9 = [1 if str(r["outcome_move"]).strip().lower() == "move" else 0 for r in rows_phase9]
        y_up = [1 if str(r["outcome_dir"]).strip().lower() == "up" else 0 for r in rows_phase9]

        m_x = _signal_metrics(xgb_move_9, xgb_dir, y_move_9, y_up, args.move_threshold, args.dir_threshold)
        m_f = _signal_metrics(fused_move_9, fused_dir, y_move_9, y_up, args.move_threshold, args.dir_threshold)

        phase9_votes = [
            _classify_winner(m_x["signal_rate"], m_f["signal_rate"], lower_is_better=False),
            _classify_winner(m_x["hit_rate"], m_f["hit_rate"], lower_is_better=False),
            _classify_winner(m_x["edge_delta"], m_f["edge_delta"], lower_is_better=False),
            _classify_winner(_ranking_spread(xgb_move, y_move), _ranking_spread(fused_move, y_move), lower_is_better=False),
        ]
        phase9[hz] = {
            "xgb_policy": m_x,
            "fused_policy": m_f,
            "threshold_gated_performance": {"move_threshold": args.move_threshold, "dir_threshold": args.dir_threshold},
            "winner": _winner_from_votes(phase9_votes),
        }

        hz_votes = [phase8[hz]["winner"], phase9[hz]["winner"]]
        winner_by_hz[hz] = _winner_from_votes(hz_votes)

        overall_xgb_move.extend(xgb_move)
        overall_fused_move.extend(fused_move)
        overall_y_move.extend(y_move)
        if xgb_dir and fused_dir and y_up:
            overall_xgb_dir.extend(xgb_dir)
            overall_fused_dir.extend(fused_dir)
            overall_y_up.extend(y_up)

        # stability by ticker and month uses move edge delta at threshold
        by_tkr = defaultdict(lambda: {"x": [], "f": [], "y": []})
        by_month = defaultdict(lambda: {"x": [], "f": [], "y": []})
        for r in rows:
            tkr = str(r["ticker"])
            month_key = time.strftime("%Y-%m", time.gmtime(float(r["ts_utc"])))
            by_tkr[tkr]["x"].append(float(r["xgb_move"]))
            by_tkr[tkr]["f"].append(float(r["fused_move"]))
            by_tkr[tkr]["y"].append(1 if str(r["outcome_move"]).strip().lower() == "move" else 0)
            by_month[month_key]["x"].append(float(r["xgb_move"]))
            by_month[month_key]["f"].append(float(r["fused_move"]))
            by_month[month_key]["y"].append(1 if str(r["outcome_move"]).strip().lower() == "move" else 0)

        tkr_out = {}
        for tkr, d in by_tkr.items():
            if len(d["y"]) < 50:
                continue
            ex = _signal_metrics(d["x"], [0.5] * len(d["x"]), d["y"], [0] * len(d["x"]), args.move_threshold, 1.0)
            ef = _signal_metrics(d["f"], [0.5] * len(d["f"]), d["y"], [0] * len(d["f"]), args.move_threshold, 1.0)
            tkr_out[tkr] = {"n": len(d["y"]), "edge_delta_diff_fused_minus_xgb": ef["edge_delta"] - ex["edge_delta"]}
        stability["by_ticker"][hz] = tkr_out

        month_out = {}
        for mk, d in by_month.items():
            if len(d["y"]) < 50:
                continue
            ex = _signal_metrics(d["x"], [0.5] * len(d["x"]), d["y"], [0] * len(d["x"]), args.move_threshold, 1.0)
            ef = _signal_metrics(d["f"], [0.5] * len(d["f"]), d["y"], [0] * len(d["f"]), args.move_threshold, 1.0)
            month_out[mk] = {"n": len(d["y"]), "edge_delta_diff_fused_minus_xgb": ef["edge_delta"] - ex["edge_delta"]}
        stability["by_month"][hz] = month_out

    conn.close()

    overall_phase8_votes = []
    overall_phase9_votes = []
    for hz in ML_HORIZON_SLUGS:
        if hz in phase8 and "winner" in phase8[hz]:
            overall_phase8_votes.append(phase8[hz]["winner"])
        if hz in phase9 and "winner" in phase9[hz]:
            overall_phase9_votes.append(phase9[hz]["winner"])

    winner_overall = _winner_from_votes(overall_phase8_votes + overall_phase9_votes)

    hz_improve = sum(1 for h, w in winner_by_hz.items() if w == "FUSED_BETTER")
    hz_degrade = sum(1 for h, w in winner_by_hz.items() if w == "XGB_BETTER")
    if hz_improve >= 5 and hz_degrade == 0:
        stability_class = "improves broadly"
    elif hz_improve > 0 and hz_degrade > 0:
        stability_class = "improves selectively"
    elif hz_improve == 0 and hz_degrade == 0:
        stability_class = "is neutral"
    elif hz_degrade > 0:
        stability_class = "degrades in specific areas"
    else:
        stability_class = "is neutral"
    stability["classification"] = stability_class

    if winner_overall in ("FUSED_BETTER", "FUSED_EQUAL"):
        retrain_decision = "NO_RETRAIN_NEEDED"
    elif winner_overall == "MIXED":
        retrain_decision = "RECALIBRATION_ONLY"
    elif winner_overall == "XGB_BETTER":
        retrain_decision = "PARTIAL_RETRAIN_NEEDED"
    else:
        retrain_decision = "FULL_RETRAIN_NEEDED"

    out = {
        "created_ts_utc": time.time(),
        "db_path": str(args.db.resolve()),
        "FINAL_COMPARISON_INTERSECTION": final_intersection,
        "PHASE8_COMPARISON": phase8,
        "PHASE9_COMPARISON": phase9,
        "STABILITY_CHECK": stability,
        "WINNER_CLASSIFICATION": {"overall": winner_overall, "by_horizon": winner_by_hz},
        "RETRAIN_DECISION": retrain_decision,
    }

    # Verdict is about validity/completeness/honesty of the comparison.
    valid_intersection = all(final_intersection.get(h, {}).get("rows", 0) > 0 for h in ML_HORIZON_SLUGS)
    has_phase8 = all("winner" in phase8.get(h, {}) for h in ML_HORIZON_SLUGS)
    has_phase9 = all("winner" in phase9.get(h, {}) for h in ML_HORIZON_SLUGS)
    honest = winner_overall in {"FUSED_BETTER", "FUSED_EQUAL", "XGB_BETTER", "MIXED", "INCONCLUSIVE"}
    out["FINAL_VERDICT"] = "PASS" if (valid_intersection and has_phase8 and has_phase9 and honest) else "FAIL"

    outp = ROOT / "data" / "final_fused_vs_xgb_comparison_v1.json"
    outp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(outp), "FINAL_VERDICT": out["FINAL_VERDICT"], "winner_overall": winner_overall}, indent=2))
    return 0 if out["FINAL_VERDICT"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
