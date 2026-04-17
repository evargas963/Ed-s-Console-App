#!/usr/bin/env python3
"""
Profile full-stack runtime for compute_signals (single process; profiler-only patches).

Patches timing wrappers onto stack entrypoints and orchestration helpers, then runs N iterations.
Patch order: core ML/fusion modules first, then signals-local functions (import signals inside
_apply_patches so wrappers bind before compute_signals runs).

Reports:
  - Aggregate (main stack): inference, overlay, xgb pre, RBM, MC, fuse, prediction core/enrich, call
  - Unaccounted breakdown: regime/rules, signal layer, MC context, fusion cache, shared sequence,
    fusion policy columns, MH bundle, MH synthesis, canonical forecast, snapshot, calibration, etc.
  - Nested: inference_snapshot_v1_to_engineering_snapshot as %% of run_base_models_once (not additive)

Usage:
  python tools/profile_full_stack_runtime.py
  python tools/profile_full_stack_runtime.py --ticker SPY --iterations 15 --csv stack_profile.csv
"""

from __future__ import annotations

import argparse
import csv
import functools
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

# Repo root (parent of tools/)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def _hz() -> str:
    try:
        from ml_predict import get_ml_infer_horizon_slug

        return get_ml_infer_horizon_slug() or "?"
    except Exception:
        return "?"


class StackProfile:
    """Accumulates wall times and call counts; per-horizon for governed-slug-scoped calls."""

    def __init__(self) -> None:
        self.totals: dict[str, float] = defaultdict(float)
        self.counts: dict[str, int] = defaultdict(int)
        # by_horizon[hz][component] -> seconds
        self.by_horizon: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.by_horizon_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def add(self, key: str, dt: float, *, horizon: str | None = None) -> None:
        self.totals[key] += dt
        self.counts[key] += 1
        if horizon is not None:
            self.by_horizon[horizon][key] += dt
            self.by_horizon_counts[horizon][key] += 1


def _wrap(
    orig: Callable[..., Any],
    key: str,
    stats: StackProfile,
    *,
    horizon: bool = False,
) -> Callable[..., Any]:
    @functools.wraps(orig)
    def wrapped(*a: Any, **kw: Any) -> Any:
        t0 = time.perf_counter()
        try:
            return orig(*a, **kw)
        finally:
            hz = _hz() if horizon else None
            stats.add(key, time.perf_counter() - t0, horizon=hz)

    return wrapped


