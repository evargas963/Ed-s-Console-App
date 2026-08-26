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
        "terrain_engine.py",
        "math_probabilities.py",
        "math_volatility.py",
        "order_flow_engine.py",
        "order_flow_live_state.py",
        "order_flow_streaming.py",
    }
)

# RC-297: engine modules that are legitimately OUTSIDE the Mega2 (§D+§E) scope —
# they are inventoried by other megas / lanes, not uninventoried producers.
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
        if not name.endswith(".py"):
            continue
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
    # RETIRED (mission TRUTH_V1, RC-473/474): compute_order_flow_verdict DELETED from math_exposure.py.
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
    Mega2TraceableDerivation("math_exposure_core.py", 34, "gamma_is_plausible", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike",), None, "Rejects poisoned Schwab per-contract gamma (negative or implausibly large) before aggregation."),
    Mega2TraceableDerivation("math_exposure_core.py", 34, "schwab_iv_to_sigma", "SCHWAB_LEAF", 'chains.callExpDateMap.*.volatility', (), None, "Single conversion of Schwab IV (reported in percent) to decimal sigma; guards a vendor units change."),
    Mega2TraceableDerivation("math_exposure_core.py", 36, "bucket_metric_abs", "DERIVED", None, ("math_exposure_core.py:bucket_metric",), None, "Abs of bucket_metric."),
    Mega2TraceableDerivation("math_exposure_core.py", 66, "_strike_bucket", "SCHWAB_LEAF", 'chains.callExpDateMap.*.openInterest', (), None, "Strike dict lookup."),
    Mega2TraceableDerivation("math_exposure_core.py", 102, "compute_exposures_by_strike", "DERIVED", None, ("server.py:_fetch_state",), None, "Core Schwab chain aggregation; skip -999 greeks."),
    Mega2TraceableDerivation("math_exposure_core.py", 211, "compute_exposures_by_strike._tte_memo", "NONE", None, (), None, "No market-field derivation: per-expiry TTE memo cache nested in compute_exposures_by_strike; parent row owns derivation semantics."),
    Mega2TraceableDerivation("math_exposure_core.py", 255, "_nearest_strike", "SCHWAB_LEAF", 'chains.*.strikePrice', (), None, "ATM strike selection."),
    Mega2TraceableDerivation("math_exposure_core.py", 266, "_window_strikes", "SCHWAB_LEAF", 'chains.*.strikePrice', (), None, "Strike window filter."),
    Mega2TraceableDerivation("math_exposure_core.py", 282, "exposures_have_dollar_gex", "DERIVED", None, ("math_exposure_core.py:bucket_metric",), None, "Detects dollarized GEX availability."),
    Mega2TraceableDerivation("math_exposure_core.py", 292, "key_level_strikes_with_oi", "SCHWAB_LEAF", 'chains.*.openInterest', (), None, "Strikes with OI leaf."),
    Mega2TraceableDerivation("math_exposure_core.py", 305, "key_level_strikes_with_gamma", "SCHWAB_LEAF", 'chains.*.gamma', (), None, "Strikes with usable gamma."),
    Mega2TraceableDerivation("math_exposure_core.py", 321, "total_gex_dollars_at_strike", "DERIVED", None, ("math_exposure_core.py:bucket_metric_abs",), None, "Sum |call|+|put| GEX$."),
    Mega2TraceableDerivation("math_exposure_core.py", 496, "pick_key_delta_strike", "DERIVED", None, ("math_exposure_core.py:bucket_metric_abs",), None, "Selects the strike with the largest total delta notional (|call DEX$|+|put DEX$|) from derived exposures; no raw leaf read."),
    Mega2TraceableDerivation("math_exposure_core.py", 507, "pick_key_delta_strike._total_dex", "DERIVED", None, ("math_exposure_core.py:bucket_metric_abs",), None, "Nested: sums |call DEX$|+|put DEX$| per strike bucket for the key-delta selection."),
    Mega2TraceableDerivation("math_exposure_core.py", 518, "pick_volatility_point_strikes", "DERIVED", None, ("math_exposure_core.py:bucket_metric",), None, "(HVP, LVP): strikes holding the most-negative / most-positive net GEX$ from derived exposures."),
    Mega2TraceableDerivation("math_exposure_core.py", 333, "net_gex_dollars_at_strike", "DERIVED", None, ("math_exposure_core.py:bucket_metric",), None, "Net GEX$ at strike."),
    Mega2TraceableDerivation("math_exposure_core.py", 337, "total_gamma_raw_at_strike", "DERIVED", None, ("math_exposure_core.py:bucket_metric_abs",), None, "Raw gamma magnitude fallback."),
    Mega2TraceableDerivation("math_exposure_core.py", 348, "net_gamma_raw_at_strike", "DERIVED", None, ("math_exposure_core.py:bucket_metric",), None, "Raw net gamma."),
    Mega2TraceableDerivation("math_exposure_core.py", 352, "_pick_strike_max_metric", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Max-metric strike picker."),
    # RC-297: `pick_gamma_pin_strike` no longer exists. RC-124 split it in two because ONE
    # name was carrying two metrics — the total-gamma magnet and the signed-book peak — and
    # this row was the last place the retired name survived. Both successors are inventoried
    # below, each stating which book it measures.
    Mega2TraceableDerivation("math_exposure_core.py", 468, "pick_pin_and_strength", "DERIVED", None, ("terrain_engine.py:compute_terrain",), None, "RC-124/RC-315: the strike with maximum TOTAL gamma (|call GEX$| + |put GEX$|) — a GROSS GAMMA CONCENTRATION, i.e. where the most dealer re-hedging activity sits — plus strength_pct, the leader's margin over the runner-up on the same metric. It is a pin CANDIDATE and NOT a demonstrated magnet: magnitude sets the SIZE of the hedging flow while the SIGN of the dealer position sets whether that flow stabilises or repels, and this metric discards the sign, so two strikes with equal absolute gamma can behave oppositely. The sign is also not observable — public open interest does not say who owns the contracts, so dealer direction is modelled (https://spotgamma.com/what-is-gex-gamma-exposure/). Expiration-date clustering turns on NET positioning, not gross: Ni, Pearson and Poteshman, Journal of Financial Economics, doi:10.1016/j.jfineco.2004.08.005. An earlier version of this row asserted that magnitude pins regardless of sign; that was refuted (RC-315) and must not return. Fail-closed: no dollarized GEX gives (None, None), never a raw-gamma fallback."),
    Mega2TraceableDerivation("math_exposure_core.py", 499, "pick_net_gex_peak_strike", "DERIVED", None, ("math_levels.py:build_summary_rows", "server.py:_fetch_state", "terrain_engine.py:compute_terrain",), None, "RC-124/RC-417: the strike with the largest |net GEX$| per 1% (calls MINUS puts) — a real measure of where the signed book concentrates, formerly displayed under the name 'gamma pin'. ExposureRow.net_gex_peak is this strike; the canonical pin is pick_pin_and_strength. institutional=True returns None rather than falling back to raw gamma."),
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
    Mega2TraceableDerivation("math_exposure_core.py", 890, "compute_net_charm._tte_memo", "DERIVED", None, ("math_exposure_core.py:compute_net_charm",), None, "Nested: memoises time_et.time_to_expiry_years per distinct expiry against a `now` pinned once for the aggregate (RC-245). Not an optimisation only — with now=None each per-contract call re-read the clock, so T drifted across the loop and one reported figure described several moments."),
    Mega2TraceableDerivation("math_exposure_core.py", 745, "greek_bias", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Bias string from greeks."),
    Mega2TraceableDerivation("math_exposure_core.py", 778, "compute_beta", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Beta from return series; inputs from Schwab candles."),
    Mega2TraceableDerivation("math_exposure_core.py", 820, "compute_beta_residual", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Residual vs SPY; quote-derived inputs."),
    Mega2TraceableDerivation("math_exposure_core.py", 830, "returns_from_candles", "SCHWAB_LEAF", 'pricehistory.candles.*.close', (), None, "Daily returns; datetime required (cross-section fix)."),
    Mega2TraceableDerivation("math_levels.py", 115, "_strike_total_oi", "NONE", None, (), None, "No market-field derivation: Both-leg OI gate for max pain / OI center."),
    Mega2TraceableDerivation("math_levels.py", 128, "_pick_oi_center", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "OI-weighted center."),
    Mega2TraceableDerivation("math_levels.py", 138, "_pick_inflection_closest_zero", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Zero-cross inflection picker."),
    Mega2TraceableDerivation("math_levels.py", 157, "_pin_strength", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Net-GEX peak concentration vs neighbors (High/Med/Low of |net GEX$| at the analytics peak). Not the terrain pin lead %."),
    Mega2TraceableDerivation("math_levels.py", 194, "_bias_from_net", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Bias signal taxonomy."),
    Mega2TraceableDerivation("math_levels.py", 215, "build_summary_rows", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike", "market_state.py:build_market_state",), None, "KEY LEVELS summary table rows."),
    Mega2TraceableDerivation("math_levels.py", 347, "compute_pin_width_pts", "DERIVED", None, ("market_state.py:build_market_state", "server.py:_fetch_state",), None, "RC-345/F20 one authority for pin width: call_gamma_wall - put_gamma_wall in points; None unless both walls present."),
    Mega2TraceableDerivation("math_levels.py", 345, "consensus_walls_bind_terrain_ssot", "DERIVED", None, ("terrain_engine.py:compute_terrain", "math_levels.py:build_walls_rows",), None, "RC-420/RC-422: CONSENSUS gamma/delta wall strikes bind to the terrain cache; OI/vanna wall slots are withheld because terrain does not compute them."),
    Mega2TraceableDerivation("math_levels.py", 231, "build_summary_rows.aggregate", "DERIVED", None, ("math_levels.py:build_summary_rows",), None, "Nested strike-window aggregate inside build_summary_rows."),
    Mega2TraceableDerivation("math_levels.py", 324, "_dominant", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Dominant side selection."),
    Mega2TraceableDerivation("math_levels.py", 339, "build_walls_rows", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike", "market_state.py:build_market_state",), None, "Walls table for UI."),
    Mega2TraceableDerivation("math_levels.py", 353, "build_totals_rows.strikes_for", "DERIVED", None, ("math_levels.py:build_totals_rows",), None, "Nested strike list filter inside build_totals_rows."),
    Mega2TraceableDerivation("math_levels.py", 473, "build_totals_rows", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike",), None, "Totals table aggregation."),
    Mega2TraceableDerivation("math_levels.py", 575, "is_pin_zone", "ALLOWLISTED", None, (), 'mega2_internal_helper', "Zone classifier constant check."),
    Mega2TraceableDerivation("math_levels.py", 581, "parity_f_minus_spot_from_contracts", "SCHWAB_LEAF", 'chains.callExpDateMap.*.mark', (), None, "Parity residual; mark-only mid per strike."),
    Mega2TraceableDerivation("math_levels.py", 618, "parity_f_minus_spot_from_contracts._mid", "SCHWAB_LEAF", 'chains.callExpDateMap.*.mark', (), None, "Nested mid from Schwab bid/ask/mark only."),
    Mega2TraceableDerivation("math_levels.py", 680, "_norm_pdf", "DERIVED", None, ("math_levels.py:bs_gamma",), None, "Standard normal PDF; pure math constant, no market field."),
    Mega2TraceableDerivation("math_levels.py", 684, "bs_gamma", "DERIVED", None, ("math_levels.py:compute_gamma_profile",), None, "Black-Scholes gamma N'(d1)/(S*sigma*sqrt(T)); refuses T<=0 or sigma<=0."),
    Mega2TraceableDerivation("math_levels.py", 698, "_contract_inputs", "SCHWAB_LEAF", 'chains.callExpDateMap.*.volatility', (), None, "Reads strike/IV/OI/DTE/putCall leaves from the Schwab contract; normalizes IV-in-percent."),
    Mega2TraceableDerivation("math_levels.py", 698, "bs_charm", "DERIVED", None, ("math_levels.py:compute_charm_by_strike",), None, "Black-Scholes charm dDelta/dt per share; verified against a finite-difference derivative of BS delta."),
    Mega2TraceableDerivation("math_levels.py", 704, "bs_vanna", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike",), None, "Black-Scholes vanna dDelta/dSigma per share, closed form -e^(-qT) phi(d1) d2 / sigma — identical for calls and puts, sign driven entirely by -d2 so it flips through SPOT and never through the call/put boundary. Independently verified 2026-08-02 against a central finite difference of BS delta over 27 (K,T,sigma) points to max |err| 9.1e-9, and against both the vega and gamma identities; the gamma identity is a standing cross-check in tests/test_charm_sign_finite_difference.py. Units are delta-change per 1.00 of IV."),
    Mega2TraceableDerivation("math_levels.py", 721, "compute_gamma_profile", "DERIVED", None, ("server.py:_fetch_state",), None, "Dealer gamma recomputed at each hypothetical spot (+call/-put); canonical profile."),
    Mega2TraceableDerivation("math_levels.py", 809, "_dealer_sign", "NONE", None, (), None, "No market-field derivation: maps the +1 call / -1 put naive side sign to the dealer sign per sign_model (naive vs empirical-prior GPO)."),
    Mega2TraceableDerivation("math_levels.py", 725, "compute_charm_by_strike", "DERIVED", None, ("terrain_engine.py:compute_terrain",), None, "Per-strike dealer charm exposure in delta-shares/day, +call/-put convention."),
    Mega2TraceableDerivation("math_levels.py", 729, "_total_gamma_at_strike", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "Total gamma measure at strike."),
    Mega2TraceableDerivation("math_levels.py", 737, "compute_hvl", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike", "market_state.py:build_market_state",), None, "Delegates pick_hvl_strike."),
    Mega2TraceableDerivation("math_levels.py", 748, "gamma_flip_from_profile", "DERIVED", None, ("math_levels.py:compute_gamma_flip_v2",), None, "Interpolated zero-crossing of the gamma profile."),
    Mega2TraceableDerivation("math_levels.py", 750, "hvl_gamma_strength", "DERIVED", None, ("math_levels.py:_total_gamma_at_strike",), None, "Strength at HVL."),
    Mega2TraceableDerivation("math_levels.py", 758, "pick_charm_wall_strikes", "DERIVED", None, ("terrain_engine.py:compute_terrain",), None, "Strikes of maximum call-side and put-side charm exposure."),
    Mega2TraceableDerivation("math_levels.py", 762, "compute_max_pain", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike", "server.py:_fetch_state",), None, "Max pain from OI; no Schwab max-pain leaf."),
    Mega2TraceableDerivation("math_levels.py", 763, "compute_gamma_flip_v2", "DERIVED", None, ("server.py:_fetch_state",), None, "Gamma flip plus chain-span confidence flag; narrow chains are never served as trustworthy."),
    Mega2TraceableDerivation("math_levels.py", 776, "compute_max_pain._pain_at", "DERIVED", None, ("math_levels.py:compute_max_pain",), None, "Nested pain calc at settlement inside compute_max_pain."),
    Mega2TraceableDerivation("math_levels.py", 806, "max_pain_oi_strength", "DERIVED", None, ("server.py:_fetch_state", "market_state.py:build_market_state",), None, "OI at max pain strike."),
    Mega2TraceableDerivation("math_levels.py", 824, "compute_gamma_void_zones", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike",), None, "Delegates to Schwab transport producers for compute_gamma_void_zones."),
    Mega2TraceableDerivation("math_levels.py", 840, "gamma_at_price", "DERIVED", None, ("math_levels.py:compute_gamma_flip_v2",), None, "Net dealer gamma interpolated at a price; the SIGN of this value defines the regime, independent of whether a flip exists."),
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
    Mega2TraceableDerivation("math_probabilities.py", 1245, "flow_imbalance_label_from_normalized", "NONE", None, (), None, "No market-field derivation: label bands for the persisted/served flow_imbalance number (F11)."),
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
    # RETIRED (mission TRUTH_V1, RC-474): _compute_absorption DELETED (whole-buffer density mislabeled absorption).
    Mega2TraceableDerivation("order_flow_engine.py", 545, "_iter_option_exp_levels", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_iter_option_exp_levels)."),
    Mega2TraceableDerivation("order_flow_engine.py", 606, "_option_contract_volume", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_option_contract_volume)."),
    Mega2TraceableDerivation("order_flow_engine.py", 619, "_compute_options_flow", "DERIVED", None, ("order_flow_engine.py:_iter_option_exp_levels", "order_flow_engine.py:_option_contract_volume",), None, "Options flow from chain/stream maps."),
    Mega2TraceableDerivation("order_flow_engine.py", 686, "_compute_rvol", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_rvol)."),
    Mega2TraceableDerivation("order_flow_engine.py", 740, "_compute_institutional_flow_proxy", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_institutional_flow_proxy)."),
    Mega2TraceableDerivation("order_flow_engine.py", 766, "_normalize", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_normalize)."),
    # RETIRED (mission TRUTH_V1, RC-474): _compute_order_flow_score / _direction / _readiness DELETED with the composite.
    Mega2TraceableDerivation("order_flow_engine.py", 799, "_weighted_mean_present", "DERIVED", None, ("order_flow_engine.py:OrderFlowEngine.compute",), None, "Composite mean over present legs only — derives order_flow composite from Schwab-derived inputs (_weighted_mean_present)."),
    Mega2TraceableDerivation("order_flow_engine.py", 837, "OrderFlowEngine.compute", "DERIVED", None, ("order_flow_live_state.py:get_content_for_symbol",), None, "Public OF engine entry; composes sub-metrics."),
    Mega2TraceableDerivation("order_flow_engine.py", 992, "OrderFlowEngine._empty_result", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (OrderFlowEngine._empty_result)."),
    Mega2TraceableDerivation("order_flow_engine.py", 1046, "_mock_data", "ALLOWLISTED", None, (), 'mega2_test_fixture', "Order-flow metric from Schwab stream/quote fields."),
    Mega2TraceableDerivation("order_flow_engine.py", 1144, "_main", "NONE", None, (), None, "No market-field derivation: CLI/mock/diagnostic; no production derivation."),
    # ORDER_FLOW_MARKET_MICROSTRUCTURE_V1 (RC-445/446/447): canonical book-microstructure faucet.
    Mega2TraceableDerivation("order_flow_engine.py", 225, "_book_side_depth_total", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_side_depth_total)."),
    Mega2TraceableDerivation("order_flow_engine.py", 235, "_book_imbalance_from_totals", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_imbalance_from_totals)."),
    Mega2TraceableDerivation("order_flow_engine.py", 443, "_sorted_valid_levels", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_sorted_valid_levels)."),
    Mega2TraceableDerivation("order_flow_engine.py", 453, "_extract_canonical_book", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_extract_canonical_book)."),
    Mega2TraceableDerivation("order_flow_engine.py", 482, "_canonical_book_identity", "NONE", None, (), None, "No market-field derivation: hashable cache-identity over the extracted canonical book for carry invalidation."),
    Mega2TraceableDerivation("order_flow_engine.py", 495, "_microprice", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_microprice)."),
    Mega2TraceableDerivation("order_flow_engine.py", 515, "_book_pressure_curve", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_pressure_curve)."),
    Mega2TraceableDerivation("order_flow_engine.py", 525, "_book_slope", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_slope)."),
    Mega2TraceableDerivation("order_flow_engine.py", 541, "_book_concentration", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_concentration)."),
    Mega2TraceableDerivation("order_flow_engine.py", 552, "_book_wall_candidates", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_wall_candidates)."),
    Mega2TraceableDerivation("order_flow_engine.py", 576, "_microstructure_structural", "DERIVED", None, ("order_flow_engine.py:_book_side_depth_total", "order_flow_engine.py:_microprice", "order_flow_engine.py:_book_wall_candidates",), None, "Structural book microstructure: depth totals, imbalance, microprice, slope, concentration and wall candidates from one canonical book snapshot."),
    Mega2TraceableDerivation("order_flow_engine.py", 662, "compute_book_microstructure", "DERIVED", None, ("order_flow_engine.py:_extract_canonical_book", "order_flow_engine.py:_microstructure_structural",), None, "Canonical book microstructure producer: extracts the book once, carries structural state per book identity, stamps ages; the API route serializes it."),
    Mega2TraceableDerivation("order_flow_live_state.py", 33, "is_rth_open", "ALLOWLISTED", None, (), 'mega1_session_calendar', "No Schwab market-field derivation in function body."),
    Mega2TraceableDerivation("order_flow_live_state.py", 46, "_get_book", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_get_book)."),
    Mega2TraceableDerivation("order_flow_live_state.py", 53, "_get_tape", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_get_tape)."),
    Mega2TraceableDerivation("order_flow_live_state.py", 60, "push_book", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (push_book)."),
    Mega2TraceableDerivation("order_flow_live_state.py", 93, "_get_receive_log", "NONE", None, (), None, "No market-field derivation: local receive-log deque accessor; not a native trade id."),
    Mega2TraceableDerivation("order_flow_live_state.py", 100, "push_level_one", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (push_level_one)."),
    Mega2TraceableDerivation("order_flow_live_state.py", 202, "get_content_for_symbol", "DERIVED", None, ("order_flow_live_state.py:push_level_one", "order_flow_live_state.py:push_book",), None, "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_content_for_symbol)."),
    Mega2TraceableDerivation("order_flow_live_state.py", 231, "get_l1_stream_input_probe", "ALLOWLISTED", None, (), 'mega1_l1_sse_counters', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_l1_stream_input_probe)."),
    Mega2TraceableDerivation("order_flow_live_state.py", 256, "clear_all_live_state", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Clears tape/book/top/prev-print identity on disconnect/reconnect so prior-session restatements cannot bind the new session."),
    Mega2TraceableDerivation("order_flow_live_state.py", 266, "_clear_all_session_state_unlocked", "NONE", None, (), None, "No market-field derivation: lock-held session wipe helper; parent clear_all_live_state owns the stream identity contract."),
    Mega2TraceableDerivation("order_flow_live_state.py", 282, "forget_unsubscribed_symbols", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Clears live state for symbols leaving the active LEVELONE subscription set."),
    Mega2TraceableDerivation("order_flow_live_state.py", 291, "get_receive_log", "NONE", None, (), None, "No market-field derivation: copies local receive_seq log; not a native trade id."),
    Mega2TraceableDerivation("order_flow_live_state.py", 300, "clear_symbol", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (clear_symbol)."),
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
    Mega2TraceableDerivation("order_flow_streaming.py", 71, "options_streaming_enabled", "NONE", None, (), None, "No market-field derivation: reads the ED_OPTIONS_STREAM gate at call time so enabling/disabling options collection is honoured without an import-time cache."),
    Mega2TraceableDerivation("order_flow_streaming.py", 78, "_register_options_handlers", "NONE", None, (), None, "No market-field derivation: attaches LEVELONE_OPTIONS/OPTIONS_BOOK handlers to the EXISTING StreamClient. Registration is inert until something subscribes, and failures are contained so the equity path cannot be aborted."),
    Mega2TraceableDerivation("order_flow_streaming.py", 95, "_start_options_collection", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Selects contracts from chains ALREADY persisted, starts the bounded ingest writer, subscribes the two options services on the sole client, and records coverage epochs. Reads no Schwab market field itself; selection rides stored chain data."),
    Mega2TraceableDerivation("order_flow_streaming.py", 150, "_stop_options_collection", "NONE", None, (), None, "No market-field derivation: closes coverage epochs and drains the writer at shutdown, so retained history never claims observability past the end of the session."),
    Mega2TraceableDerivation("order_flow_streaming.py", 175, "options_stream_status", "NONE", None, (), None, "No market-field derivation: reports options collection enablement, subscribed contract count and ingest counters for the diagnostics surface."),
    Mega2TraceableDerivation("order_flow_streaming.py", 420, "_run_stream_loop._async_run._options_frame_handler", "NONE", None, (), None, "No market-field derivation: builds the per-service options frame handler. Nested factory; the handler it returns owns the behaviour."),
    Mega2TraceableDerivation("order_flow_streaming.py", 421, "_run_stream_loop._async_run._options_frame_handler._handler", "ALLOWLISTED", None, (), 'mega2_schwab_stream_l1', "Receives a decoded LEVELONE_OPTIONS/OPTIONS_BOOK frame on the shared stream loop and hands it to the bounded queue. O(1) and error-contained by construction: no field is read, parsed or derived here, because any work on this thread stalls LEVELONE_EQUITIES/NASDAQ_BOOK/NYSE_BOOK."),
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
    Mega2TraceableDerivation("terrain_engine.py", 80, "TerrainSnapshot.to_dict", "NONE", None, (), None, "No market-field derivation: dataclass-to-dict serialization for the API response."),
    Mega2TraceableDerivation("terrain_engine.py", 84, "_unavailable", "NONE", None, (), None, "No market-field derivation: builds the fail-closed terrain payload from caller-supplied ticker/spot only."),
    Mega2TraceableDerivation("terrain_engine.py", 93, "compute_terrain", "DERIVED", None, ("server.py:_latest_chain_and_spot",), None, "Assembles the terrain payload (regime, walls, pin, HVL, max pain, charm walls) from one chain; no model stack."),
    # RC-297: nine terrain functions and four exposure/levels functions had drifted out of
    # this inventory, and one entry named a function that no longer exists. Traced 2026-08-09
    # by AST — callers resolved across the tracked index, vendor leaves read out of each
    # body — rather than by pattern-matching neighbouring rows.
    Mega2TraceableDerivation("terrain_engine.py", 169, "_per_strike_rows", "SCHWAB_LEAF", 'chains.*.totalVolume', (), None, "Builds the [[strike, net_gex_1pct$, session_volume], ...] triples the per-strike panel renders; volume is summed from the chain's own totalVolume through float_nonnegative_or_none, strikes through float_finite_or_none, so a NaN can never become a key or a bar."),
    Mega2TraceableDerivation("terrain_engine.py", 215, "_dte_of", "SCHWAB_LEAF", 'chains.*.daysToExpiration', (), None, "Reads the contract's own daysToExpiration and returns None when it cannot be read; RC-290 removed the 999.0 sentinel that was putting unknown-maturity contracts into the FAR scope and rendering them there."),
    Mega2TraceableDerivation("terrain_engine.py", 231, "compute_wall_value_area", "DERIVED", None, ("terrain_engine.py:compute_terrain",), None, "RC-115 Market-Profile value area over SIDE gamma mass — the wall's earned range. Consumes exposures already derived upstream; reads no vendor leaf itself."),
    Mega2TraceableDerivation("terrain_engine.py", 282, "compute_implied_one_day_move", "SCHWAB_LEAF", 'chains.*.volatility', (), None, "RC-113 institutional sigma band EM_1d = S x sigma_ATM x sqrt(1/252); selects the ATM contract by putCall and strikePrice and takes its volatility leaf directly."),
    Mega2TraceableDerivation("terrain_engine.py", 339, "_per_strike_scopes", "DERIVED", None, ("terrain_engine.py:compute_terrain",), None, "Splits the per-strike rows into the {all, near, far} sets the ALL / <=7DTE / MONTHLY+ chips switch between; the maturity split comes from _dte_of and a contract that cannot answer it lands in NEITHER side (RC-290)."),
    Mega2TraceableDerivation("terrain_engine.py", 366, "_per_strike_map", "SCHWAB_LEAF", 'chains.*.totalVolume', (), None, "Per-strike net GEX$ and session volume from the chain that just built `exposures`; volume stays None until a contract supplies one, so a missing totalVolume cannot render as a real zero (RC-290)."),
    Mega2TraceableDerivation("terrain_engine.py", 401, "strongest_strike_storm1", "DERIVED", None, ("terrain_engine.py:compute_terrain",), None, "RC-159 spot-independent strongest strike, ranked over the [[strike, net_gex, volume], ...] triples _per_strike_rows already produced; reads no vendor leaf."),
    Mega2TraceableDerivation("terrain_engine.py", 439, "strongest_strike_storm1._inv_ranks", "DERIVED", None, ("terrain_engine.py:strongest_strike_storm1",), None, "Nested: n+1-rank with AVERAGE ranks for ties (rank 1 = highest), so tied strikes cannot be ordered by list position."),
    Mega2TraceableDerivation("terrain_engine.py", 477, "wall_geometry_state", "DERIVED", None, ("server.py:get_terrain", "terrain_engine.py:compute_terrain",), None, "RC-130: answers whether a wall is in the configuration its support/resistance label claims (contains / breached / unknown) from spot and the wall strike; the UI renders NO behavioural claim without a positive state."),    # Strike-width derivation added 2026-07-20 (RC-12 root fix).
    Mega2TraceableDerivation("terrain_engine.py", 585, "qualify_pin_candidate", "DERIVED", None, ("terrain_engine.py:compute_terrain", "math_probabilities.py:compute_pin_score",), None, "RC-292 operator disposition: pin_candidate is the absolute-gamma strike published as a candidate pin ONLY after regime (net long gamma at spot), proximity (<=0.5% of spot, study_pin_residence_v1 cut), DTE (front expiry <=1 day, same study), liquidity (committed pin-score thresholds above negligible) and completeness (RC-413 magnitude bundle present) qualification; every gate fail-closed, absence ships with its blocker names."),
    Mega2TraceableDerivation("math_levels.py", 870, "infer_strike_increment", "SCHWAB_LEAF", 'chains.callExpDateMap.*.strikePrice', (), None, "Median adjacent difference of strikePrice values from an already-fetched chain; junk rows skipped, thin chains return None."),
    Mega2TraceableDerivation("math_levels.py", 902, "required_strike_count", "NONE", None, (), None, "No market-field derivation: pure arithmetic from spot, strike increment and GAMMA_FLIP_MIN_SPAN_PCT; sizes the NEXT fetch request."),
    # RC-354/RC-357..RC-362 desk metrics traced into the inventory 2026-08-17. Each row
    # below was assigned by reading the function body and its resolved caller, not by
    # copying a neighbouring row: the four exposure aggregates and the GSF/GRC pair
    # consume the ALREADY-derived exposures/profile books, so they are DERIVED and their
    # producer_refs name the real upstream producer; the 25-delta risk reversal is the
    # only one of the nine that reads a vendor contract field itself.
    Mega2TraceableDerivation("math_exposure_core.py", 449, "compute_net_vanna", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike", "terrain_engine.py:compute_terrain",), None, "RC-362: sums call_vanna MINUS put_vanna over the ONE exposures book compute_exposures_by_strike already built (per-strike vanna is the vega/(S*IV) proxy accumulated with OI and multiplier at parse time), divides by 100 for per-vol-point and multiplies by spot for dollars. Reads no vendor field itself; the dealer sign model is inherited from the book, not re-encoded. Fail-closed: None on an empty/valueless book or missing spot, never a fabricated zero."),
    Mega2TraceableDerivation("math_exposure_core.py", 480, "compute_net_dex_dollars", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike",), None, "RC-361: sums call_dex_dollars MINUS put_dex_dollars over the same exposures book, giving the dealer's net delta notional (put deltas already arrive negative, so subtracting the put leg lands on the dealer's side). Consumes only fields the book produced; fail-closed to None on an empty/degenerate book rather than a fabricated $0."),
    Mega2TraceableDerivation("math_exposure_core.py", 509, "compute_delta_oi_walls", "DERIVED", None, ("terrain_engine.py:compute_terrain",), None, "RC-359: diffs today's {strike: (call_oi, put_oi)} map — taken from the terrain snapshot's oi_by_strike, i.e. the same exposures book — against the prior session banked by server.py, then picks the largest call build, largest put build and deepest combined unwind. It reads no vendor leaf; the OI values reach it already parsed. Fail-closed: None when no prior session is banked, so the diff is withheld rather than invented."),
    Mega2TraceableDerivation("math_exposure_core.py", 553, "compute_zero_dte_gamma_share", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike",), None, "RC-357: share of sum(|net_gex_1pct|) contributed by the same-day-expiry book over the full book, where BOTH books come from compute_exposures_by_strike (the 0DTE one is the same call with use_only_dte_max=0) — same parser, same sign model, no second math path. A bucket missing net_gex_1pct withholds the whole ratio rather than contributing a fabricated zero weight (RC-369)."),
    Mega2TraceableDerivation("math_levels.py", 944, "_interp_profile_at", "DERIVED", None, ("math_levels.py:compute_gamma_profile",), None, "Linear interpolation of net GEX$ at an arbitrary price on the ascending profile compute_gamma_profile materialised; clamps to the endpoints outside the profile span. Operates purely on that derived profile — no vendor field is read here."),
    Mega2TraceableDerivation("math_levels.py", 961, "compute_gamma_support_levels", "DERIVED", None, ("math_levels.py:compute_gamma_profile", "math_levels.py:_interp_profile_at",), None, "RC-354: the Gamma Support Floor (highest s < spot with N(s) <= phi*N(spot)) and Gamma Resistance Ceiling (lowest s > spot with the same condition) on the SAME materialised net-GEX profile the flip and regime read (RC-345 one-profile rule), located by walking outward from spot and linearly interpolating the crossing. Fail-closed: N(spot) <= eps returns state=BELOW_SUPPORT with both levels None, an unusable profile returns state=UNAVAILABLE — never a fabricated price."),
    Mega2TraceableDerivation("math_levels.py", 1001, "compute_gamma_support_levels._cross", "NONE", None, (), None, "No market-field derivation: nested linear solve for the price at which one profile segment crosses the phi*N(spot) target; the parent row owns the GSF/GRC derivation semantics and its inputs."),
    Mega2TraceableDerivation("math_levels.py", 1028, "snap_level_to_shelf_strike", "DERIVED", None, ("math_exposure_core.py:compute_exposures_by_strike", "math_levels.py:compute_gamma_support_levels",), None, "RC-354 snap-to-shelf: moves a profile-derived GSF/GRC onto a real positive-GEX strike when one clearing the caller-supplied theta sits within snap_pct of it on the correct side of spot. Both inputs are already-derived — the level from compute_gamma_support_levels, the per-strike GEX$ from the exposures book — so no vendor field is read; a None level and an empty strike map pass through unchanged."),
    Mega2TraceableDerivation("math_volatility.py", 40, "compute_25d_risk_reversal", "SCHWAB_LEAF", 'chains.callExpDateMap.*.volatility', (), None, "RC-358: IV(25-delta call) minus IV(25-delta put) on the front expiry, in vol points. Unlike the other RC-35x metrics this one reads the vendor contract dicts directly — putCall, daysToExpiration, delta and the `volatility` leaf, which Schwab reports in PERCENT and which stays in vol points here. Front expiry is the smallest usable dte >= 0; each wing must sit within RR25_DELTA_TOL of its +/-0.25 target and the -999 missing-greek sentinel is rejected, so a missing or off-target wing withholds the whole reading rather than producing a fabricated skew."),

)

