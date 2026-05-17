"""
Minimum sample sizes for calibration analysis outputs (fail-closed).

Aligned with ``MIN_SAMPLES_STATISTICAL`` (30) from ``math_probabilities`` — same bar as
empirical similarity / prediction_engine withholding.
"""

from __future__ import annotations

import statistics
from typing import Any

from math_probabilities import MIN_SAMPLES_STATISTICAL

# All bucket minima default to production empirical floor unless noted.
MIN_N_CONFIDENCE_BUCKET = MIN_SAMPLES_STATISTICAL
MIN_N_REGIME_BUCKET = MIN_SAMPLES_STATISTICAL
MIN_N_MODEL_BY_REGIME_BUCKET = MIN_SAMPLES_STATISTICAL
MIN_N_THRESHOLD_GRID_CELL = MIN_SAMPLES_STATISTICAL
MIN_N_PROBABILITY_BUCKET = MIN_SAMPLES_STATISTICAL
MIN_N_MHAP_BUCKET = MIN_SAMPLES_STATISTICAL
MIN_N_BASELINE_COMPARISON = MIN_SAMPLES_STATISTICAL
MIN_N_DECISION_SIGNAL = MIN_SAMPLES_STATISTICAL
MIN_N_SNAPSHOT_FALLBACK_CONVICTION = MIN_SAMPLES_STATISTICAL
MIN_N_BRIER_AGGREGATE = MIN_SAMPLES_STATISTICAL


def thresholds_dict() -> dict[str, int]:
    return {
        "confidence_bucket": MIN_N_CONFIDENCE_BUCKET,
        "regime_bucket": MIN_N_REGIME_BUCKET,
        "model_by_regime_bucket": MIN_N_MODEL_BY_REGIME_BUCKET,
        "threshold_grid_cell": MIN_N_THRESHOLD_GRID_CELL,
        "probability_bucket_expectancy": MIN_N_PROBABILITY_BUCKET,
        "mhap_alignment_bucket": MIN_N_MHAP_BUCKET,
        "baseline_comparison": MIN_N_BASELINE_COMPARISON,
        "decision_signal_performance": MIN_N_DECISION_SIGNAL,
        "snapshot_fallback_by_conviction": MIN_N_SNAPSHOT_FALLBACK_CONVICTION,
        "brier_aggregate": MIN_N_BRIER_AGGREGATE,
        "source_constant": "MIN_SAMPLES_STATISTICAL",
        "MIN_SAMPLES_STATISTICAL": MIN_SAMPLES_STATISTICAL,
    }


def bucket_gate(n: int, min_n: int) -> dict[str, Any]:
    ok = n >= min_n
    return {
        "n": n,
        "min_required": min_n,
        "sufficient_sample": ok,
        "status": "ok" if ok else "insufficient_sample",
    }


def gated_mean(vals: list[float], min_n: int) -> tuple[float | None, dict[str, Any]]:
    n = len(vals)
    gate = bucket_gate(n, min_n)
    if not gate["sufficient_sample"] or not vals:
        return None, gate
    return round(statistics.mean(vals), 6), gate


def gated_ratio(numer: int, denom: int) -> tuple[float | None, dict[str, Any]]:
    """Integer ratio (e.g. miss rate, null rate) withheld unless denom meets MIN_SAMPLES_STATISTICAL."""
    g = bucket_gate(denom, MIN_SAMPLES_STATISTICAL)
    if not g["sufficient_sample"]:
        return None, g
    return round(numer / max(denom, 1), 6), g


def _gate_ok_for_value(val: Any, gate: dict[str, Any] | None) -> bool:
    if val is None:
        return True
    if gate is None:
        return False
    return bool(gate.get("sufficient_sample"))


def verify_phase3_no_numeric_leak(out: dict[str, Any]) -> bool:
    """
    Defensive check: no empirical rate/mean should be present without sufficient_sample.
    Returns True if safe.
    """
    for _bkt, row in out.get("reliability_by_canonical_confidence", {}).items():
        g = row.get("sample_gate")
        if not _gate_ok_for_value(row.get("empirical_hit_rate"), g):
            return False
        if not _gate_ok_for_value(row.get("mean_max_class_probability"), g):
            return False
    for _k, row in out.get("regime_buckets", {}).items():
        g = row.get("sample_gate")
        if not _gate_ok_for_value(row.get("mean_5c_pts"), g):
            return False
    for _k, row in out.get("model_by_regime_buckets", {}).items():
        g = row.get("sample_gate")
        if not _gate_ok_for_value(row.get("mean_5c_pts"), g):
            return False
    grid = out.get("threshold_grid") or {}
    for cell in grid.get("thresholds_tried") or []:
        g = cell.get("sample_gate")
        if not _gate_ok_for_value(cell.get("mean_5c_pts"), g):
            return False
    for _k, row in out.get("probability_bucket_expectancy_5c_pts", {}).items():
        g = row.get("sample_gate")
        if not _gate_ok_for_value(row.get("mean_pts"), g):
            return False
    br = out.get("brier_sample_gate")
    if out.get("brier_canonical_vs_outcome_5c") is not None:
        if br is None or not br.get("sufficient_sample"):
            return False
    sf = out.get("snapshots_fallback") or {}
    for _conv, row in sf.get("by_combined_conviction", {}).items():
        g = row.get("sample_gate")
        if not _gate_ok_for_value(row.get("mean_pnl_proxy_5c"), g):
            return False
    return True