def _apply_patches(stats: StackProfile) -> dict[str, Any]:
    """Patch modules; return dict of original callables for optional restore."""
    import bayesian_fusion
    import call_engine
    import ml_predict
    import monte_carlo
    import prediction_engine
    import regime_engine
    import rules_engine
    import volatility_regime

    import multi_horizon_decision
    import multi_horizon_ml_bundle

    from features import inference_snapshot as inf_snap
    from features import fusion_policy_contract as fusion_policy_contract
    from features import monte_carlo_stack_input as mc_stack
    from features import shared_sequence_context as shared_seq
    from features import signal_layer_v1 as signal_layer_v1
    from features import xgb_model_input as xgb_model_input

    import mc_fusion_adjustment

    originals: dict[str, Any] = {}

    def _patch(mod: Any, name: str, key: str, *, horizon: bool = False) -> None:
        full = f"{mod.__name__}.{name}"
        originals[full] = getattr(mod, name)
        setattr(mod, name, _wrap(getattr(mod, name), key, stats, horizon=horizon))

    _patch(inf_snap, "build_inference_snapshot_v1_from_signal_input", "build_inference_snapshot_v1")
    _patch(prediction_engine, "build_fusion_model_overlay_for_stack", "build_fusion_model_overlay_for_stack")
    _patch(ml_predict, "build_xgb_pre_engineering_snapshot_for_tick", "build_xgb_pre_engineering_snapshot_for_tick")
    _patch(ml_predict, "run_base_models_once", "run_base_models_once", horizon=True)
    _patch(ml_predict, "_predict_xgb", "run_base_models_once.xgb", horizon=True)
    _patch(ml_predict, "_predict_lstm", "run_base_models_once.lstm", horizon=True)
    _patch(ml_predict, "_predict_transformer", "run_base_models_once.transformer", horizon=True)
    _patch(monte_carlo, "simulate", "monte_carlo.simulate", horizon=True)
    _patch(bayesian_fusion, "fuse", "bayesian_fusion.fuse", horizon=True)
    _patch(prediction_engine, "compute_prediction_core", "compute_prediction_core")
    _patch(prediction_engine, "compute_prediction_enrichment", "compute_prediction_enrichment")
    _patch(call_engine, "compute_call", "compute_call")

    # Feature transform (nested under run_base_models_once — reported separately, not additive to iteration %)
    _patch(
        xgb_model_input,
        "inference_snapshot_v1_to_engineering_snapshot",
        "inference_snapshot_v1_to_engineering_snapshot",
    )

    # Regime + rules (orchestration — exclusive segments)
    _patch(volatility_regime, "classify_volatility_regime", "classify_volatility_regime")
    _patch(rules_engine, "compute_rules", "compute_rules")
    _patch(regime_engine, "classify_regime", "classify_regime")

    _patch(signal_layer_v1, "compute_signal_layer_v1_for_calibration", "compute_signal_layer_v1_for_calibration")
    _patch(mc_stack, "resolve_monte_carlo_stack_inputs", "resolve_monte_carlo_stack_inputs")
    _patch(bayesian_fusion, "build_fusion_tick_cache", "build_fusion_tick_cache")
    _patch(shared_seq, "build_shared_sequence_context", "build_shared_sequence_context")
    _patch(fusion_policy_contract, "fusion_payload_to_policy_columns", "fusion_payload_to_policy_columns")
    _patch(mc_fusion_adjustment, "fuse_payload_apply_mc_adjustment", "fuse_payload_apply_mc_adjustment")

    _patch(multi_horizon_ml_bundle, "build_multi_horizon_ml_fusion_bundle", "build_multi_horizon_ml_fusion_bundle")
    _patch(multi_horizon_decision, "compute_multi_horizon_synthesis", "compute_multi_horizon_synthesis")
    _patch(multi_horizon_decision, "finalize_multi_horizon_bundle", "finalize_multi_horizon_bundle")

    # signals.* — import signals after stack modules are patched
    import signals as signals_mod

    _patch(signals_mod, "canonical_forecast_from_fusion", "canonical_forecast_from_fusion")
    _patch(signals_mod, "_build_stack_decision_path", "signals._build_stack_decision_path")
    _patch(signals_mod, "_build_snapshot_dict", "signals._build_snapshot_dict")
    _patch(signals_mod, "_maybe_append_calibration_log", "signals._maybe_append_calibration_log")

    return originals


