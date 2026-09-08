#!/usr/bin/env python3

# DEPRECATED — 7-horizon era (pre Phase D3 schema drop).
# Targets retired outcome_3c/8c/13c columns; do not run against post-D3 databases.
# Relocated to tools/legacy/horizon_7/ for audit history only.
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

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import configure_sqlite_connection

GOV_WHERE = """
timeframe = '1m'
AND COALESCE(horizon_outcome_schema_version, 3) = 3
AND outcome_1c IS NOT NULL AND outcome_1c_pts IS NOT NULL
AND outcome_3c IS NOT NULL AND outcome_3c_pts IS NOT NULL
AND outcome_5c IS NOT NULL AND outcome_5c_pts IS NOT NULL
AND outcome_8c IS NOT NULL AND outcome_8c_pts IS NOT NULL
AND outcome_13c IS NOT NULL AND outcome_13c_pts IS NOT NULL
AND outcome_15c IS NOT NULL AND outcome_15c_pts IS NOT NULL
AND outcome_60c IS NOT NULL AND outcome_60c_pts IS NOT NULL
AND EXISTS (
  SELECT 1 FROM price_bars_1m p
  WHERE p.ticker = snapshots.ticker AND p.bar_end_ts_utc <= snapshots.ts_utc
)
""".strip()


def _interp_piecewise(x: float, xs: list[float], ys: list[float]) -> float:
    if not xs:
        return x
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        x0, x1 = xs[i], xs[i + 1]
        if x0 <= x <= x1:
            y0, y1 = ys[i], ys[i + 1]
            if abs(x1 - x0) < 1e-12:
                return y0
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return ys[-1]


