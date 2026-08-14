"""Mega 2 traceable inventory (§D+§E) — KEY LEVELS math + order flow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Mega2Disposition = Literal["SCHWAB_LEAF", "REPLACED", "DERIVED", "ALLOWLISTED", "NONE"]


@dataclass(frozen=True)
class Mega2TraceableDerivation:
    file: str
    line: int
    derivation: str
    disposition: Mega2Disposition
    schwab_leaf: str | None
    producer_refs: tuple[str, ...]
    allowlist_id: str | None
    justification: str


MEGA2_FILES = frozenset(
    {
        "debug_flow_snapshot.py",
        "levels.py",
        "math_exposure.py",
        "math_exposure_core.py",
        "math_levels.py",
        "math_probabilities.py",
        "math_volatility.py",
        "order_flow_engine.py",
        "order_flow_live_state.py",
        "order_flow_streaming.py",
    }
)

# Engines that are not Mega2 KEY-LEVELS / order-flow producers. Named so a new
# *_engine.py cannot land uninventoried by hiding next to these.
MEGA2_ENGINE_OUT_OF_SCOPE = frozenset(
    {
        "adaptive_similarity_engine.py",
        "arch_competition/promotion_engine.py",
        "call_engine.py",
        "liquidity_value_engine.py",
        "prediction_engine.py",
        "regime_engine.py",
        "rules_engine.py",
    }
)


# Token, not the cited suffix: engine_core.py and terrain_engine.py are the
# same class. signal_engineering.py is not (engine is not a path token).
_ENGINE_FILENAME_TOKEN = re.compile(r"(^|_)engine(\.|_|$)")


def uninventoried_engine_modules(
    repo_files: list[str],
    mega2_files: frozenset[str] = MEGA2_FILES,
    out_of_scope: frozenset[str] = MEGA2_ENGINE_OUT_OF_SCOPE,
) -> list[str]:
    """RC-297: any module whose filename contains an `engine` token, uninventoried."""
    from pathlib import Path

    offenders: list[str] = []
    for rel in repo_files:
        if rel.startswith("tests/"):
            continue
        name = Path(rel).name
        if _ENGINE_FILENAME_TOKEN.search(name):
            if rel not in mega2_files and rel not in out_of_scope:
                offenders.append(rel)
    return sorted(offenders)

MEGA2_TRACEABLE_INVENTORY: tuple[Mega2TraceableDerivation, ...] = (
    Mega2TraceableDerivation("debug_flow_snapshot.py", 32, "_contracts_from_chain_json", "SCHWAB_LEAF", 'chains.callExpDateMap.*.openInterest', (), None, "Parses option chain JSON for debug snapshot."),
    Mega2TraceableDerivation("debug_flow_snapshot.py", 63, "main", "NONE", None, (), None, "No market-field derivation: CLI debug entry; reads persisted snapshots."),
    Mega2TraceableDerivation("levels.py", 22, "_fmt_level", "NONE", None, (), None, "No market-field derivation in _fmt_level; Level formatter."),
    Mega2TraceableDerivation("levels.py", 28, "_fmt_plain_2", "NONE", None, (), None, "No market-field derivation: Plain number formatter."),
    Mega2TraceableDerivation("levels.py", 34, "to_display_rows", "ALLOWLISTED", None, (), 'mega2_display_formatter', "ALLOWLISTED for to_display_rows: Display mapping only."),
    Mega2TraceableDerivation("levels.py", 56, "walls_to_df_rows", "ALLOWLISTED", None, (), 'mega2_display_formatter', "Walls display mapping."),
    Mega2TraceableDerivation("levels.py", 91, "totals_to_df_rows", "ALLOWLISTED", None, (), 'mega2_display_formatter', "Totals display mapping."),
    Mega2TraceableDerivation("levels.py", 118, "key_levels_to_plot_rows", "ALLOWLISTED", None, (), 'mega2_internal_helper', "Plot row formatter; no derivation."),
    Mega2TraceableDerivation("levels.py", 147, "key_levels_to_plot_rows._sr", "NONE", None, (), None, "No market-field derivation: Nested helper inside key_levels_to_plot_rows; parent row owns derivation semantics."),
    Mega2TraceableDerivation("levels.py", 190, "key_levels_to_plot_rows._oe_flag", "NONE", None, (), None, "No market-field derivation: Nested helper inside key_levels_to_plot_rows; parent row owns derivation semantics."),
    Mega2TraceableDerivation("levels.py", 198, "key_levels_to_plot_rows._row", "NONE", None, (), None, "No market-field derivation: Nested helper inside key_levels_to_plot_rows; parent row owns derivation semantics."),
    Mega2TraceableDerivation("math_exposure.py", 52, "_of_sign", "NONE", None, (), None, "No market-field derivation: Sign helper on order-flow scalar."),
    Mega2TraceableDerivation("math_exposure.py", 63, "_of_direction", "NONE", None, (), None, "No market-field derivation: Direction label from scalar."),
    Mega2TraceableDerivation("math_exposure.py", 78, "_verdict_unavailable", "NONE", None, (), None, "No market-field derivation: Unavailable verdict template for fail-closed OF path."),
    Mega2TraceableDerivation("math_exposure.py", 78, "compute_order_flow_verdict", "DERIVED", None, ("server.py:_fetch_state",), None, "Composite verdict; inputs must be Schwab-first from OF engine."),
    Mega2TraceableDerivation("math_exposure.py", 140, "_book_direction", "NONE", None, (), None, "No market-field derivation: Book imbalance label bands."),
    Mega2TraceableDerivation("math_exposure.py", 155, "order_flow_score_label", "NONE", None, (), None, "No market-field derivation: Display label for OF score."),
    Mega2TraceableDerivation("math_exposure.py", 161, "order_flow_book_label", "NONE", None, (), None, "No market-field derivation: Display label for book imbalance."),
    Mega2TraceableDerivation("math_exposure.py", 176, "order_flow_opt_label", "NONE", None, (), None, "No market-field derivation: Display label for option flow."),
    Mega2TraceableDerivation("math_exposure.py", 191, "order_flow_field_arrow", "NONE", None, (), None, "No market-field derivation: UI arrow from signed field."),
    Mega2TraceableDerivation("math_exposure.py", 202, "fmt_money", "NONE", None, (), None, "No market-field derivation in fmt_money; Money formatter."),
    Mega2TraceableDerivation("math_exposure.py", 213, "fmt_money_gex", "NONE", None, (), None, "No market-field derivation: GEX money formatter."),
    Mega2TraceableDerivation("math_exposure_core.py", 20, "_f", "NONE", None, (), None, "No market-field derivation in _f; Safe float parse."),
    Mega2TraceableDerivation("math_exposure_core.py", 26, "charm_compute_unavailable_log_level", "NONE", None, (), None, "No market-field derivation: two-state charm withhold log level (quality-gate DEBUG, else WARNING)."),
    Mega2TraceableDerivation("math_exposure_core.py", 29, "bucket_metric", "DERIVED", None, ("server.py:_fetch_state",), None, "Fail-closed; no .get(k,0)."),
    Mega2TraceableDerivation("math_exposure_core.py", 36, "bucket_metric_abs", "DERIVED", None, ("math_exposure_core.py:bucket_metric",), None, "Abs of bucket_metric."),
    Mega2TraceableDerivation("math_exposure_core.py", 66, "_strike_bucket", "SCHWAB_LEAF", 'chains.callExpDateMap.*.openInterest', (), None, "Strike dict lookup."),
    Mega2TraceableDerivation("math_exposure_core.py", 102, "compute_exposures_by_strike", "DERIVED", None, ("server.py:_fetch_state",), None, "Core Schwab chain aggregation; skip -999 greeks."),
    Mega2TraceableDerivation("math_exposure_core.py", 255, "_nearest_strike", "SCHWAB_LEAF", 'chains.*.strikePrice', (), None, "ATM strike selection."),
    Mega2TraceableDerivation("math_exposure_core.py", 266, "_window_strikes", "SCHWAB_LEAF", 'chains.*.strikePrice', (), None, "Strike window filter."),
    Mega2TraceableDerivation("math_exposure_core.py", 282, "exposures_have_dollar_gex", "DERIVED", None, ("math_exposure_core.py:bucket_metric",), None, "Detects dollarized GEX availability."),
    Mega2TraceableDerivation("math_exposure_core.py", 292, "key_level_strikes_with_oi", "SCHWAB_LEAF", 'chains.*.openInterest', (), None, "Strikes with OI leaf."),
    Mega2TraceableDerivation("math_exposure_core.py", 305, "key_level_strikes_with_gamma", "SCHWAB_LEAF", 'chains.*.gamma', (), None, "Strikes with usable gamma."),
    Mega2TraceableDerivation("math_exposure_core.py", 321, "total_gex_dollars_at_strike", "DERIVED", None, ("math_exposure_core.py:bucket_metric_abs",), None, "Sum |call|+|put| GEX$."),
    Mega2TraceableDerivation("math_exposure_core.py", 333, "net_gex_dollars_at_strike", "DERIVED", None, ("math_exposure_core.py:bucket_metric",), None, "Net GEX$ at strike."),
    Mega2TraceableDerivation("math_exposure_core.py", 337, "total_gamma_raw_at_strike", "DERIVED", None, ("math_exposure_core.py:bucket_metric_abs",), None, "Raw gamma magnitude fallback."),
    Mega2TraceableDerivation("math_exposure_core.py", 348, "net_gamma_raw_at_strike", "DERIVED", None, ("math_exposure_core.py:bucket_metric",), None, "Raw net gamma."),
    Mega2TraceableDerivation("math_exposure_core.py", 352, "_pick_strike_max_metric", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Max-metric strike picker."),
    Mega2TraceableDerivation("math_exposure_core.py", 370, "pick_gamma_pin_strike", "DERIVED", None, ("math_exposure_core.py:exposures_have_dollar_gex", "math_exposure_core.py:_pick_strike_max_metric", "math_exposure_core.py:bucket_metric_abs",), None, "Institutional pin; no raw fallback when dollarized."),
    Mega2TraceableDerivation("math_exposure_core.py", 433, "gex_at_bound_pin_strike", "DERIVED", None, ("math_exposure_core.py:net_gex_dollars_at_strike", "math_exposure_core.py:net_gamma_raw_at_strike", "math_exposure_core.py:exposures_have_dollar_gex",), None, "|net GEX$| at bound pin for pin_score; not total-gamma / HVL."),
    Mega2TraceableDerivation("math_exposure_core.py", 393, "pick_hvl_strike", "DERIVED", None, ("math_exposure_core.py:exposures_have_dollar_gex", "math_exposure_core.py:_pick_strike_max_metric",), None, "High-vol level strike."),
    Mega2TraceableDerivation("math_exposure_core.py", 405, "pick_gamma_wall_strikes", "DERIVED", None, ("math_exposure_core.py:exposures_have_dollar_gex", "math_exposure_core.py:_pick_strike_max_metric", "math_exposure_core.py:bucket_metric_abs",), None, "Call/put gamma walls."),
    Mega2TraceableDerivation("math_exposure_core.py", 428, "pick_delta_wall_strikes", "DERIVED", None, ("math_exposure_core.py:exposures_have_dollar_gex", "math_exposure_core.py:_pick_strike_max_metric", "math_exposure_core.py:bucket_metric_abs",), None, "Call/put delta walls."),
    Mega2TraceableDerivation("math_exposure_core.py", 450, "aggregate_net_gex", "DERIVED", None, ("math_exposure_core.py:exposures_have_dollar_gex", "math_exposure_core.py:net_gamma_raw_at_strike", "math_exposure_core.py:net_gex_dollars_at_strike",), None, "Sum net_gex_1pct over strikes."),
    Mega2TraceableDerivation("math_exposure_core.py", 474, "aggregate_net_dex", "DERIVED", None, ("math_exposure_core.py:exposures_have_dollar_gex", "math_exposure_core.py:bucket_metric",), None, "Sum net_dex over strikes."),
    Mega2TraceableDerivation("math_exposure_core.py", 496, "gex_magnitude_label", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Label from GEX magnitude."),
    Mega2TraceableDerivation("math_exposure_core.py", 509, "gex_regime_label", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Regime label from sign of GEX."),
    Mega2TraceableDerivation("math_exposure_core.py", 517, "greeks_validity", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Validity gate on greek coverage."),
    Mega2TraceableDerivation("math_exposure_core.py", 531, "sanitize_dealer_metrics", "DERIVED", None, ("math_exposure_core.py:greeks_validity",), None, "Sanitize when greeks invalid."),
    Mega2TraceableDerivation("math_exposure_core.py", 541, "window_summary", "DERIVED", None, ("math_exposure_core.py:bucket_metric",), None, "Window-level DEX/GEX/OI summary."),
    Mega2TraceableDerivation("math_exposure_core.py", 567, "strike_agg", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Delegates to Schwab transport producers for strike_agg."),
    Mega2TraceableDerivation("math_exposure_core.py", 573, "compute_net_charm", "DERIVED", None, ("server.py:_fetch_state",), None, "Net charm from chain; Schwab charm leaf when present."),
    Mega2TraceableDerivation("math_exposure_core.py", 622, "compute_net_charm._resolve_T", "SCHWAB_LEAF", 'chains.*.daysToExpiration', (), None, "Nested DTE parse for charm window."),
    Mega2TraceableDerivation("math_exposure_core.py", 745, "greek_bias", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Bias string from greeks."),
    Mega2TraceableDerivation("math_exposure_core.py", 778, "compute_beta", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Beta from return series; inputs from Schwab candles."),
    Mega2TraceableDerivation("math_exposure_core.py", 820, "compute_beta_residual", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Residual vs SPY; quote-derived inputs."),
    Mega2TraceableDerivation("math_exposure_core.py", 830, "returns_from_candles", "SCHWAB_LEAF", 'pricehistory.candles.*.close', (), None, "Daily returns; datetime required (cross-section fix)."),
    Mega2TraceableDerivation("math_levels.py", 115, "_strike_total_oi", "NONE", None, (), None, "No market-field derivation: Both-leg OI gate for max pain / OI center."),
    Mega2TraceableDerivation("math_levels.py", 116, "_pick_gamma_pin", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Delegates pick_gamma_pin_strike."),
    Mega2TraceableDerivation("math_levels.py", 120, "_pick_oi_center", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "OI-weighted center."),
    Mega2TraceableDerivation("math_levels.py", 138, "_pick_inflection_closest_zero", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Zero-cross inflection picker."),
    Mega2TraceableDerivation("math_levels.py", 157, "_pin_strength", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Pin strength vs neighbors."),
    Mega2TraceableDerivation("math_levels.py", 194, "_bias_from_net", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Bias signal taxonomy."),
    Mega2TraceableDerivation("math_levels.py", 215, "build_summary_rows", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike", "market_state.py:build_market_state",), None, "KEY LEVELS summary table rows."),
    Mega2TraceableDerivation("math_levels.py", 231, "build_summary_rows.aggregate", "DERIVED", None, ("math_levels.py:build_summary_rows",), None, "Nested strike-window aggregate inside build_summary_rows."),
    Mega2TraceableDerivation("math_levels.py", 289, "_pick_wall_abs", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Legacy abs wall picker."),
    Mega2TraceableDerivation("math_levels.py", 305, "_pick_wall_pos", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Positive-metric wall picker."),
    Mega2TraceableDerivation("math_levels.py", 324, "_dominant", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Dominant side selection."),
    Mega2TraceableDerivation("math_levels.py", 339, "build_walls_rows", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike", "market_state.py:build_market_state",), None, "Walls table for UI."),
    Mega2TraceableDerivation("math_levels.py", 353, "build_totals_rows.strikes_for", "DERIVED", None, ("math_levels.py:build_totals_rows",), None, "Nested strike list filter inside build_totals_rows."),
    Mega2TraceableDerivation("math_levels.py", 473, "build_totals_rows", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike",), None, "Totals table aggregation."),
    Mega2TraceableDerivation("math_levels.py", 486, "build_walls_rows.strikes_for", "DERIVED", None, ("math_levels.py:build_walls_rows",), None, "Nested strike list filter inside build_walls_rows."),
    Mega2TraceableDerivation("math_levels.py", 575, "is_pin_zone", "ALLOWLISTED", None, (), 'mega2_internal_helper', "Zone classifier constant check."),
    Mega2TraceableDerivation("math_levels.py", 581, "parity_f_minus_spot_from_contracts", "SCHWAB_LEAF", 'chains.callExpDateMap.*.mark', (), None, "Parity residual; mark-only mid per strike."),
    Mega2TraceableDerivation("math_levels.py", 618, "parity_f_minus_spot_from_contracts._mid", "SCHWAB_LEAF", 'chains.callExpDateMap.*.mark', (), None, "Nested mid from Schwab bid/ask/mark only."),
    Mega2TraceableDerivation("math_levels.py", 652, "compute_gamma_flip", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike",), None, "Zero-cross interpolation."),
    Mega2TraceableDerivation("math_levels.py", 675, "compute_gamma_flip._find_crossing", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike",), None, "Nested zero-cross search inside compute_gamma_flip."),
    Mega2TraceableDerivation("math_levels.py", 729, "_total_gamma_at_strike", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Total gamma measure at strike."),
    Mega2TraceableDerivation("math_levels.py", 737, "compute_hvl", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike", "market_state.py:build_market_state",), None, "Delegates pick_hvl_strike."),
    Mega2TraceableDerivation("math_levels.py", 750, "hvl_gamma_strength", "DERIVED", None, ("math_levels.py:_total_gamma_at_strike",), None, "Strength at HVL."),
    Mega2TraceableDerivation("math_levels.py", 762, "compute_max_pain", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike", "server.py:_fetch_state",), None, "Max pain from OI; no Schwab max-pain leaf."),
    Mega2TraceableDerivation("math_levels.py", 776, "compute_max_pain._pain_at", "DERIVED", None, ("math_levels.py:compute_max_pain",), None, "Nested pain calc at settlement inside compute_max_pain."),
    Mega2TraceableDerivation("math_levels.py", 806, "max_pain_oi_strength", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "OI at max pain strike."),
    Mega2TraceableDerivation("math_levels.py", 824, "compute_gamma_void_zones", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike",), None, "Delegates to Schwab transport producers for compute_gamma_void_zones."),
    Mega2TraceableDerivation("math_levels.py", 859, "compute_gamma_void_zones._get_gex", "DERIVED", None, ("math_levels.py:compute_gamma_void_zones",), None, "Nested GEX reader; parent REPLACED forbids or-zero synthesis."),
    Mega2TraceableDerivation("math_levels.py", 876, "compute_gamma_void_zones._get_oi", "DERIVED", None, ("math_levels.py:compute_gamma_void_zones",), None, "Nested OI reader inside compute_gamma_void_zones."),
    Mega2TraceableDerivation("math_levels.py", 976, "compute_level_density", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Density metric for level bands."),
    Mega2TraceableDerivation("math_probabilities.py", 85, "_oe_wall_consensus_row", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Delegates to Schwab transport producers for _oe_wall_consensus_row."),
    Mega2TraceableDerivation("math_probabilities.py", 95, "_wlevel", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Delegates to Schwab transport producers for _wlevel."),
    Mega2TraceableDerivation("math_probabilities.py", 102, "compute_wall_score_components", "DERIVED", None, ("math_probabilities.py:_oe_wall_consensus_row", "math_probabilities.py:_wlevel",), None, "Wall proximity scoring."),
    Mega2TraceableDerivation("math_probabilities.py", 176, "score_option_expression", "DERIVED", None, ("math_probabilities.py:compute_wall_score_components",), None, "OE score; spread from bid-ask pts only."),
    Mega2TraceableDerivation("math_probabilities.py", 269, "classify_direction", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Direction from move threshold."),
    Mega2TraceableDerivation("math_probabilities.py", 280, "classify_direction_pts", "NONE", None, (), None, "No market-field derivation: No Schwab market-field derivation in function body."),
    Mega2TraceableDerivation("math_probabilities.py", 283, "dist_bucket", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Distance bucket label."),
    Mega2TraceableDerivation("math_probabilities.py", 293, "bucket_lo", "ALLOWLISTED", None, (), 'mega2_internal_helper', "Bucket lower bound map."),
    Mega2TraceableDerivation("math_probabilities.py", 300, "bucket_hi", "ALLOWLISTED", None, (), 'mega2_internal_helper', "Bucket upper bound map."),
    Mega2TraceableDerivation("math_probabilities.py", 311, "compute_probs", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Historical outcome probabilities."),
    Mega2TraceableDerivation("math_probabilities.py", 335, "dominant_direction", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Dominant class from probs."),
    Mega2TraceableDerivation("math_probabilities.py", 343, "determine_confidence", "DERIVED", None, ("server.py:_fetch_state",), None, "Confidence label."),
    Mega2TraceableDerivation("math_probabilities.py", 382, "_binomial_p_value", "NONE", None, (), None, "No market-field derivation in _binomial_p_value; Stats helper."),
    Mega2TraceableDerivation("math_probabilities.py", 395, "compute_percentile_range", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Percentile band from history."),
    Mega2TraceableDerivation("math_probabilities.py", 408, "classify_reversal_risk", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Derived field logic for classify_reversal_risk."),
    Mega2TraceableDerivation("math_probabilities.py", 429, "compute_dealer_pressure_index", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "DPI composite."),
    Mega2TraceableDerivation("math_probabilities.py", 479, "compute_hedging_flow_score", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Hedging flow score."),
    Mega2TraceableDerivation("math_probabilities.py", 539, "compute_gamma_gradient", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "dGEX/dPrice near spot."),
    Mega2TraceableDerivation("math_probabilities.py", 589, "compute_breakout_score", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Breakout composite."),
    Mega2TraceableDerivation("math_probabilities.py", 640, "compute_pin_score", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Pin score from GEX."),
    Mega2TraceableDerivation("math_probabilities.py", 688, "compute_vol_expansion_signal", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Vol expansion signal."),
    Mega2TraceableDerivation("math_probabilities.py", 741, "compute_sweep_score", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Sweep detection score."),
    Mega2TraceableDerivation("math_probabilities.py", 796, "compute_sector_strength", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Sector strength from context quotes."),
    Mega2TraceableDerivation("math_probabilities.py", 831, "_sector_strength_unavailable", "NONE", None, (), None, "No market-field derivation: Unavailable sector strength template."),
    Mega2TraceableDerivation("math_probabilities.py", 848, "compute_iwm_confluence", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "IWM blended participation."),
    Mega2TraceableDerivation("math_probabilities.py", 883, "_iwm_confluence_unavailable", "NONE", None, (), None, "No market-field derivation: Unavailable IWM confluence template."),
    Mega2TraceableDerivation("math_probabilities.py", 1081, "compute_volume_oi_ratio", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Volume/OI per strike."),
    Mega2TraceableDerivation("math_probabilities.py", 1158, "compute_option_flow_imbalance", "SCHWAB_LEAF", 'chains.callExpDateMap.*.bidSize', (), None, "Bid/ask size imbalance from Schwab leaves."),
    Mega2TraceableDerivation("math_probabilities.py", 1237, "atm_flow_window_totals", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "ATM window flow totals."),
    Mega2TraceableDerivation("math_probabilities.py", 1300, "flow_imbalance_normalized_with_fallback", "DERIVED", None, ("math_probabilities.py:atm_flow_window_totals", "math_probabilities.py:compute_option_flow_imbalance",), None, "Normalized flow with explicit fallback policy."),
    Mega2TraceableDerivation("math_probabilities.py", 1336, "compute_smart_money_signal", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Fail-closed Schwab leaf read: chains.* volume,OI,bid/ask size."),
    Mega2TraceableDerivation("math_volatility.py", 34, "_spot_atm_strike", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "ATM strike from chain."),
    Mega2TraceableDerivation("math_volatility.py", 39, "_extract_iv_for_strike", "SCHWAB_LEAF", 'chains.*.volatility', (), None, "Mean call/put IV at strike; skip invalid."),
    Mega2TraceableDerivation("math_volatility.py", 65, "charm_intraday_context", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Banner from charm_result dict."),
    Mega2TraceableDerivation("math_volatility.py", 96, "session_bucket", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "No Schwab session_label leaf."),
    Mega2TraceableDerivation("math_volatility.py", 116, "vix_tier_token", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Canonical VIX tier token (15/20/30 cuts); shared authority for vix_bucket and L1 vol regime."),
    Mega2TraceableDerivation("math_volatility.py", 121, "compute_expected_move_straddle", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "EM from ATM marks; not single EM leaf."),
    Mega2TraceableDerivation("math_volatility.py", 141, "vix_bucket", "DERIVED", None, ("math_volatility.py:vix_tier_token",), None, "SignalInput vix_* label from vix_tier_token authority."),
    Mega2TraceableDerivation("math_volatility.py", 153, "compute_expected_move_iv", "DERIVED", None, ("market_state.py:build_market_state", "server.py:_fetch_state",), None, "EM from IV + time; IV from Schwab volatility leaf."),
    Mega2TraceableDerivation("math_volatility.py", 195, "resolve_kl_em_anchor", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Anchor policy for KL+MC alignment."),
    Mega2TraceableDerivation("math_volatility.py", 204, "iv_percent_from_em_pts", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Invert IV-EM formula."),
    Mega2TraceableDerivation("math_volatility.py", 216, "resolve_mc_iv_for_kl_em_anchor", "DERIVED", None, ("market_state.py:build_market_state",), None, "MC IV reconciled to KL anchor."),
    Mega2TraceableDerivation("math_volatility.py", 239, "compute_em_progress", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Progress through EM range."),
    Mega2TraceableDerivation("math_volatility.py", 286, "compute_iv_skew", "SCHWAB_LEAF", 'chains.*.volatility', (), None, "Put IV minus call IV at ATM."),
    Mega2TraceableDerivation("math_volatility.py", 346, "compute_realized_vol", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "RV from closes; Schwab OHLC input."),
    Mega2TraceableDerivation("math_volatility.py", 386, "compute_atr", "DERIVED", None, ("math_volatility.py:compute_atr._get",), None, "ATR from Schwab candles; skip incomplete bars."),
    Mega2TraceableDerivation("math_volatility.py", 403, "compute_atr._get", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Nested candle field reader inside compute_atr."),
    Mega2TraceableDerivation("math_volatility.py", 438, "compute_iv_rank", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "IV rank vs history series."),
    Mega2TraceableDerivation("math_volatility.py", 467, "compute_iv_percentile", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "IV percentile vs history."),
    Mega2TraceableDerivation("math_volatility.py", 494, "compute_volatility_envelope", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "ATR bands around spot."),
    Mega2TraceableDerivation("math_volatility.py", 571, "estimate_garch_params", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "GARCH param estimation from returns."),
    Mega2TraceableDerivation("math_volatility.py", 637, "compute_garch_forecast", "DERIVED", None, ("math_volatility.py:estimate_garch_params",), None, "Forward sigma from GARCH."),
    Mega2TraceableDerivation("math_volatility.py", 708, "blend_garch_sigma", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Blend GARCH+IV+RV per-bar sigma."),
    Mega2TraceableDerivation("math_volatility.py", 765, "compute_iv_model_spread", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Market vs model IV (OP-012)."),
    Mega2TraceableDerivation("order_flow_engine.py", 40, "_safe_float", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_safe_float)."),
    Mega2TraceableDerivation("order_flow_engine.py", 50, "_nonnegative_float", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_nonnegative_float)."),
    Mega2TraceableDerivation("order_flow_engine.py", 57, "_safe_int", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_safe_int)."),
    Mega2TraceableDerivation("order_flow_engine.py", 67, "_collect_from_nested", "NONE", None, (), None, "No market-field derivation: No Schwab market-field derivation in function body."),
    Mega2TraceableDerivation("order_flow_engine.py", 83, "_get_nested", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_get_nested)."),
    Mega2TraceableDerivation("order_flow_engine.py", 98, "_iter_content", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_iter_content)."),
    Mega2TraceableDerivation("order_flow_engine.py", 110, "_iter_bids_levels", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_iter_bids_levels)."),
    Mega2TraceableDerivation("order_flow_engine.py", 135, "_iter_asks_levels", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_iter_asks_levels)."),
    Mega2TraceableDerivation("order_flow_engine.py", 159, "_iter_tape_prints", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_iter_tape_prints)."),
    Mega2TraceableDerivation("order_flow_engine.py", 183, "_latest_book_snapshot", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_latest_book_snapshot)."),
    Mega2TraceableDerivation("order_flow_engine.py", 191, "_compute_book_imbalance", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_book_imbalance)."),
    Mega2TraceableDerivation("order_flow_engine.py", 216, "_latest_quote_snapshot", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_latest_quote_snapshot)."),
    Mega2TraceableDerivation("order_flow_engine.py", 224, "_compute_top_book_pressure", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_top_book_pressure)."),
    Mega2TraceableDerivation("order_flow_engine.py", 254, "_resolve_bid_ask_prices", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_resolve_bid_ask_prices)."),
    Mega2TraceableDerivation("order_flow_engine.py", 298, "_resolve_quote_mark", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_resolve_quote_mark)."),
    Mega2TraceableDerivation("order_flow_engine.py", 319, "_compute_spread", "DERIVED", None, ("order_flow_engine.py:_resolve_quote_mark",), None, "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_spread)."),
    Mega2TraceableDerivation("order_flow_engine.py", 356, "_compute_tape_pressure", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_tape_pressure)."),
    Mega2TraceableDerivation("order_flow_engine.py", 410, "_compute_cum_delta_proxy", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_cum_delta_proxy)."),
    Mega2TraceableDerivation("order_flow_engine.py", 442, "_compute_cum_delta_slope", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_cum_delta_slope)."),
    Mega2TraceableDerivation("order_flow_engine.py", 501, "_earliest_book_snapshot", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_earliest_book_snapshot)."),
    Mega2TraceableDerivation("order_flow_engine.py", 509, "_compute_absorption", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_absorption)."),
    Mega2TraceableDerivation("order_flow_engine.py", 545, "_iter_option_exp_levels", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_iter_option_exp_levels)."),
    Mega2TraceableDerivation("order_flow_engine.py", 606, "_option_contract_volume", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_option_contract_volume)."),
    Mega2TraceableDerivation("order_flow_engine.py", 619, "_compute_options_flow", "DERIVED", None, ("order_flow_engine.py:_iter_option_exp_levels", "order_flow_engine.py:_option_contract_volume",), None, "Options flow from chain/stream maps."),
    Mega2TraceableDerivation("order_flow_engine.py", 686, "_compute_rvol", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_rvol)."),
    Mega2TraceableDerivation("order_flow_engine.py", 740, "_compute_institutional_flow_proxy", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_institutional_flow_proxy)."),
    Mega2TraceableDerivation("order_flow_engine.py", 766, "_normalize", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_normalize)."),
    Mega2TraceableDerivation("order_flow_engine.py", 773, "_compute_order_flow_score", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_order_flow_score)."),
    Mega2TraceableDerivation("order_flow_engine.py", 799, "_weighted_mean_present", "DERIVED", None, ("order_flow_engine.py:OrderFlowEngine.compute",), None, "Composite mean over present legs only — derives order_flow composite from Schwab-derived inputs (_weighted_mean_present)."),
    Mega2TraceableDerivation("order_flow_engine.py", 802, "_direction", "NONE", None, (), None, "No market-field derivation: No Schwab market-field derivation in function body."),
    Mega2TraceableDerivation("order_flow_engine.py", 811, "_readiness", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_readiness)."),
    Mega2TraceableDerivation("order_flow_engine.py", 837, "OrderFlowEngine.compute", "DERIVED", None, ("order_flow_engine.py:_compute_order_flow_score", "order_flow_live_state.py:get_content_for_symbol",), None, "Public OF engine entry; composes sub-metrics."),
    Mega2TraceableDerivation("order_flow_engine.py", 992, "OrderFlowEngine._empty_result", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (OrderFlowEngine._empty_result)."),
    Mega2TraceableDerivation("order_flow_engine.py", 1046, "_mock_data", "ALLOWLISTED", None, (), 'mega2_test_fixture', "Order-flow metric from Schwab stream/quote fields."),
    Mega2TraceableDerivation("order_flow_engine.py", 1144, "_main", "NONE", None, (), None, "No market-field derivation: CLI/mock/diagnostic; no production derivation."),
    Mega2TraceableDerivation("order_flow_live_state.py", 33, "is_rth_open", "ALLOWLISTED", None, (), 'mega1_session_calendar', "No Schwab market-field derivation in function body."),
    Mega2TraceableDerivation("order_flow_live_state.py", 46, "_get_book", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_get_book)."),
    Mega2TraceableDerivation("order_flow_live_state.py", 53, "_get_tape", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_get_tape)."),
    Mega2TraceableDerivation("order_flow_live_state.py", 60, "push_book", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (push_book)."),
    Mega2TraceableDerivation("order_flow_live_state.py", 85, "push_level_one", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (push_level_one)."),
    Mega2TraceableDerivation("order_flow_live_state.py", 182, "get_content_for_symbol", "DERIVED", None, ("order_flow_live_state.py:push_level_one", "order_flow_live_state.py:push_book",), None, "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_content_for_symbol)."),
    Mega2TraceableDerivation("order_flow_live_state.py", 211, "get_l1_stream_input_probe", "ALLOWLISTED", None, (), 'mega1_l1_sse_counters', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_l1_stream_input_probe)."),
    Mega2TraceableDerivation("order_flow_live_state.py", 236, "clear_symbol", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (clear_symbol)."),
    Mega2TraceableDerivation("order_flow_live_state.py", 254, "get_stream_volume", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_stream_volume)."),
    Mega2TraceableDerivation("order_flow_live_state.py", 263, "get_stream_chg_pct", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_stream_chg_pct)."),
    Mega2TraceableDerivation("order_flow_live_state.py", 272, "get_top_of_book_sizes", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_top_of_book_sizes)."),
    Mega2TraceableDerivation("order_flow_live_state.py", 278, "get_top_of_book_sizes._to_int", "NONE", None, (), None, "No market-field derivation: Nested helper inside get_top_of_book_sizes; parent row owns derivation semantics."),
    Mega2TraceableDerivation("order_flow_live_state.py", 294, "get_stats", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_stats)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 60, "_log_stream", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_log_stream)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 68, "_streaming_healthy", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_streaming_healthy)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 79, "is_order_flow_stream_running", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (is_order_flow_stream_running)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 83, "get_plane_authority_for_ticker", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_plane_authority_for_ticker)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 101, "streaming_l1_cache_usable", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Fast-quote gate: plane row fresh within FAST_QUOTE_STREAM_CACHE_MAX_AGE_MS (streaming_l1_cache_usable)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 116, "_is_stream_disconnect_error", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Classify websocket close so message loop exits cleanly (_is_stream_disconnect_error)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 122, "_stale_bucket", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_stale_bucket)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 137, "_diag_on_active_l1_tick", "ALLOWLISTED", None, (), 'mega1_l1_sse_counters', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_diag_on_active_l1_tick)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 153, "_async_staleness_watch", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_async_staleness_watch)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 185, "get_streaming_diagnostics", "ALLOWLISTED", None, (), 'mega1_diagnostic_log', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_streaming_diagnostics)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 205, "_resubscribe_to_ticker", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_resubscribe_to_ticker)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 233, "_resubscribe_coro", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_resubscribe_coro)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 246, "set_streaming_active_ticker", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (set_streaming_active_ticker)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 274, "_graceful_disconnect_stream_client", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_graceful_disconnect_stream_client)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 293, "_drain_asyncio_tasks", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_drain_asyncio_tasks)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 304, "_message_loop_until_shutdown", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_message_loop_until_shutdown)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 347, "_run_stream_loop", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_run_stream_loop)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 358, "_run_stream_loop._async_run", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_run_stream_loop._async_run)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 380, "_run_stream_loop._async_run._book_handler", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_run_stream_loop._async_run._book_handler)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 393, "_run_stream_loop._async_run._level_one_handler", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_run_stream_loop._async_run._level_one_handler)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 476, "start_order_flow_stream", "DERIVED", None, ("order_flow_live_state.py:get_content_for_symbol",), None, "Delegates to Schwab transport producers for start_order_flow_stream."),
    Mega2TraceableDerivation("order_flow_streaming.py", 507, "stop_order_flow_stream", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (stop_order_flow_stream)."),
    Mega2TraceableDerivation("order_flow_streaming.py", 544, "get_stream_thread", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_stream_thread)."),
)