def _restore(originals: dict[str, Any]) -> None:
    import bayesian_fusion
    import call_engine
    import ml_predict
    import monte_carlo
    import prediction_engine
    import regime_engine
    import rules_engine
    import volatility_regime

    import multi_horizon_decision
    import multi_horizon_ml_bundle

    from features import inference_snapshot as inf_snap
    from features import fusion_policy_contract as fusion_policy_contract
    from features import monte_carlo_stack_input as mc_stack
    from features import shared_sequence_context as shared_seq
    from features import signal_layer_v1 as signal_layer_v1
    from features import xgb_model_input as xgb_model_input

    import mc_fusion_adjustment
    import signals as signals_mod

    mapping = [
        (inf_snap, "build_inference_snapshot_v1_from_signal_input"),
        (prediction_engine, "build_fusion_model_overlay_for_stack"),
        (ml_predict, "build_xgb_pre_engineering_snapshot_for_tick"),
        (ml_predict, "run_base_models_once"),
        (ml_predict, "_predict_xgb"),
        (ml_predict, "_predict_lstm"),
        (ml_predict, "_predict_transformer"),
        (monte_carlo, "simulate"),
        (bayesian_fusion, "fuse"),
        (prediction_engine, "compute_prediction_core"),
        (prediction_engine, "compute_prediction_enrichment"),
        (call_engine, "compute_call"),
        (xgb_model_input, "inference_snapshot_v1_to_engineering_snapshot"),
        (volatility_regime, "classify_volatility_regime"),
        (rules_engine, "compute_rules"),
        (regime_engine, "classify_regime"),
        (signal_layer_v1, "compute_signal_layer_v1_for_calibration"),
        (mc_stack, "resolve_monte_carlo_stack_inputs"),
        (bayesian_fusion, "build_fusion_tick_cache"),
        (shared_seq, "build_shared_sequence_context"),
        (fusion_policy_contract, "fusion_payload_to_policy_columns"),
        (mc_fusion_adjustment, "fuse_payload_apply_mc_adjustment"),
        (multi_horizon_ml_bundle, "build_multi_horizon_ml_fusion_bundle"),
        (multi_horizon_decision, "compute_multi_horizon_synthesis"),
        (multi_horizon_decision, "finalize_multi_horizon_bundle"),
        (signals_mod, "canonical_forecast_from_fusion"),
        (signals_mod, "_build_stack_decision_path"),
        (signals_mod, "_build_snapshot_dict"),
        (signals_mod, "_maybe_append_calibration_log"),
    ]
    for mod, name in mapping:
        full = f"{mod.__name__}.{name}"
        if full in originals:
            setattr(mod, name, originals[full])


def _default_signal_input(ticker: str):
    from signal_types import SignalInput

    return SignalInput(
        ticker=ticker,
        timeframe="1m",
        expiry=None,
        dte=None,
        spot=450.0,
        candle_open=449.5,
        candle_high=450.2,
        candle_low=449.3,
        candle_close=450.0,
        candle_direction="up",
        candle_body_pts=0.5,
        candle_range_pts=0.9,
        vwap=449.8,
        vwap_side="above",
        vwap_dist_pts=0.2,
        zone="pin_bull",
        prev_zone="pin_bull",
        zone_since_bars=5,
        zone_since_bars_1m=5,
        zone_since_bars_5m=1,
        call_gamma_wall=452.0,
        put_gamma_wall=448.0,
        call_delta_wall=None,
        put_delta_wall=None,
        gamma_inflection=None,
        delta_inflection=None,
        call_oi_wall=None,
        put_oi_wall=None,
        call_vanna_wall=None,
        put_vanna_wall=None,
        pin_width_pts=2.0,
        dist_call_gamma_wall=2.0,
        dist_put_gamma_wall=-2.0,
        dist_call_delta_wall=None,
        dist_put_delta_wall=None,
        dist_gamma_inflection=None,
        dist_delta_inflection=None,
        dist_call_oi_wall=None,
        dist_put_oi_wall=None,
        dist_call_vanna_wall=None,
        dist_put_vanna_wall=None,
        nearest_above_name="CGW",
        nearest_above_val=452.0,
        nearest_above_dist=2.0,
        nearest_below_name="PGW",
        nearest_below_val=448.0,
        nearest_below_dist=2.0,
        net_gamma=1000.0,
        net_delta=200.0,
        net_vanna=None,
        charm_net=None,
        charm_direction="neutral",
        charm_drift_toward=450.0,
        charm_magnitude="moderate",
        dex_magnitude="moderate",
        iv_level=0.15,
        iv_direction="flat",
        realized_vol=None,
        atr=1.5,
        put_call_oi_ratio=1.0,
        oi_center=None,
        recent_crosses=[],
        ceiling_tests_today=0,
        floor_tests_today=0,
        spy_chg_pct=0.05,
        qqq_chg_pct=0.04,
        iwm_chg_pct=0.03,
        vix_level=18.0,
        mins_to_close=240.0,
        em_upper=452.0,
        em_lower=448.0,
        order_flow_score=0.0,
        order_flow_direction="neutral",
        order_flow_readiness="yellow",
    )


