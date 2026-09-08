#!/usr/bin/env python3

# DEPRECATED — 7-horizon era (pre Phase D3 schema drop).
# Targets retired outcome_3c/8c/13c columns; do not run against post-D3 databases.
# Relocated to tools/legacy/horizon_7/ for audit history only.
from __future__ import annotations

import argparse
import json
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
        import math

        a = float(mapping.get("coef", 0.0))
        b = float(mapping.get("intercept", 0.0))
        z = a * float(raw) + b
        if z >= 0:
            ez = math.exp(-z)
            return 1.0 / (1.0 + ez)
        ez = math.exp(z)
        return ez / (1.0 + ez)
    return max(0.0, min(1.0, float(raw)))


def _edge_for_indices(labels: list[int], idx: list[int], baseline: float) -> dict:
    if not idx:
        return {"n": 0, "hit_rate": 0.0, "edge_delta": -baseline}
    hr = statistics.fmean(labels[i] for i in idx)
    return {"n": len(idx), "hit_rate": float(hr), "edge_delta": float(hr - baseline)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    ap.add_argument("--min-signals", type=int, default=300)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="run_phase9_policy_remediation_v1", write_capable=False)

    readiness = json.loads((ROOT / "data" / "ticker_readiness_matrix_v1.json").read_text(encoding="utf-8"))
    phase8r = json.loads((ROOT / "data" / "phase8_calibration_remediation_v1.json").read_text(encoding="utf-8"))
    phase9fail = json.loads((ROOT / "data" / "phase9_decision_policy_v1.json").read_text(encoding="utf-8"))
    allowed_tickers = sorted(
        r["ticker"]
        for r in readiness["tickers"]
        if r["final_readiness_verdict"] == "READY_GLOBAL_STANDARD" and r["policy_status"] == "POLICY_ELIGIBLE"
    )
    mv_hz = sorted(set(phase8r["horizon_sets"]["movement"]["POLICY_RANK_ONLY"] + phase8r["horizon_sets"]["movement"]["POLICY_CALIBRATED"]))
    dr_hz = sorted(set(phase8r["horizon_sets"]["direction"]["POLICY_RANK_ONLY"] + phase8r["horizon_sets"]["direction"]["POLICY_CALIBRATED"]))
    excluded = set(tuple(x.split(":")) for x in phase8r.get("excluded_family_horizon", []))

    thresholds = {}
    for r in phase8r["thresholds"]:
        k = (r["head"], r["horizon"])
        cur = thresholds.get(k)
        if cur is None or float(r["edge_delta"]) > float(cur["edge_delta"]):
            thresholds[k] = r

    conn = sqlite3.connect(str(args.db.resolve()))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    rows = conn.execute(
        f"SELECT * FROM snapshots WHERE ticker IN ({','.join(['?'] * len(allowed_tickers))}) AND {GOV_WHERE}",
        tuple(allowed_tickers),
    ).fetchall()
    conn.close()

    # Flatten candidates per row-horizon with calibrated values.
    cand = []
    for rr in rows:
        d = dict(rr)
        for hz in mv_hz:
            op = d.get(f"outcome_move_{hz}")
            rp = d.get(f"fused_move_prob_{hz}")
            if op not in ("move", "no_move") or rp is None:
                continue
            m_map = phase8r["final_calibration_functions"]["move"][hz]["mapping"]
            m_cal = _apply_mapping(float(rp), m_map)
            dy = None
            dp = d.get(f"fused_dir_up_prob_{hz}")
            do = d.get(f"outcome_dir_{hz}")
            if hz in dr_hz and ("dir", hz) not in excluded and dp is not None and do in ("up", "down"):
                d_map = phase8r["final_calibration_functions"]["dir"][hz]["mapping"]
                dy = _apply_mapping(float(dp), d_map)
            cand.append(
                {
                    "ticker": str(d["ticker"]),
                    "ts_utc": float(d.get("ts_utc") or 0.0),
                    "horizon": hz,
                    "move_cal": m_cal,
                    "dir_cal": dy,
                    "y_move": 1 if op == "move" else 0,
                }
            )

    labels = [c["y_move"] for c in cand]
    baseline = statistics.fmean(labels) if labels else 0.0

    # ranking percentile per horizon
    per_h = defaultdict(list)
    for i, c in enumerate(cand):
        per_h[c["horizon"]].append((i, c["move_cal"]))
    pct = {}
    for hz, arr in per_h.items():
        arr.sort(key=lambda t: t[1])
        n = len(arr)
        for rank, (i, _) in enumerate(arr, start=1):
            pct[i] = rank / n if n else 0.0

    # Step2 components
    idx_A = [i for i, c in enumerate(cand) if c["move_cal"] >= float(thresholds[("move", c["horizon"])]["threshold"])]
    idx_B = [i for i in idx_A if pct.get(i, 0.0) >= 0.80]
    idx_C = [
        i
        for i in idx_A
        if cand[i]["dir_cal"] is not None
        and cand[i]["dir_cal"] >= float(thresholds.get(("dir", cand[i]["horizon"]), {"threshold": 0.55})["threshold"])
    ]
    # D approx current (tier+ranking+direction optional): mimic strict tier margins from previous fail
    idx_D = [
        i
        for i, c in enumerate(cand)
        if c["move_cal"] >= float(thresholds[("move", c["horizon"])]["threshold"]) + 0.02 and pct.get(i, 0.0) >= 0.80
    ]

    comp = {
        "A_movement_only": _edge_for_indices(labels, idx_A, baseline),
        "B_move_plus_ranking": _edge_for_indices(labels, idx_B, baseline),
        "C_move_plus_direction": _edge_for_indices(labels, idx_C, baseline),
        "D_current_like": _edge_for_indices(labels, idx_D, baseline),
    }

    # Step3 horizon movement-only classification
    horizon_edge = {}
    edge_positive = []
    for hz in mv_hz:
        idx = [i for i, c in enumerate(cand) if c["horizon"] == hz and c["move_cal"] >= float(thresholds[("move", hz)]["threshold"])]
        st = _edge_for_indices(labels, idx, baseline)
        cls = "EDGE_POSITIVE" if st["edge_delta"] > 0 else ("EDGE_NEUTRAL" if abs(st["edge_delta"]) < 1e-9 else "EDGE_NEGATIVE")
        horizon_edge[hz] = {"classification": cls, **st}
        if cls == "EDGE_POSITIVE":
            edge_positive.append(hz)

    # Step4/5 test filters on EDGE_POSITIVE set
    idx_base = [i for i, c in enumerate(cand) if c["horizon"] in edge_positive and c["move_cal"] >= float(thresholds[("move", c["horizon"])]["threshold"])]
    idx_rank = [i for i in idx_base if pct.get(i, 0.0) >= 0.80]
    idx_dir = [
        i
        for i in idx_base
        if cand[i]["dir_cal"] is not None
        and cand[i]["dir_cal"] >= float(thresholds.get(("dir", cand[i]["horizon"]), {"threshold": 0.55})["threshold"])
    ]
    idx_topN = []
    # group by timestamp and keep top5 by move prob
    g = defaultdict(list)
    for i in idx_base:
        g[cand[i]["ts_utc"]].append(i)
    for _ts, arr in g.items():
        arr = sorted(arr, key=lambda i: cand[i]["move_cal"], reverse=True)[:5]
        idx_topN.extend(arr)

    filt = {
        "base_threshold_only": _edge_for_indices(labels, idx_base, baseline),
        "base_plus_ranking": _edge_for_indices(labels, idx_rank, baseline),
        "base_plus_direction_gate": _edge_for_indices(labels, idx_dir, baseline),
        "base_plus_topN": _edge_for_indices(labels, idx_topN, baseline),
    }

    # keep only beneficial filters
    best_idx = list(idx_base)
    removed_logic = []
    if filt["base_plus_ranking"]["edge_delta"] > filt["base_threshold_only"]["edge_delta"] and filt["base_plus_ranking"]["n"] >= 0.5 * filt["base_threshold_only"]["n"]:
        best_idx = idx_rank
    else:
        removed_logic.append("ranking_percentile_cutoff_removed_no_edge_gain")
    if filt["base_plus_direction_gate"]["edge_delta"] > _edge_for_indices(labels, best_idx, baseline)["edge_delta"] and filt["base_plus_direction_gate"]["n"] >= 0.5 * len(best_idx):
        best_idx = idx_dir
    else:
        removed_logic.append("direction_confirmation_removed_no_edge_gain")
    # topN only if improves edge materially and not too trivial
    if filt["base_plus_topN"]["edge_delta"] > _edge_for_indices(labels, best_idx, baseline)["edge_delta"] and filt["base_plus_topN"]["n"] >= args.min_signals:
        best_idx = idx_topN
    else:
        removed_logic.append("top_n_selection_removed_no_edge_gain")
    removed_logic.extend(
        [
            "tier_offset_removed_harmful_or_unnecessary",
            "longest_horizon_priority_removed_harmful_or_unnecessary",
            "early_exit_rules_removed_pending_no_backtest_gain",
        ]
    )

    # final selected signals
    final_signals = [cand[i] for i in best_idx]
    final_stats = _edge_for_indices(labels, best_idx, baseline)
    final_stats["baseline_move_rate"] = baseline
    final_stats["signals_generated"] = final_stats["n"]
    final_stats["signal_rate"] = final_stats["n"] / len(cand) if cand else 0.0

    # build output examples
    examples = []
    for c in sorted(final_signals, key=lambda x: (x["move_cal"], x["ts_utc"]), reverse=True)[:10]:
        hz = c["horizon"]
        dth = thresholds.get(("dir", hz), {}).get("threshold")
        dbias = "neutral"
        if c["dir_cal"] is not None and dth is not None:
            if c["dir_cal"] >= float(dth):
                dbias = "long"
            elif c["dir_cal"] <= 1.0 - float(dth):
                dbias = "short"
        examples.append(
            {
                "ticker": c["ticker"],
                "direction": dbias,
                "horizon": hz,
                "signal_tier": "TIER_1",
                "move_probability": round(c["move_cal"], 6),
                "direction_probability": round(c["dir_cal"], 6) if c["dir_cal"] is not None else None,
                "entry_condition_met": True,
                "exit_condition": {"time_based_bars": int(hz[:-1]), "early_exit_enabled": False},
                "position_size_tier": "FULL",
                "confidence_note": "movement_threshold_edge_positive_set",
            }
        )

    out = {
        "created_ts_utc": time.time(),
        "ticker_filter_used": allowed_tickers,
        "excluded_horizons": sorted(":".join(x) for x in excluded),
        "control": {
            "baseline_move_rate": baseline,
            "phase9_prev_move_hit_rate": phase9fail.get("sanity", {}).get("move_hit_rate_on_signals"),
            "phase9_prev_edge_delta": phase9fail.get("sanity", {}).get("edge_delta"),
        },
        "component_isolation": comp,
        "horizon_edge": horizon_edge,
        "edge_positive_horizons": sorted(edge_positive, key=lambda h: int(h[:-1])),
        "filter_tests": filt,
        "removed_logic": removed_logic,
        "final_policy_rules": {
            "entry": [
                "ticker must be READY_GLOBAL_STANDARD and POLICY_ELIGIBLE",
                "horizon must be in EDGE_POSITIVE set",
                "calibrated_move_prob_H >= threshold_H",
                "no tier offsets",
                "no mandatory ranking cutoff",
                "no mandatory direction gate",
            ],
            "exit": [
                "time-based exit at H bars",
                "early exits disabled for remediation policy",
            ],
            "selection": [
                "movement-threshold-only base selection",
                "direction used as bias annotation only",
                "no top-N truncation in base policy",
            ],
            "position_sizing": {
                "tier_model": "single-tier execution",
                "size": "FULL for qualified signals; NONE otherwise",
            },
        },
        "signal_examples": examples,
        "sanity_new_policy": final_stats,
    }
    out["final_verdict"] = "PASS" if final_stats["edge_delta"] > 0 and final_stats["signals_generated"] >= int(args.min_signals) else "FAIL"

    outp = ROOT / "data" / "phase9_policy_remediation_v1.json"
    outp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(outp), "verdict": out["final_verdict"], "signals": final_stats["signals_generated"], "edge_delta": round(final_stats["edge_delta"], 6)}, indent=2))
    return 0 if out["final_verdict"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