def _apply_mapping(raw: float, mapping: dict) -> float:
    t = mapping.get("type")
    if t in ("isotonic", "bin_mono"):
        xs = [float(v) for v in mapping.get("x_thresholds", [])]
        ys = [float(v) for v in mapping.get("y_thresholds", [])]
        return max(0.0, min(1.0, _interp_piecewise(float(raw), xs, ys)))
    if t == "platt":
        a = float(mapping.get("coef", 0.0))
        b = float(mapping.get("intercept", 0.0))
        z = a * float(raw) + b
        if z >= 0:
            ez = math.exp(-z)
            return 1.0 / (1.0 + ez)
        ez = math.exp(z)
        return ez / (1.0 + ez)
    return max(0.0, min(1.0, float(raw)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    ap.add_argument("--top-n", type=int, default=5)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="run_phase9_decision_policy_v1", write_capable=False)

    readiness = json.loads((ROOT / "data" / "ticker_readiness_matrix_v1.json").read_text(encoding="utf-8"))
    rem = json.loads((ROOT / "data" / "phase8_calibration_remediation_v1.json").read_text(encoding="utf-8"))

    allowed_tickers = sorted(
        r["ticker"]
        for r in readiness["tickers"]
        if r.get("final_readiness_verdict") == "READY_GLOBAL_STANDARD"
        and r.get("policy_status") == "POLICY_ELIGIBLE"
    )
    mv_hz = sorted(set(rem["horizon_sets"]["movement"]["POLICY_CALIBRATED"] + rem["horizon_sets"]["movement"]["POLICY_RANK_ONLY"]))
    dr_hz = sorted(set(rem["horizon_sets"]["direction"]["POLICY_CALIBRATED"] + rem["horizon_sets"]["direction"]["POLICY_RANK_ONLY"]))

    # Thresholds: choose strongest edge with sample >= 120 per head/hz.
    thr_map: dict[tuple[str, str], dict] = {}
    for r in rem.get("thresholds", []):
        key = (r["head"], r["horizon"])
        cur = thr_map.get(key)
        if cur is None or float(r["edge_delta"]) > float(cur["edge_delta"]):
            thr_map[key] = r

    conn = sqlite3.connect(str(args.db.resolve()))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)

    rows = conn.execute(
        f"""
        SELECT *
        FROM snapshots
        WHERE ticker IN ({",".join(["?"] * len(allowed_tickers))})
          AND {GOV_WHERE}
        """,
        tuple(allowed_tickers),
    ).fetchall()
    conn.close()

    # Build per-horizon percentile baselines from calibrated move probabilities.
    per_h_values: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        d = dict(r)
        for hz in mv_hz:
            p = d.get(f"fused_move_prob_{hz}")
            if p is None:
                continue
            map_cfg = rem["final_calibration_functions"]["move"][hz]["mapping"]
            cp = _apply_mapping(float(p), map_cfg)
            per_h_values[hz].append(cp)
    per_h_sorted = {hz: sorted(vs) for hz, vs in per_h_values.items()}

    def percentile(hz: str, v: float) -> float:
        arr = per_h_sorted.get(hz) or []
        if not arr:
            return 0.0
        lo, hi = 0, len(arr)
        while lo < hi:
            mid = (lo + hi) // 2
            if arr[mid] <= v:
                lo = mid + 1
            else:
                hi = mid
        return lo / len(arr)

    signals = []
    horizon_order = {"60c": 7, "15c": 6, "13c": 5, "8c": 4, "5c": 3, "3c": 2, "1c": 1}
    tier_margin = 0.05
    for r in rows:
        d = dict(r)
        t = str(d["ticker"])
        per_row = []
        for hz in mv_hz:
            p_raw = d.get(f"fused_move_prob_{hz}")
            if p_raw is None:
                continue
            map_cfg = rem["final_calibration_functions"]["move"][hz]["mapping"]
            p_move = _apply_mapping(float(p_raw), map_cfg)
            thr = float(thr_map.get(("move", hz), {}).get("threshold", 1.1))
            pct = percentile(hz, p_move)
            if p_move >= thr + tier_margin and pct >= 0.92:
                tier = "TIER_1"
            elif p_move >= thr + 0.02 and pct >= 0.80:
                tier = "TIER_2"
            else:
                tier = "TIER_3"
            dir_prob = None
            dir_thr = None
            direction_bias = "neutral"
            if hz in dr_hz and d.get(f"fused_dir_up_prob_{hz}") is not None:
                d_raw = float(d[f"fused_dir_up_prob_{hz}"])
                d_map = rem["final_calibration_functions"]["dir"][hz]["mapping"]
                d_cal = _apply_mapping(d_raw, d_map)
                dir_prob = d_cal
                dir_thr = float(thr_map.get(("dir", hz), {}).get("threshold", 0.60))
                if d_cal >= dir_thr:
                    direction_bias = "long"
                elif d_cal <= (1.0 - dir_thr):
                    direction_bias = "short"
            per_row.append(
                {
                    "ticker": t,
                    "ts_utc": float(d.get("ts_utc") or 0.0),
                    "horizon": hz,
                    "move_prob": round(p_move, 6),
                    "move_threshold": thr,
                    "ranking_percentile": round(pct, 6),
                    "signal_tier": tier,
                    "direction_prob": round(dir_prob, 6) if dir_prob is not None else None,
                    "direction_threshold": dir_thr,
                    "direction_bias": direction_bias,
                    "entry_condition_met": tier in ("TIER_1", "TIER_2"),
                    "exit_rules": {
                        "time_exit_bars": int(hz[:-1]) if hz.endswith("c") and hz[:-1].isdigit() else None,
                        "early_exit_move_drop_below_threshold": True,
                        "early_exit_opposite_direction_signal": True,
                        "early_exit_signal_decay": "drop_one_tier_or_more",
                    },
                    "size_tier": "FULL" if tier == "TIER_1" else ("REDUCED_0_6" if tier == "TIER_2" else "NONE"),
                    "confidence_note": "rank_only_calibration",
                    "outcome_move": d.get(f"outcome_move_{hz}"),
                    "outcome_dir": d.get(f"outcome_dir_{hz}"),
                }
            )
        if not per_row:
            continue
        # multi-horizon logic: prefer longest qualifying horizon; require no strong conflict.
        qual = [x for x in per_row if x["entry_condition_met"]]
        if not qual:
            continue
        qual.sort(key=lambda x: (horizon_order.get(x["horizon"], 0), x["move_prob"]), reverse=True)
        chosen = qual[0]
        shorter = [x for x in qual if horizon_order.get(x["horizon"], 0) < horizon_order.get(chosen["horizon"], 0)]
        align = sum(1 for x in shorter if x["direction_bias"] in ("neutral", chosen["direction_bias"]))
        conflict = sum(1 for x in shorter if x["direction_bias"] not in ("neutral", chosen["direction_bias"]))
        if conflict > align + 1:
            continue
        chosen["cross_horizon_alignment"] = {"aligned_shorter": align, "conflicting_shorter": conflict}
        chosen["multi_horizon_policy"] = "prioritize_longest_then_alignment"
        signals.append(chosen)

    # Cross-ticker selection: top-N by move_prob then percentile.
    signals.sort(key=lambda x: (x["ts_utc"], x["move_prob"], x["ranking_percentile"]), reverse=True)
    selected = signals[: max(1, int(args.top_n))]

    # Lightweight sanity.
    total_rows = len(rows)
    trade_count = len(signals)
    sel_count = len(selected)
    move_hits = [1 if s.get("outcome_move") == "move" else 0 for s in signals]
    move_rate = statistics.fmean(move_hits) if move_hits else 0.0
    base_move = []
    for hz in mv_hz:
        ys = [1 if dict(r).get(f"outcome_move_{hz}") == "move" else 0 for r in rows if dict(r).get(f"outcome_move_{hz}") in ("move", "no_move")]
        if ys:
            base_move.append(statistics.fmean(ys))
    base_rate = statistics.fmean(base_move) if base_move else 0.0

    out = {
        "created_ts_utc": time.time(),
        "db_path": str(args.db.resolve()),
        "ticker_universe_used": allowed_tickers,
        "horizons_used": {"movement": mv_hz, "direction": dr_hz},
        "excluded_horizons": rem.get("excluded_family_horizon", []),
        "thresholds_selected": {f"{k[0]}:{k[1]}": v for k, v in thr_map.items()},
        "policy_rules": {
            "signal_tiers": {
                "TIER_1": "move_prob >= threshold+0.05 and ranking_percentile >= 0.90",
                "TIER_2": "move_prob >= threshold and ranking_percentile >= 0.70",
                "TIER_3": "otherwise",
            },
            "entry_rules": [
                "ticker must be READY_GLOBAL_STANDARD and POLICY_ELIGIBLE",
                "horizon must be POLICY_RANK_ONLY or POLICY_CALIBRATED",
                "calibrated_move_prob >= movement threshold",
                "tier in {TIER_1,TIER_2}",
            ],
            "direction_rule": "optional bias/confirmation only",
            "exit_rules": {
                "primary": "time-based exit at H bars",
                "early": [
                    "move_prob drops below threshold",
                    "opposite direction signal",
                    "signal tier decays by >=1",
                ],
            },
            "position_sizing": {"TIER_1": "FULL", "TIER_2": "REDUCED_0_6", "TIER_3": "NONE"},
            "multi_horizon": "prioritize longer horizon; downgrade/block on conflict",
            "cross_ticker_selection": f"select top {int(args.top_n)} by move_prob then percentile",
            "risk_limits": {
                "max_open_trades": int(args.top_n),
                "max_per_ticker": 1,
                "max_total_exposure": 1.0,
                "correlation_control": "avoid duplicate sector/index proxies when possible",
            },
        },
        "generated_signals_count": len(signals),
        "generated_signals_sample": signals[:500],
        "selected_signals": selected,
        "sanity": {
            "rows_evaluated": total_rows,
            "signals_generated": trade_count,
            "selected_signals": sel_count,
            "signal_rate": round(trade_count / total_rows, 6) if total_rows else 0.0,
            "move_hit_rate_on_signals": round(move_rate, 6),
            "baseline_move_rate": round(base_rate, 6),
            "edge_delta": round(move_rate - base_rate, 6),
            "not_excessive_trading": trade_count < max(1, int(0.35 * total_rows)),
            "edge_positive": move_rate > base_rate,
        },
    }

    verdict = (
        "PASS"
        if out["sanity"]["not_excessive_trading"]
        and out["sanity"]["edge_positive"]
        and len(mv_hz) > 0
        else "FAIL"
    )
    out["final_verdict"] = verdict

    outp = ROOT / "data" / "phase9_decision_policy_v1.json"
    outp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(outp), "verdict": verdict, "signals": trade_count, "selected": sel_count}, indent=2))
    return 0 if verdict == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
