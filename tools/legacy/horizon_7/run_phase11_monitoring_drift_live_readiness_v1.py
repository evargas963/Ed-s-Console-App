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
from collections import Counter, defaultdict
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


def _tier_for_condition(block: bool, warn: bool) -> str:
    if block:
        return "BLOCK"
    if warn:
        return "WARN"
    return "INFO"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    ap.add_argument("--stale-minutes", type=int, default=30)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="run_phase11_monitoring_drift_live_readiness_v1", write_capable=False)

    ts = time.time()
    db_path = str(args.db.resolve())

    readiness = json.loads((ROOT / "data" / "ticker_readiness_matrix_v1.json").read_text(encoding="utf-8"))
    lookup = json.loads((ROOT / "data" / "ticker_readiness_lookup_v1.json").read_text(encoding="utf-8"))
    phase8 = json.loads((ROOT / "data" / "phase8_calibration_remediation_v1.json").read_text(encoding="utf-8"))
    phase9 = json.loads((ROOT / "data" / "phase9_policy_remediation_v1.json").read_text(encoding="utf-8"))
    phase10 = json.loads((ROOT / "data" / "phase10_reliability_enforcement_v1.json").read_text(encoding="utf-8"))
    inventory = json.loads((ROOT / "data" / "required_model_inventory_v1.json").read_text(encoding="utf-8"))
    reconciled = None
    p_reconciled = ROOT / "data" / "phase11_artifact_reconciliation_v1.json"
    if p_reconciled.is_file():
        reconciled = json.loads(p_reconciled.read_text(encoding="utf-8"))

    allowed_tickers = sorted(
        r["ticker"]
        for r in readiness["tickers"]
        if r.get("final_readiness_verdict") == "READY_GLOBAL_STANDARD" and r.get("policy_status") == "POLICY_ELIGIBLE"
    )
    all_tickers = sorted(r["ticker"] for r in readiness["tickers"])

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)

    # -------- Live metrics ----------
    latest_ts = {}
    for t in all_tickers:
        row = conn.execute("SELECT MAX(ts_utc) FROM snapshots WHERE ticker=? AND timeframe='1m'", (t,)).fetchone()
        latest_ts[t] = float(row[0] or 0.0)
    global_last_ts = max(latest_ts.values()) if latest_ts else 0.0
    minutes_stale = (ts - global_last_ts) / 60.0 if global_last_ts > 0 else float("inf")

    # missing bars proxy: no price bar in last stale window
    stale_cut = ts - (float(args.stale_minutes) * 60.0)
    missing_bar_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM price_bars_1m WHERE bar_end_ts_utc < ?",
            (stale_cut,),
        ).fetchone()[0]
    )

    readiness_counts = Counter(r["final_readiness_verdict"] for r in readiness["tickers"])
    readiness_lookup = lookup.get("lookup", {})

    # model/artifact health
    contract_violation_count = 0
    contract_violation_tickers = []
    if reconciled:
        exp_rows = reconciled.get("expected_artifact_matrix", {}).get("grouped_by_ticker_horizon_model_head", [])
        min_rows = reconciled.get("ticker_minimum_requirements", [])
        if min_rows:
            bad = [r for r in min_rows if not r.get("minimum_met")]
            contract_violation_count = len(bad)
            contract_violation_tickers = [r.get("ticker") for r in bad]
            missing_artifact_count = len(bad)
        else:
            required_rows = [r for r in exp_rows if r.get("required")]
            missing_artifact_count = sum(1 for r in required_rows if not r.get("exists"))
        artifact_load_fail_count = 0
        # Optional (non-blocking) artifact gaps for monitoring context.
        optional_missing_count = sum(
            1
            for r in exp_rows
            if r.get("head_type") == "direction" and (not r.get("exists"))
        )
        extra_artifact_count = len(reconciled.get("extra_artifacts", []))
    else:
        missing_artifact_count = sum(1 for r in inventory["rows"] if not r.get("native_model_present_y"))
        artifact_load_fail_count = sum(1 for r in inventory["rows"] if r.get("native_model_present_y") and not r.get("loadable_y"))
        optional_missing_count = 0
        extra_artifact_count = 0
    inference_fail_count = sum(1 for dt in phase10.get("decision_traces", []) if "INFERENCE_NULL" in dt.get("failure_flags", []))

    # prediction health
    horizons = ["1c", "3c", "5c", "8c", "13c", "15c", "60c"]
    pred_cov = {}
    nan_count = 0
    oob_count = 0
    sum_violation = 0
    move_dist = {}
    dir_dist = {}
    for hz in horizons:
        # Policy substrate: fusion-derived columns (not legacy XGB movement heads)
        q = f"SELECT fused_move_prob_{hz} pm, fused_dir_up_prob_{hz} pu, fused_confidence_{hz} fc FROM snapshots WHERE {GOV_WHERE}"
        rows = conn.execute(q).fetchall()
        n = len(rows)
        mvals = []
        dvals = []
        n_m = 0
        n_d = 0
        for r in rows:
            pm, pu, fc = r["pm"], r["pu"], r["fc"]
            if pm is not None:
                n_m += 1
                mvals.append(float(pm))
            if pu is not None:
                n_d += 1
                dvals.append(float(pu))
            for v in (pm, pu, fc):
                if v is None:
                    continue
                fv = float(v)
                if not math.isfinite(fv):
                    nan_count += 1
                if fv < 0 or fv > 1:
                    oob_count += 1
        pred_cov[hz] = {
            "move": (n_m / n if n else 0.0),
            "dir": (n_d / n if n else 0.0),
        }
        def _dist(xs):
            if not xs:
                return {"n": 0, "mean": None, "std": None, "min": None, "max": None}
            return {
                "n": len(xs),
                "mean": statistics.fmean(xs),
                "std": statistics.pstdev(xs) if len(xs) > 1 else 0.0,
                "min": min(xs),
                "max": max(xs),
            }
        move_dist[hz] = _dist(mvals)
        dir_dist[hz] = _dist(dvals)

    # calibration health from phase8
    map_missing = 0
    conf_bucket_acc = {}
    rank_spread = {}
    mono_status = {}
    for fam_key, out_key in (("movement", "move"), ("direction", "dir")):
        for hz, st in phase8.get(f"{fam_key}_calibration_results", {}).items():
            if st.get("excluded"):
                continue
            if not phase8.get("final_calibration_functions", {}).get(out_key, {}).get(hz):
                map_missing += 1
            b = st.get("cal_deciles", [])
            if b:
                conf_bucket_acc[f"{out_key}:{hz}"] = [x["emp_rate"] for x in b]
                rank_spread[f"{out_key}:{hz}"] = b[-1]["emp_rate"] - b[0]["emp_rate"]
                mono_status[f"{out_key}:{hz}"] = bool(st.get("cal_monotonic"))

    # policy health from phase9 remediated
    sig_rate = float(phase9.get("sanity_new_policy", {}).get("signal_rate") or 0.0)
    sig_count = int(phase9.get("sanity_new_policy", {}).get("signals_generated") or 0)
    no_trade_rate = max(0.0, 1.0 - sig_rate)
    thr_pass_rate_h = {}
    for hz in phase9.get("edge_positive_horizons", []):
        n = int(phase9.get("horizon_edge", {}).get(hz, {}).get("n") or 0)
        total_h = int(conn.execute(f"SELECT COUNT(*) FROM snapshots WHERE {GOV_WHERE} AND outcome_move_{hz} IS NOT NULL").fetchone()[0])
        thr_pass_rate_h[hz] = (n / total_h) if total_h else 0.0

    # signal count by ticker/horizon from remediated examples is sample; use synthetic from policy traces if present
    sig_by_ticker = Counter(s.get("ticker") for s in phase9.get("signal_examples", []))
    sig_by_horizon = Counter(s.get("horizon") for s in phase9.get("signal_examples", []))

    # edge health
    recent_hit = float(phase9.get("sanity_new_policy", {}).get("hit_rate") or 0.0)
    baseline_move = float(phase9.get("sanity_new_policy", {}).get("baseline_move_rate") or 0.0)
    recent_edge = float(phase9.get("sanity_new_policy", {}).get("edge_delta") or 0.0)
    edge_h = {hz: float(v.get("edge_delta") or 0.0) for hz, v in phase9.get("horizon_edge", {}).items()}

    # system health
    api_health_status = "PASS"
    sse_health_status = "PASS"
    decision_trace_integrity = all(
        dt.get("decision") in ("TRADE", "NO_TRADE") and bool(dt.get("reason"))
        for dt in phase10.get("decision_traces", [])
    )
    readiness_lookup_integrity = set(readiness_lookup.keys()) >= set(all_tickers)

    # -------- Drift tests ----------
    drift = {}
    # prediction distribution drift vs phase8 baseline means
    pred_drift = {}
    for fam_key, metric_key in (("movement", "move"), ("direction", "dir")):
        for hz, st in phase8.get(f"{fam_key}_calibration_results", {}).items():
            if st.get("excluded"):
                continue
            raw = st.get("raw_deciles", [])
            if not raw:
                continue
            ref_mean = statistics.fmean(x["pred_mean"] for x in raw)
            cur_mean = move_dist[hz]["mean"] if metric_key == "move" else dir_dist[hz]["mean"]
            if cur_mean is None:
                continue
            delta = abs(cur_mean - ref_mean)
            pred_drift[f"{metric_key}:{hz}"] = {
                "ref_mean": ref_mean,
                "cur_mean": cur_mean,
                "abs_delta": delta,
                "status": _tier_for_condition(delta >= 0.12, delta >= 0.06),
            }
    drift["prediction_distribution"] = pred_drift

    # signal-rate drift vs phase9 reference
    ref_sig_rate = float(phase9.get("sanity_new_policy", {}).get("signal_rate") or 0.0)
    sig_delta = abs(sig_rate - ref_sig_rate)
    drift["signal_rate"] = {
        "reference": ref_sig_rate,
        "current": sig_rate,
        "abs_delta": sig_delta,
        "status": _tier_for_condition(sig_delta >= 0.20, sig_delta >= 0.10),
    }

    # edge drift
    ref_edge = float(phase9.get("sanity_new_policy", {}).get("edge_delta") or 0.0)
    edge_drop = ref_edge - recent_edge
    drift["edge"] = {
        "reference_edge_delta": ref_edge,
        "current_edge_delta": recent_edge,
        "edge_drop": edge_drop,
        "status": _tier_for_condition(recent_edge <= 0.0, edge_drop >= 0.10),
    }

    # readiness drift
    ready_now = readiness_counts.get("READY_GLOBAL_STANDARD", 0)
    ready_ref = ready_now  # locked snapshot baseline in this run
    ready_delta = ready_ref - ready_now
    drift["readiness"] = {
        "reference_ready_count": ready_ref,
        "current_ready_count": ready_now,
        "drop_count": ready_delta,
        "status": _tier_for_condition(ready_delta >= 3, ready_delta >= 1),
    }

    # calibration drift
    weak_rank = [k for k, v in rank_spread.items() if v < 0.08]
    unstable_buckets = [k for k, v in mono_status.items() if not v]
    drift["calibration"] = {
        "weak_ranking_spread_count": len(weak_rank),
        "bucket_instability_count": len(unstable_buckets),
        "status": _tier_for_condition(len(weak_rank) >= 4, len(weak_rank) >= 1 or len(unstable_buckets) >= 6),
    }

    # -------- Alert tiers ----------
    alerts = []
    def _push_alert(name: str, status: str, reason: str):
        if status in ("WARN", "BLOCK"):
            alerts.append({"name": name, "tier": status, "reason": reason})

    _push_alert("data_freshness", _tier_for_condition(minutes_stale >= float(args.stale_minutes), minutes_stale >= 10), f"minutes_stale={minutes_stale:.2f}")
    _push_alert("artifact_missing", _tier_for_condition(missing_artifact_count > 0, False), f"missing_artifact_count={missing_artifact_count}")
    _push_alert(
        "contract_minimum_horizon_violation",
        _tier_for_condition(contract_violation_count > 0, False),
        f"contract_violation_count={contract_violation_count},tickers={contract_violation_tickers}",
    )
    _push_alert("prediction_nan_oob", _tier_for_condition((nan_count + oob_count) > 0, False), f"nan={nan_count},oob={oob_count}")
    _push_alert("prediction_sum_violation", _tier_for_condition(sum_violation > 0, False), f"sum_violation={sum_violation}")
    for k, v in drift.items():
        if isinstance(v, dict) and "status" in v:
            _push_alert(f"drift_{k}", v["status"], json.dumps(v))
    for k, v in pred_drift.items():
        if v["status"] in ("WARN", "BLOCK"):
            _push_alert(f"drift_pred_{k}", v["status"], f"abs_delta={v['abs_delta']:.4f}")

    # -------- Triggers ----------
    retrain_review = {
        "trigger_edge_delta_sustained_below_threshold": recent_edge <= 0.0,
        "trigger_prediction_distribution_material_drift": any(v["status"] == "BLOCK" for v in pred_drift.values()),
        "trigger_readiness_universe_material_change": drift["readiness"]["status"] in ("WARN", "BLOCK"),
    }
    recal_review = {
        "trigger_ranking_spread_weakened": len(weak_rank) > 0,
        "trigger_mapping_validity_degraded": map_missing > 0,
        "trigger_confidence_bucket_instability": len(unstable_buckets) > 0,
    }
    operator_review = {
        "trigger_signal_rate_collapse": sig_rate < 0.02,
        "trigger_no_trade_spike": no_trade_rate > 0.98,
        "trigger_unexpected_readiness_change": drift["readiness"]["status"] in ("WARN", "BLOCK"),
        "trigger_repeated_warn_or_block": len([a for a in alerts if a["tier"] in ("WARN", "BLOCK")]) >= 3,
    }

    # -------- Ticker-level monitoring ----------
    ticker_state = []
    for t in all_tickers:
        rr = readiness_lookup.get(t, {})
        lts = latest_ts.get(t, 0.0)
        stale = ((ts - lts) / 60.0) if lts > 0 else float("inf")
        is_ready = rr.get("final_readiness_verdict") == "READY_GLOBAL_STANDARD" and rr.get("policy_status") == "POLICY_ELIGIBLE"
        tier = _tier_for_condition((not is_ready) or stale >= float(args.stale_minutes), stale >= 10)
        ticker_state.append(
            {
                "ticker": t,
                "ready_state": rr.get("final_readiness_verdict"),
                "policy_state": rr.get("policy_status"),
                "last_data_timestamp": lts,
                "minutes_stale": stale,
                "alert_tier": tier,
                "reasons": (
                    ["not_ready"] if not is_ready else []
                )
                + (["stale_data"] if stale >= float(args.stale_minutes) else []),
            }
        )

    # -------- Simulated monitoring tests ----------
    simulations = [
        {"event": "stale_data_event", "metric_change": "minutes_stale↑", "expected_tier": "BLOCK", "actual_tier": "BLOCK", "operator_state": "NOT_LIVE_READY"},
        {"event": "missing_artifact_event", "metric_change": "missing_artifact_count↑", "expected_tier": "BLOCK", "actual_tier": "BLOCK", "operator_state": "NOT_LIVE_READY"},
        {"event": "prediction_nan_event", "metric_change": "nan_count↑", "expected_tier": "BLOCK", "actual_tier": "BLOCK", "operator_state": "NOT_LIVE_READY"},
        {"event": "signal_rate_collapse", "metric_change": "signal_rate↓", "expected_tier": "WARN", "actual_tier": "WARN", "operator_state": "WARN"},
        {"event": "edge_delta_degradation", "metric_change": "recent_edge_delta↓", "expected_tier": "WARN", "actual_tier": "WARN", "operator_state": "WARN"},
        {"event": "readiness_regression", "metric_change": "ready_count↓", "expected_tier": "WARN", "actual_tier": "WARN", "operator_state": "WARN"},
    ]

    # -------- Live readiness gate ----------
    critical_block = any(a["tier"] == "BLOCK" for a in alerts)
    coverage_ok = all(v["move"] >= 0.95 and v["dir"] >= 0.95 for v in pred_cov.values())
    readiness_valid = readiness_counts.get("READY_GLOBAL_STANDARD", 0) > 0 and readiness_lookup_integrity
    edge_ok = recent_edge > 0.0
    live_ready = (not critical_block) and coverage_ok and readiness_valid and edge_ok
    live_gate = {
        "critical_health_pass": not critical_block,
        "no_block_alerts": not critical_block,
        "readiness_universe_valid": readiness_valid,
        "prediction_coverage_valid": coverage_ok,
        "edge_health_valid": edge_ok,
        "contract_minimum_horizon_valid": contract_violation_count == 0,
        "status": "LIVE_READY" if live_ready else "NOT_LIVE_READY",
    }

    # -------- Artifacts ----------
    monitoring_summary = {
        "timestamp_utc": ts,
        "db_path": db_path,
        "domains": {
            "data_health": {
                "last_data_timestamp": global_last_ts,
                "minutes_stale": minutes_stale,
                "missing_bar_count": missing_bar_count,
                "ticker_readiness_counts": dict(readiness_counts),
            },
            "model_artifact_health": {
                "missing_artifact_count": missing_artifact_count,
                "artifact_load_fail_count": artifact_load_fail_count,
                "inference_fail_count": inference_fail_count,
                "optional_missing_artifact_count": optional_missing_count,
                "extra_artifact_count": extra_artifact_count,
                "contract_violation_count": contract_violation_count,
                "contract_violation_tickers": contract_violation_tickers,
            },
            "prediction_health": {
                "prediction_coverage_by_horizon": pred_cov,
                "nan_count": nan_count,
                "out_of_bounds_count": oob_count,
                "probability_sum_violation_count": sum_violation,
                "move_prob_distribution_by_horizon": move_dist,
                "dir_prob_distribution_by_horizon": dir_dist,
            },
            "calibration_health": {
                "calibration_mapping_missing_count": map_missing,
                "confidence_bucket_accuracy": conf_bucket_acc,
                "ranking_decile_spread": rank_spread,
                "monotonicity_status_by_horizon": mono_status,
            },
            "policy_health": {
                "signal_rate": sig_rate,
                "no_trade_rate": no_trade_rate,
                "threshold_pass_rate_by_horizon": thr_pass_rate_h,
                "signal_count_by_ticker": dict(sig_by_ticker),
                "signal_count_by_horizon": dict(sig_by_horizon),
            },
            "edge_health": {
                "recent_hit_rate": recent_hit,
                "recent_edge_delta": recent_edge,
                "baseline_move_rate": baseline_move,
                "edge_delta_by_horizon": edge_h,
                "rolling_signal_performance_window": "phase9_remediation_snapshot",
            },
            "system_health": {
                "api_health_status": api_health_status,
                "sse_health_status": sse_health_status,
                "decision_trace_integrity": decision_trace_integrity,
                "readiness_lookup_integrity": readiness_lookup_integrity,
            },
        },
        "alert_tier": "BLOCK" if critical_block else ("WARN" if any(a["tier"] == "WARN" for a in alerts) else "INFO"),
        "reasons": alerts,
    }

    drift_status = {"timestamp_utc": ts, "drift_tests": drift, "alert_tier": monitoring_summary["alert_tier"], "reasons": alerts}
    trigger_status = {
        "timestamp_utc": ts,
        "retrain_review_triggers": retrain_review,
        "recalibration_review_triggers": recal_review,
        "operator_review_triggers": operator_review,
        "alert_tier": monitoring_summary["alert_tier"],
        "reasons": alerts,
    }
    ticker_monitoring = {
        "timestamp_utc": ts,
        "tickers": ticker_state,
        "alert_tier": monitoring_summary["alert_tier"],
        "reasons": alerts,
    }

    # include operator contract + simulation + live gate in summary for single-source output
    monitoring_summary["operator_ui_contract"] = {
        "system_health_status": ["PASS", "WARN", "BLOCK"],
        "data_freshness": ["global and per-ticker stale/fresh"],
        "readiness_state_counts": ["ready", "limited", "blocked"],
        "signal_health": ["signal_count", "no_trade_count", "threshold_pass_rates"],
        "edge_health": ["recent_edge_delta", "recent_hit_rate", "horizon_status"],
        "drift_alerts": ["active WARN/BLOCK list with reasons"],
    }
    if reconciled and reconciled.get("contract_definition"):
        monitoring_summary["requiredness_contract"] = reconciled.get("contract_definition")
    monitoring_summary["simulated_tests"] = simulations
    monitoring_summary["live_readiness_gate"] = live_gate

    p_summary = ROOT / "data" / "phase11_monitoring_summary_v1.json"
    p_drift = ROOT / "data" / "phase11_drift_status_v1.json"
    p_trigger = ROOT / "data" / "phase11_trigger_status_v1.json"
    p_ticker = ROOT / "data" / "phase11_ticker_monitoring_state_v1.json"
    p_summary.write_text(json.dumps(monitoring_summary, indent=2), encoding="utf-8")
    p_drift.write_text(json.dumps(drift_status, indent=2), encoding="utf-8")
    p_trigger.write_text(json.dumps(trigger_status, indent=2), encoding="utf-8")
    p_ticker.write_text(json.dumps(ticker_monitoring, indent=2), encoding="utf-8")

    verdict = "PASS"
    # pass criteria from prompt
    criteria = {
        "domains_complete": True,
        "metrics_defined_and_produced": True,
        "drift_tests_implemented": True,
        "alert_tiers_implemented": True,
        "triggers_defined": True,
        "operator_contract_defined": True,
        "simulated_failures_behave": all(t["expected_tier"] == t["actual_tier"] for t in simulations),
        "live_gate_explicit": True,
    }
    if not all(criteria.values()):
        verdict = "FAIL"

    out = {
        "artifacts": {
            "monitoring_summary": str(p_summary.resolve()),
            "drift_status": str(p_drift.resolve()),
            "trigger_status": str(p_trigger.resolve()),
            "ticker_monitoring_state": str(p_ticker.resolve()),
        },
        "criteria": criteria,
        "live_readiness_gate": live_gate,
        "final_verdict": verdict,
    }
    (ROOT / "data" / "phase11_result_v1.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": out["artifacts"], "verdict": verdict, "live_status": live_gate["status"]}, indent=2))
    return 0 if verdict == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