def verify_a1_calibration_health_no_numeric_leak(health: dict[str, Any]) -> bool:
    """
    Defensive check for A1 isotonic health: gated means/rates only when sample_gate passes.
    """
    for row in health.get("reliability_table") or []:
        g = row.get("sample_gate")
        if not _gate_ok_for_value(row.get("predicted_mean"), g):
            return False
        if not _gate_ok_for_value(row.get("observed_hit_rate"), g):
            return False
    for _key, row in (health.get("regime_reliability") or {}).items():
        g = row.get("sample_gate")
        if not _gate_ok_for_value(row.get("predicted_mean"), g):
            return False
        if not _gate_ok_for_value(row.get("observed_hit_rate"), g):
            return False
    agg = (health.get("sample_gates") or {}).get("aggregate_holdout")
    if not _gate_ok_for_value(health.get("ece"), agg):
        return False
    if not _gate_ok_for_value(health.get("brier_score"), agg):
        return False
    return True


def verify_phase4_no_numeric_leak(out: dict[str, Any]) -> bool:
    for _sig, row in out.get("decision_performance_from_log", {}).items():
        g = row.get("sample_gate")
        if not _gate_ok_for_value(row.get("mean_pnl_proxy"), g):
            return False
    mh = out.get("mhap_alignment") or {}
    if not _gate_ok_for_value(mh.get("aligned_mean_5c_pts"), mh.get("aligned_mean_gate")):
        return False
    if not _gate_ok_for_value(mh.get("misaligned_mean_5c_pts"), mh.get("misaligned_mean_gate")):
        return False
    bl = out.get("baselines_from_snapshots") or {}
    if not _gate_ok_for_value(bl.get("always_up_mean_5c_pts"), bl.get("always_up_mean_gate")):
        return False
    if not _gate_ok_for_value(bl.get("always_down_mean_5c_pts"), bl.get("always_down_mean_gate")):
        return False
    if not _gate_ok_for_value(
        bl.get("vwap_side_mean_reversion_proxy_mean"), bl.get("vwap_mr_proxy_gate")
    ):
        return False
    comp = bl.get("decision_log_vs_baseline_comparison") or {}
    delta = comp.get("delta_log_mean_minus_always_up_mean")
    if delta is not None and comp.get("status") != "ok":
        return False
    return True


_ANCHOR_RATE_GATE_PAIRS: tuple[tuple[str, str], ...] = (
    ("miss_rate", "miss_rate_sample_gate"),
    ("miss_rate_authoritative_rule", "miss_rate_authoritative_rule_gate"),
    ("anchor_miss_rate_overall", "anchor_miss_rate_overall_gate"),
    ("fraction_trusted_without_anchor", "fraction_trusted_without_anchor_gate"),
)


def verify_anchor_audit_no_numeric_leak(out: dict[str, Any]) -> bool:
    """Defensive: no miss_rate / fraction fields without sufficient_sample on the paired gate."""

    def walk(node: Any) -> bool:
        if isinstance(node, dict):
            for rk, gk in _ANCHOR_RATE_GATE_PAIRS:
                if rk in node and not _gate_ok_for_value(node.get(rk), node.get(gk)):
                    return False
            for v in node.values():
                if not walk(v):
                    return False
        elif isinstance(node, list):
            for x in node:
                if not walk(x):
                    return False
        return True

    return walk(out)


def verify_payload_audit_no_numeric_leak(out: dict[str, Any]) -> bool:
    if not _gate_ok_for_value(
        out.get("snapshot_exact_ts_match_rate"), out.get("snapshot_exact_ts_match_rate_gate")
    ):
        return False
    snap = out.get("snapshot_nearest_abs_delta_sec") or {}
    g = snap.get("distribution_sample_gate")
    for k in ("min", "median", "max"):
        if not _gate_ok_for_value(snap.get(k), g):
            return False
    return True


def verify_audit_phase1_no_numeric_leak(out: dict[str, Any]) -> bool:
    """Gap stats, alignment fraction, outcome null rates, structural null rates — all gated."""

    def walk_gap_seconds(obj: Any) -> bool:
        if isinstance(obj, dict):
            gs = obj.get("gap_seconds")
            if isinstance(gs, dict):
                gg = gs.get("distribution_sample_gate")
                for k in ("median", "p95", "max"):
                    if not _gate_ok_for_value(gs.get(k), gg):
                        return False
            for v in obj.values():
                if not walk_gap_seconds(v):
                    return False
        elif isinstance(obj, list):
            for x in obj:
                if not walk_gap_seconds(x):
                    return False
        return True

    if not walk_gap_seconds(out.get("gap_continuity_snapshots_1m")):
        return False
    if not walk_gap_seconds(out.get("gap_continuity_price_bars_1m")):
        return False

    sba = out.get("snapshot_bar_alignment") or {}
    if not _gate_ok_for_value(
        sba.get("fraction_missing_anchor"), sba.get("fraction_missing_anchor_gate")
    ):
        return False

    oi = out.get("outcome_label_integrity") or {}
    nr_g = oi.get("null_rates_sample_gate")
    nr = oi.get("null_rates") or {}
    for k in ("outcome_1c", "outcome_5c", "outcome_15c", "outcome_60c"):
        if not _gate_ok_for_value(nr.get(k), nr_g):
            return False

    sc = out.get("structural_field_completeness") or {}
    sg = sc.get("structural_null_rates_sample_gate")
    if not _gate_ok_for_value(sc.get("zone_null_rate"), sg):
        return False
    if not _gate_ok_for_value(sc.get("vwap_side_null_rate"), sg):
        return False

    return True