def _print_table(title: str, rows: list[tuple[str, float, float, int]]) -> None:
    print(title)
    print(f"{'Component':<48} {'Avg ms':>12} {'% iter':>10} {'Calls':>8}")
    print("-" * 82)
    for name, avg_ms, pct, n in rows:
        print(f"{name:<48} {avg_ms:>12.3f} {pct:>9.1f}% {n:>8d}")


def _write_csv(path: Path, rows: list[tuple[str, float, float, int]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "component",
                "avg_ms_per_iteration",
                "pct",
                "calls",
                "pct_interpretation",
            ]
        )
        w.writerow(
            [
                "",
                "",
                "",
                "",
                "top rows: pct of total iteration wall; "
                "breakdown rows: pct of run_base_models_once only",
            ]
        )
        for name, avg_ms, pct, n in rows:
            w.writerow([name, f"{avg_ms:.6f}", f"{pct:.4f}", n, ""])


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile compute_signals full stack runtime.")
    parser.add_argument("--ticker", default="SPY", help="Ticker symbol (default SPY)")
    parser.add_argument("--iterations", type=int, default=15, help="Number of compute_signals runs (default 15)")
    parser.add_argument("--csv", type=str, default="", help="Optional path to write component summary CSV")
    args = parser.parse_args()

    from ml_horizon import ALL_GOVERNED_HORIZONS, PRIMARY_DECISION_HORIZONS, SECONDARY_SUPPORT_HORIZONS

    n_iter = max(1, args.iterations)
    ticker = (args.ticker or "SPY").upper().strip()

    # Patch once before signals import so `from prediction_engine import compute_prediction` etc. bind to wrappers.
    agg = StackProfile()
    originals = _apply_patches(agg)

    try:
        import signals  # noqa: WPS433 — after patches

        from db import get_db

        inp = _default_signal_input(ticker)
        inp.ticker = ticker

        db = get_db()

        iteration_totals: list[float] = []

        for _ in range(n_iter):
            t0 = time.perf_counter()
            signals.compute_signals(inp, db=db)
            iteration_totals.append(time.perf_counter() - t0)

        sum_iter = sum(iteration_totals)
        avg_iter = sum_iter / n_iter

        print()
        print("=" * 82)
        print(f"FULL STACK RUNTIME PROFILE  ticker={ticker}  iterations={n_iter}")
        print("=" * 82)
        print(f"Horizon contract: ALL_GOVERNED={len(ALL_GOVERNED_HORIZONS)}  PRIMARY={len(PRIMARY_DECISION_HORIZONS)}  SECONDARY={len(SECONDARY_SUPPORT_HORIZONS)}")
        print(f"  ALL_GOVERNED_HORIZONS: {ALL_GOVERNED_HORIZONS}")
        print(f"  PRIMARY_DECISION_HORIZONS: {PRIMARY_DECISION_HORIZONS}")
        print(f"  SECONDARY_SUPPORT_HORIZONS: {SECONDARY_SUPPORT_HORIZONS}")
        print()
        print(f"Mean iteration wall time: {avg_iter * 1000:.2f} ms  (min {min(iteration_totals)*1000:.2f}  max {max(iteration_totals)*1000:.2f})")
        print()

        # Primary stack: mutually exclusive top-level segments (no nesting between these keys).
        main_stack_keys = [
            "build_inference_snapshot_v1",
            "build_fusion_model_overlay_for_stack",
            "build_xgb_pre_engineering_snapshot_for_tick",
            "run_base_models_once",
            "monte_carlo.simulate",
            "bayesian_fusion.fuse",
            "compute_prediction_core",
            "compute_prediction_enrichment",
            "compute_call",
        ]
        orchestration_keys = [
            "classify_volatility_regime",
            "compute_rules",
            "classify_regime",
            "compute_signal_layer_v1_for_calibration",
            "resolve_monte_carlo_stack_inputs",
            "build_fusion_tick_cache",
            "build_shared_sequence_context",
            "fusion_payload_to_policy_columns",
            "fuse_payload_apply_mc_adjustment",
            "build_multi_horizon_ml_fusion_bundle",
            "canonical_forecast_from_fusion",
            "compute_multi_horizon_synthesis",
            "finalize_multi_horizon_bundle",
            "signals._build_stack_decision_path",
            "signals._build_snapshot_dict",
            "signals._maybe_append_calibration_log",
        ]

        summary_rows: list[tuple[str, float, float, int]] = []
        for key in main_stack_keys:
            total_t = agg.totals.get(key, 0.0)
            cnt = agg.counts.get(key, 0)
            avg_ms = (total_t / n_iter) * 1000.0
            pct = (total_t / sum_iter * 100.0) if sum_iter > 0 else 0.0
            summary_rows.append((key, avg_ms, pct, cnt))

        rbm_t = agg.totals.get("run_base_models_once", 0.0)
        sub_keys = [
            ("run_base_models_once.xgb", "  (breakdown) xgb"),
            ("run_base_models_once.lstm", "  (breakdown) lstm"),
            ("run_base_models_once.transformer", "  (breakdown) transformer"),
        ]
        for sk, label in sub_keys:
            total_t = agg.totals.get(sk, 0.0)
            cnt = agg.counts.get(sk, 0)
            avg_ms = (total_t / n_iter) * 1000.0
            pct_of_parent = (total_t / rbm_t * 100.0) if rbm_t > 0 else 0.0
            summary_rows.append((f"{label} [% of run_base_models_once time]", avg_ms, pct_of_parent, cnt))

        accounted_main = sum(agg.totals.get(k, 0.0) for k in main_stack_keys)
        accounted_orch = sum(agg.totals.get(k, 0.0) for k in orchestration_keys)
        accounted_additive = accounted_main + accounted_orch
        unacc = max(0.0, sum_iter - accounted_additive)
        summary_rows.append(
            (
                "(residual unaccounted: overhead + unpatched glue)",
                (unacc / n_iter) * 1000.0,
                (unacc / sum_iter * 100.0) if sum_iter > 0 else 0.0,
                n_iter,
            )
        )

        print(
            "Aggregate (main stack) - avg ms per iteration; top rows: % of total wall time; "
            "xgb/lstm/tr rows: % of run_base_models_once only (not additive to iteration %)."
        )
        _print_table("", summary_rows)

        print()
        print("Unaccounted breakdown - explicit orchestration (avg ms per iteration; % of total wall; additive)")
        print("(Sibling slices of the same iteration; listed separately from main stack for visibility.)")
        orch_rows: list[tuple[str, float, float, int]] = []
        for key in orchestration_keys:
            total_t = agg.totals.get(key, 0.0)
            cnt = agg.counts.get(key, 0)
            avg_ms = (total_t / n_iter) * 1000.0
            pct = (total_t / sum_iter * 100.0) if sum_iter > 0 else 0.0
            orch_rows.append((key, avg_ms, pct, cnt))
        orch_rows.append(
            (
                "(sum of orchestration + main stack vs iteration)",
                (accounted_additive / n_iter) * 1000.0,
                (accounted_additive / sum_iter * 100.0) if sum_iter > 0 else 0.0,
                n_iter,
            )
        )
        orch_rows.append(
            (
                "(residual after main + orchestration)",
                (unacc / n_iter) * 1000.0,
                (unacc / sum_iter * 100.0) if sum_iter > 0 else 0.0,
                n_iter,
            )
        )
        _print_table("", orch_rows)

        print()
        print("Nested under run_base_models_once (NOT additive to iteration % - subset of RBM time)")
        eng_t = agg.totals.get("inference_snapshot_v1_to_engineering_snapshot", 0.0)
        eng_cnt = agg.counts.get("inference_snapshot_v1_to_engineering_snapshot", 0)
        eng_avg_ms = (eng_t / n_iter) * 1000.0
        eng_pct_rbm = (eng_t / rbm_t * 100.0) if rbm_t > 0 else 0.0
        print(
            f"{'inference_snapshot_v1_to_engineering_snapshot':<48} {eng_avg_ms:>12.3f} "
            f"{eng_pct_rbm:>9.1f}% {eng_cnt:>8d}  (% of run_base_models_once only)"
        )

        print()
        print("Call count verification (expect run_base_models_once / MC / fuse == "
              f"{len(ALL_GOVERNED_HORIZONS)} * iterations = {len(ALL_GOVERNED_HORIZONS) * n_iter} if every horizon completes):")
        for key in ("run_base_models_once", "monte_carlo.simulate", "bayesian_fusion.fuse"):
            print(f"  {key}: {agg.counts.get(key, 0)}")
        print()

        # Per-horizon table
        hz_order = list(ALL_GOVERNED_HORIZONS)
        hz_keys = [
            "run_base_models_once",
            "run_base_models_once.xgb",
            "run_base_models_once.lstm",
            "run_base_models_once.transformer",
            "monte_carlo.simulate",
            "bayesian_fusion.fuse",
        ]
        col_headers = ["rbm", "rbm.xgb", "rbm.lstm", "rbm.tr", "mc.sim", "fuse"]
        print("Per-horizon - avg ms per iteration (one governed slug column set per iteration)")
        print(f"{'Hz':<6}", end="")
        for ch in col_headers:
            print(f"{ch:>14}", end=" ")
        print()
        print("-" * (6 + 15 * len(col_headers)))
        for hz in hz_order:
            print(f"{hz:<6}", end="")
            for hk in hz_keys:
                total_t = agg.by_horizon.get(hz, {}).get(hk, 0.0)
                avg_ms = (total_t / n_iter) * 1000.0
                print(f"{avg_ms:>14.2f}", end=" ")
            print()

        print()
        hz_slice_keys = ["run_base_models_once", "monte_carlo.simulate", "bayesian_fusion.fuse"]
        print("Per-horizon % of total iteration wall (rbm + mc.sim + fuse only; no double-count):")
        for hz in hz_order:
            slice_t = sum(agg.by_horizon.get(hz, {}).get(hk, 0.0) for hk in hz_slice_keys)
            pct = (slice_t / sum_iter * 100.0) if sum_iter > 0 else 0.0
            tier = "PRIMARY" if hz in PRIMARY_DECISION_HORIZONS else "SECONDARY"
            print(f"  {hz} ({tier}): {pct:.1f}%")

        if args.csv:
            out = Path(args.csv)
            _write_csv(out, summary_rows)
            with out.open("a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([])
                w.writerow(["# section", "unaccounted_breakdown"])
                w.writerow(["component", "avg_ms_per_iteration", "pct_total_wall", "calls", ""])
                for name, avg_ms, pct, n in orch_rows:
                    w.writerow([name, f"{avg_ms:.6f}", f"{pct:.4f}", n, "pct of iteration wall"])
                w.writerow([])
                w.writerow(
                    [
                        "inference_snapshot_v1_to_engineering_snapshot",
                        f"{(eng_t / n_iter) * 1000.0:.6f}",
                        f"{eng_pct_rbm:.4f}",
                        eng_cnt,
                        "pct of run_base_models_once only (nested)",
                    ]
                )
            print()
            print(f"Wrote CSV: {out.resolve()}")

    finally:
        _restore(originals)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
