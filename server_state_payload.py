"""Full-bundle API payload projection of _fetch_state (server.py), extracted (RC-REHAB-1,
2026-09-23). Thirty-third slice of the _fetch_state decomposition -- see
server_state_volatility.py's own docstring for why this decomposition exists.

_project_state_payload turns one analytics cycle's already-computed values into the served
`ms_dict`. It COMPUTES nothing new: every value was produced by an earlier phase (or by
MarketState itself) and is only copied, rounded for display, or grouped here. The phases hand
over their own NamedTuples (_QuoteForState, _ExpectedMoveForState, _VolatilitySignalsForState,
_PredictivePositioningForState, _VolEnvelopeAndSectorForState, _OrderFlowSignalsForState)
instead of ~40 unpacked locals, so a field can no longer be threaded through the wrong
positional slot. Key insertion order is preserved exactly (the section helpers are called in
the original sequence).

Removed while moving (dead code, zero callers): the nested `_fs` / `_foi` wall-strength
string formatters -- their only uses were deleted by RC-128 and the definitions were left.
The "why no gamma voids?" diagnostic (four full passes over the exposure buckets on every
cycle) now runs only when DEBUG logging is enabled, the only case in which its output is seen.

MONKEYPATCH/RUNTIME-STATE NOTE: server.py-owned runtime state (_logger_lock / _logger_tickers /
_logger_running / _accuracy_cache, VIEWER_* cadence constants, PARITY_RESID_MIN,
_get_prediction_override, _ms_to_dict) and the re-exported _terrain_kl_overlay are reached via
the lazy `import server` pattern so existing mock.patch.object(server, ...) tests keep working.
Pure helpers are imported from their own modules.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from market_context import stamp_confluence_display_fields
from math_exposure_core import (
    bucket_total_oi,
    exposures_have_dollar_gex,
    gex_magnitude_label,
    gex_regime_label,
    total_gamma_raw_at_strike,
)
from math_probabilities import flow_imbalance_label_from_normalized
from numeric_contract import float_finite_or_none

log = logging.getLogger(__name__)

#: The Phase 2A PriceLevelSnapshot family, served RAW (unrounded) exactly as /api/levels
#: serves it (PDH_PRECISION kill, one-faucet-closeout-v1). Order = payload key order.
_RAW_PRICE_LEVEL_FIELDS: tuple[str, ...] = (
    "vwap", "pdh", "pdl", "pdc", "orb_high", "orb_low",
    "today_poc", "today_vah", "today_val", "pd_poc", "pd_vah", "pd_val",
    "overnight_high", "overnight_low", "orb_midpoint",
    "vwap_p1", "vwap_m1", "vwap_p2", "vwap_m2",
)


def _fv(v: Any) -> Optional[float]:
    """2dp display rounding for NON-level fields; None when the value is not numeric."""
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _quote_and_cadence_fields(ms_dict: dict, *, q, spot_label: str, vol_ctx, pcr_val) -> None:
    import server as _srv

    ms_dict["quote_source_detail"] = q.quote_source_detail(spot_label=spot_label)
    ms_dict["spread"] = q.spread_pts
    ms_dict["spread_frac"] = q.spread_frac
    ms_dict["spread_pts"] = q.spread_pts
    ms_dict["spread_source"] = q.spread_source
    ms_dict["spread_frac_source"] = q.spread_frac_source
    ms_dict["spread_pts_source"] = (
        "derived_bid_ask_pts_schwab_quote" if q.spread_pts is not None else None
    )
    ms_dict["spread_age_ms"] = q.spread_age_ms
    # VOL_INPUT_CONTRACT 1.0.0: ms_dict consumes the one per-cycle context —
    # identical values to the SignalInput stamp and the snapshot row (MSD-001).
    ms_dict["vix"] = vol_ctx.market_iv_level
    ms_dict["vix_direction"] = vol_ctx.market_iv_direction
    ms_dict["vix_vs_prev"] = vol_ctx.market_iv_change
    ms_dict["server_ts"] = time.time()
    # Client diagnostics: when a tab has SSE open for this (ticker, expiry), full pipeline
    # re-runs about this often.
    ms_dict["sse_viewer_refresh_sec"] = round(_srv.VIEWER_SSE_REFRESH_SEC, 3)
    ms_dict["sse_viewer_rest_cache_ttl_sec"] = round(_srv.VIEWER_STATE_CACHE_TTL_SEC, 3)
    try:
        from api_pressure import throttle_ui_payload

        ms_dict["api_throttle"] = throttle_ui_payload()
    except ImportError:
        ms_dict["api_throttle"] = {"active": False, "message": "", "hint": "", "n_429_recent": 0}
    ms_dict["pcr_val"] = pcr_val


def _log_why_no_gamma_voids(exposures: dict, spot_f) -> None:
    """Diagnostic only: which void thresholds the strikes failed. DEBUG-gated -- it walks the
    exposure buckets four times and its output is only ever visible at DEBUG."""
    if not log.isEnabledFor(logging.DEBUG):
        return
    gex_vals = [v for b in exposures.values() if (v := total_gamma_raw_at_strike(b)) is not None]
    max_gex = max(gex_vals, default=0)
    oi_vals = [v for b in exposures.values() if (v := bucket_total_oi(b)) is not None]
    max_oi = max(oi_vals, default=0)
    log.debug(
        "Gamma void: %d strikes, max_gex=%.0f, max_oi=%.0f, spot_passed=%s",
        len(exposures), max_gex, max_oi, "yes" if spot_f else "no",
    )

    def _gex_low(b) -> bool:
        v = total_gamma_raw_at_strike(b)
        return max_gex > 0 and v is not None and v < max_gex * 0.20

    def _oi_low(b) -> bool:
        v = bucket_total_oi(b)
        return max_oi > 0 and v is not None and v < max_oi * 0.25

    gex_low = sum(1 for b in exposures.values() if _gex_low(b))
    oi_low = sum(1 for b in exposures.values() if _oi_low(b))
    both_low = sum(1 for b in exposures.values() if _gex_low(b) and _oi_low(b))
    log.debug("Gamma void: gex_low=%d, oi_low=%d, both_low=%d (need 2+ consecutive)",
              gex_low, oi_low, both_low)


def _key_level_fields(
    ms_dict: dict, *, ticker: str, consensus_summary, exposures: dict, diag, em,
    gamma_voids, kl_expiry_source, contracts_use, spot_f,
) -> None:
    import server as _srv

    cs = consensus_summary
    # RC-128 (One Levels Faucet): wall/level/strength/flip-confidence writes that used to live
    # here were DELETED -- _terrain_kl_overlay below is the ONLY writer of every SSOT level key.
    # RC-33: terrain regime/posture/headline/lines are served ONLY by /api/terrain (one
    # terrain, one chain); the narrow-slice terrain_* read this pipeline used to attach is gone.
    _net_gex_raw = getattr(cs, "net_gamma", None) if cs else None
    try:
        _net_gex_f = float(_net_gex_raw) if _net_gex_raw is not None else None
    except (TypeError, ValueError):
        _net_gex_f = None
    ms_dict["kl_net_gex"] = round(_net_gex_f, 2) if _net_gex_f is not None else None
    if _net_gex_f is not None:
        from math_exposure import fmt_money as _fmt_gex_money
        ms_dict["kl_net_gex_disp"] = _fmt_gex_money(_net_gex_f)
        ms_dict["kl_net_gex_mag"] = gex_magnitude_label(_net_gex_f)
        ms_dict["kl_net_gex_regime"] = gex_regime_label(_net_gex_f)
    else:
        ms_dict["kl_net_gex_disp"] = "—"
        # CAPS RC-REHAB-1: no net GEX -> no magnitude / regime read (these used to be served
        # as "negligible" / "neutral"). context_light carries structural keys only when
        # non-None, so L1 omits them.
        ms_dict["kl_net_gex_mag"] = None
        ms_dict["kl_net_gex_regime"] = None
    ms_dict["kl_expiry_source"] = kl_expiry_source
    ms_dict["kl_level_window"] = "selected_expiry"
    ms_dict["kl_metrics_dollarized"] = bool(exposures and exposures_have_dollar_gex(exposures))
    ms_dict["kl_institutional_ready"] = ms_dict["kl_metrics_dollarized"]
    # CAPS RC-REHAB-1: completeness of an EMPTY chain (0 contracts) is undefined -> None.
    _kl_contracts_total = int(diag.contracts_total)
    ms_dict["kl_gex_input_completeness"] = (
        round(float(diag.contracts_used) / _kl_contracts_total, 4)
        if _kl_contracts_total > 0 else None
    )
    # RC-128 / E-34: kl_em_* comes ONLY from the terrain sigma band via the overlay. The
    # straddle/IV figures stay published as em_straddle_*_diag -- a diagnostic that never
    # shares the level vocabulary -- and mc_em_anchor keeps its consumer.
    ms_dict["em_straddle_upper_diag"] = _fv(em.em_straddle.get("upper")) or _fv(em.em_iv.get("upper"))
    ms_dict["em_straddle_lower_diag"] = _fv(em.em_straddle.get("lower")) or _fv(em.em_iv.get("lower"))
    ms_dict["kl_em_anchor"] = em.kl_em_anchor
    ms_dict["mc_em_anchor"] = em.kl_em_anchor
    ms_dict["mc_iv_source"] = em.mc_iv_source
    ms_dict["kl_gamma_voids"] = gamma_voids or []
    # RC-122: applied AFTER every kl_* assignment above -- placement IS the fix. The
    # gamma-family values came from the narrow analytics chain; the screen gets ONE book
    # (terrain SSOT) or an honest blank.
    _srv._terrain_kl_overlay(ms_dict, ticker)
    if not gamma_voids:
        _log_why_no_gamma_voids(exposures, spot_f)

    # Top GEX/DEX drivers (which strikes are driving the walls)
    ms_dict["top_gex_drivers"] = getattr(cs, "top_gex_drivers", []) or []  # caps-ok: a LIST of driver strikes -- with no consensus summary there are no identified drivers, and an empty list states exactly that (no strike or value is invented)
    ms_dict["top_dex_drivers"] = getattr(cs, "top_dex_drivers", []) or []  # caps-ok: a LIST of driver strikes -- empty = none identified, no strike or value invented

    # Synthetic forward (parity level)
    try:
        from math_exposure import parity_f_minus_spot_from_contracts
        _parity_resid = parity_f_minus_spot_from_contracts(contracts_use, spot=spot_f)
        # RC-301: None means the residual could not be computed from this chain, which is
        # not the same as a residual of zero.
        if _parity_resid is not None and abs(_parity_resid) > _srv.PARITY_RESID_MIN:
            ms_dict["kl_synth_fwd"] = round(spot_f + _parity_resid, 2)
            ms_dict["kl_synth_fwd_resid"] = round(_parity_resid, 4)
            ms_dict["kl_synth_fwd_side"] = "CALL" if _parity_resid > 0 else "PUT"
            ms_dict["kl_synth_fwd_label"] = "Calls slightly rich" if _parity_resid > 0 else "Puts slightly rich"
        else:
            ms_dict["kl_synth_fwd"] = None
    except Exception:
        ms_dict["kl_synth_fwd"] = None


def _signal_fields(ms_dict: dict, *, price_levels, em, vs, pp, sweep_score) -> None:
    # PDH_PRECISION kill: the LEVEL family travels RAW -- rounding is a RENDER concern.
    for name in _RAW_PRICE_LEVEL_FIELDS:
        ms_dict[name] = float_finite_or_none(getattr(price_levels, name, None))

    # Expected Move
    ms_dict["em_straddle"] = _fv(em.em_straddle.get("straddle"))
    ms_dict["em_straddle_pts"] = _fv(em.em_straddle.get("em_pts"))
    ms_dict["em_straddle_upper"] = _fv(em.em_straddle.get("upper"))
    ms_dict["em_straddle_lower"] = _fv(em.em_straddle.get("lower"))
    ms_dict["em_iv_pts"] = _fv(em.em_iv.get("em_pts"))
    ms_dict["em_iv_upper"] = _fv(em.em_iv.get("upper"))
    ms_dict["em_iv_lower"] = _fv(em.em_iv.get("lower"))
    ms_dict["em_progress_pct"] = em.em_progress.get("progress_pct")
    ms_dict["em_breached"] = em.em_progress.get("breached")
    ms_dict["em_direction"] = em.em_progress.get("direction")
    ms_dict["em_severity"] = em.em_progress.get("severity")
    ms_dict["em_move_pts"] = em.em_progress.get("move_pts")

    # Volatility signals
    ms_dict["iv_skew"] = vs.iv_skew.get("skew")
    ms_dict["iv_skew_interp"] = vs.iv_skew.get("interpretation")
    ms_dict["realized_vol"] = vs.realized_vol  # percent (compute_realized_vol); SignalInput uses decimal via market_state stamp
    ms_dict["atr"] = vs.atr
    ms_dict["iv_rank"] = vs.iv_rank
    ms_dict["iv_percentile"] = vs.iv_percentile

    # Section 8 — Predictive Positioning Signals. Fail-closed labels: helpers emit None when
    # inputs are absent (Action 11.4), so snapshots persist NULL.
    ms_dict["dpi_raw"] = pp.dpi.get("raw")
    ms_dict["dpi_normalized"] = pp.dpi.get("normalized")
    ms_dict["dpi_direction"] = pp.dpi.get("direction")
    ms_dict["dpi_magnitude"] = pp.dpi.get("magnitude")
    ms_dict["hedging_flow_raw"] = pp.hedging_flow.get("raw")
    ms_dict["hedging_flow_normalized"] = pp.hedging_flow.get("normalized")
    ms_dict["hedging_flow_direction"] = pp.hedging_flow.get("direction")
    ms_dict["gamma_gradient"] = pp.gamma_gradient
    ms_dict["breakout_score"] = pp.breakout_score.get("normalized")
    ms_dict["breakout_label"] = pp.breakout_score.get("label")
    ms_dict["pin_score"] = pp.pin_score_val.get("normalized")
    ms_dict["pin_label"] = pp.pin_score_val.get("label")
    ms_dict["vol_expansion_score"] = pp.vol_expansion.get("normalized")
    ms_dict["vol_expansion_label"] = pp.vol_expansion.get("label")
    ms_dict["sweep_score"] = sweep_score.get("normalized")
    ms_dict["sweep_label"] = sweep_score.get("label")


def _market_state_mirror_fields(ms_dict: dict, ms) -> None:
    """Fields MarketState owns that the payload surfaces under its own names. `ms` is always a
    MarketState here (build_market_state re-raises on failure) and every field is declared."""
    ms_dict["session_high"] = ms.session_high
    ms_dict["session_low"] = ms.session_low
    ms_dict["last_sweep_type"] = ms.last_sweep_type
    ms_dict["last_sweep_level"] = ms.last_sweep_level
    ms_dict["last_sweep_held"] = ms.last_sweep_held
    ms_dict["n_sweeps_today"] = ms.n_sweeps_today

    ms_dict["validation_passed"] = ms.validation_passed
    ms_dict["structure_valid"] = ms.structure_valid
    ms_dict["probability_valid"] = ms.probability_valid
    ms_dict["risk_valid"] = ms.risk_valid
    ms_dict["validation_summary"] = ms.validation_summary

    # Call / Put readiness (computed in call_engine.py, carried on MarketState)
    ms_dict["call_readiness"] = {
        "call_state": ms.call_state,
        "forecast_state": ms.call_forecast_state,
        "readiness_score": ms.call_readiness_score,
        "reasons": list(ms.call_readiness_reasons),
        "missing_conditions": list(ms.call_missing_conditions),
        "component_scores": dict(ms.call_readiness_component_scores),
        "wait_blocker": ms.call_wait_blocker,
    }
    ms_dict["put_readiness"] = {
        "call_state": ms.put_state,
        "forecast_state": ms.put_forecast_state,
        "readiness_score": ms.put_readiness_score,
        "reasons": list(ms.put_readiness_reasons),
        "missing_conditions": list(ms.put_missing_conditions),
        "component_scores": dict(ms.put_readiness_component_scores),
    }

    # Formal Position Sizing
    ms_dict["r_units"] = ms.r_units
    ms_dict["execution_mode"] = ms.execution_mode
    ms_dict["sizing_summary"] = ms.sizing_summary


def _context_fields(ms_dict: dict, *, ves, mkt_ctx, ofs) -> None:
    # Volatility Envelope
    ms_dict["vol_env_upper"] = ves.vol_envelope.get("upper")
    ms_dict["vol_env_lower"] = ves.vol_envelope.get("lower")
    ms_dict["vol_env_width"] = ves.vol_envelope.get("width_pts")

    # Level Density
    ms_dict["level_density_count"] = ves.level_density.get("count")
    ms_dict["level_density_label"] = ves.level_density.get("density_label")
    ms_dict["level_density_names"] = ves.level_density.get("level_names")

    # Sector Strength (3 groups)
    for prefix, grp in (("index", ves.index_strength), ("spy_holdings", ves.spy_strength),
                        ("sector", ves.sector_strength)):
        ms_dict[f"{prefix}_leader"] = grp.get("leader")
        ms_dict[f"{prefix}_laggard"] = grp.get("laggard")
        ms_dict[f"{prefix}_breadth"] = grp.get("breadth")
        # historical key names: spy_holdings_risk (not _risk_signal)
        ms_dict["spy_holdings_risk" if prefix == "spy_holdings" else f"{prefix}_risk_signal"] = grp.get("risk_signal")
        ms_dict[f"{prefix}_spread"] = grp.get("spread")

    # IWM Deep Confluence
    iwm = ves.iwm_deep
    ms_dict["iwm_risk_regime"] = iwm.get("risk_regime")
    ms_dict["iwm_risk_confidence"] = iwm.get("risk_regime_confidence")
    ms_dict["spy_iwm_divergence"] = iwm.get("spy_iwm_divergence")
    ms_dict["spy_iwm_div_label"] = iwm.get("spy_iwm_divergence_label")
    ms_dict["spy_iwm_fragile"] = iwm.get("spy_iwm_fragile")
    ms_dict["qqq_iwm_spread"] = iwm.get("qqq_iwm_spread")
    ms_dict["rotation_signal"] = iwm.get("rotation_signal")
    ms_dict["sector_breadth_quality"] = iwm.get("sector_breadth_quality")
    ms_dict["iwm_early_warning"] = iwm.get("early_warning")
    ms_dict["iwm_early_warning_type"] = iwm.get("early_warning_type")
    ms_dict["iwm_risk_score"] = iwm.get("risk_score")
    ms_dict["iwm_risk_score_label"] = iwm.get("risk_score_label")
    ms_dict["iwm_confluence_summary"] = iwm.get("summary")

    # Bond Yields
    ms_dict["tnx_yield"] = getattr(mkt_ctx, "tnx_yield", None)
    ms_dict["tnx_chg"] = getattr(mkt_ctx, "tnx_chg", None)
    ms_dict["bond_signal"] = getattr(mkt_ctx, "bond_signal", None)

    # Order Flow Signals. RC-345 / F11: the SOURCE book travels beside the value -- book
    # (bid/ask size), volume (call/put traded volume) or none are different economic truths.
    ms_dict["vol_oi_ratio"] = ofs.vol_oi_ratio.get("ratio")
    ms_dict["vol_oi_label"] = ofs.vol_oi_ratio.get("label")
    ms_dict["flow_imbalance"] = ofs.flow_imb_norm
    ms_dict["flow_imbalance_source"] = ofs.flow_imb_source
    ms_dict["flow_imbalance_label"] = flow_imbalance_label_from_normalized(ofs.flow_imb_norm)
    ms_dict["smart_money_score"] = ofs.smart_money.get("score")
    ms_dict["smart_money_direction"] = ofs.smart_money.get("direction")
    ms_dict["smart_money_label"] = ofs.smart_money.get("label")
    ms_dict["iv_model_spread"] = ofs.iv_model_spread.get("spread")
    ms_dict["iv_model_spread_label"] = ofs.iv_model_spread.get("label")


def _constituent_rows(rows, *, with_label: bool = False) -> list[dict]:
    out = []
    for cq in (rows or []):
        row = {"symbol": cq.symbol}
        if with_label:
            row["label"] = getattr(cq, "label", "")  # caps-ok: display-only sector caption; blank when the proxy row has none, the symbol/chg fields carry the data
        row.update({
            "chg_pct": cq.chg_pct,
            "weight": cq.weight,
            "contribution": cq.contribution,
            "dot_color": cq.dot_color,
        })
        out.append(row)
    return out


def _confluence_fields(ms_dict: dict, mkt_ctx) -> None:
    ms_dict["spy_chg_pct"] = getattr(mkt_ctx, "spy_chg_pct", None)
    ms_dict["qqq_chg_pct"] = getattr(mkt_ctx, "qqq_chg_pct", None)
    ms_dict["iwm_chg_pct"] = getattr(mkt_ctx, "iwm_chg_pct", None)
    ms_dict["spy_last"] = _fv(getattr(mkt_ctx, "spy_last", None))
    ms_dict["qqq_last"] = _fv(getattr(mkt_ctx, "qqq_last", None))
    ms_dict["iwm_last"] = _fv(getattr(mkt_ctx, "iwm_last", None))
    # CME index futures (optional — full contract symbols via ED_FUTURES_ES / NQ / RTY)
    for fut in ("es", "nq", "rty"):
        ms_dict[f"fut_{fut}_symbol"] = getattr(mkt_ctx, f"fut_{fut}_symbol", "") or ""  # caps-ok: optional configured contract SYMBOL (ED_FUTURES_*); "" = none configured, a label not a quote -- the price/chg fields beside it stay None
        ms_dict[f"fut_{fut}_last"] = _fv(getattr(mkt_ctx, f"fut_{fut}_last", None))
        ms_dict[f"fut_{fut}_chg_pct"] = getattr(mkt_ctx, f"fut_{fut}_chg_pct", None)
    ms_dict["vix_implication"] = getattr(mkt_ctx, "vix_implication", "")  # caps-ok: display-only prose sentence; blank when the market context carries none, never parsed as data

    # RC-365/F39: absent weighted_push stays None (not 0). Dots None when the push is absent.
    ms_dict.update(stamp_confluence_display_fields(mkt_ctx))
    ms_dict["constituents"] = _constituent_rows(getattr(mkt_ctx, "constituents", None))
    ms_dict["qqq_constituents"] = _constituent_rows(getattr(mkt_ctx, "qqq_constituents", None))
    ms_dict["iwm_holdings_constituents"] = _constituent_rows(getattr(mkt_ctx, "iwm_holdings", None))
    ms_dict["iwm_sectors"] = _constituent_rows(getattr(mkt_ctx, "iwm_sectors", None), with_label=True)


def _accuracy_block(results: Optional[dict]) -> Optional[dict]:
    if not results:
        return None
    return {
        hz: {
            "accuracy": v.get("accuracy"),
            "total": v.get("total"),
            "baseline_pct": v.get("baseline_pct"),
            "edge_vs_baseline_pp": v.get("edge_vs_baseline_pp"),
            "scope": v.get("scope"),
        }
        for hz, v in results.items() if v.get("accuracy") is not None
    }


def _runtime_status_fields(ms_dict: dict, *, ms, ticker: str, db_counts: dict) -> None:
    import server as _srv

    with _srv._logger_lock:
        ms_dict["logger_tickers"] = list(_srv._logger_tickers)
        ms_dict["logger_running"] = _srv._logger_running

    # CAPS RC-REHAB-1: always keyed by _db_counts_and_crosses_for_state; None = counts unknown.
    ms_dict["total_snapshots"] = db_counts["total"]
    ms_dict["filled_snapshots"] = db_counts["filled"]

    # Accuracy (from cache — never blocks the main response). Primary block is RTH-scoped
    # with baseline edge (operator decision 2026-07-06); all-hours rides as a separate
    # audit-context block, and a missing RTH scope fails closed to None rather than
    # borrowing the all-hours numbers.
    _cached = _srv._accuracy_cache.get(ticker, {})
    ms_dict["accuracy"] = _accuracy_block(_cached.get("results"))
    ms_dict["accuracy_scope"] = "rth_0930_1600_et" if ms_dict["accuracy"] is not None else None
    ms_dict["accuracy_all_hours"] = _accuracy_block(_cached.get("all_hours"))

    # Fusion-calibration provenance: artifact_loaded=false IS the raw-serving signal.
    try:
        from multi_horizon_ml_bundle import fusion_calibration_status

        ms_dict["fusion_calibration_v1"] = fusion_calibration_status()
    except Exception as _fcs_e:
        log.debug("fusion_calibration_status attach failed: %s", _fcs_e)
        ms_dict["fusion_calibration_v1"] = None

    _events = list(ms.stack_integrity_events or [])
    if _events:
        try:
            from features.stack_integrity_v1 import finalize_stack_integrity_v1

            ms_dict["stack_integrity_events"] = _events
            ms_dict["stack_integrity_v1"] = finalize_stack_integrity_v1(_events)
        except Exception as e:
            log.warning("finalize_stack_integrity_v1 failed ticker=%s: %s", ticker, e, exc_info=True)


def _project_state_payload(
    ms, *, ticker: str, expiries: list, today_str: str, selected_exp: str, q, vol_ctx,
    pcr_val, consensus_summary, kl_expiry_source, exposures: dict, diag, em, gamma_voids,
    contracts_use, spot_f, price_levels, vs, pp, sweep_score, ves, ofs, mkt_ctx,
    db_counts: dict,
) -> dict:
    """The served full-bundle payload for one analytics cycle (see module docstring)."""
    import server as _srv

    ms_dict = _srv._ms_to_dict(ms)
    ms_dict["analytics_partial_tier_c"] = False
    ms_dict["expiries"] = [e for e in expiries if e >= today_str]
    ms_dict["selected_exp"] = selected_exp
    spot_label = (
        "lastPrice" if q.parsed_last and q.parsed_last > 0
        else "mark" if q.parsed_mark and q.parsed_mark > 0
        else "unavailable_missing_last_and_mark"
    )
    _quote_and_cadence_fields(ms_dict, q=q, spot_label=spot_label, vol_ctx=vol_ctx, pcr_val=pcr_val)
    ms_dict["pred_override"] = _srv._get_prediction_override(ticker)
    # Liquidity-behavior + news/sentiment (additive; same data also on snapshot rows)
    ms_dict["context_layer"] = {
        "liquidity_behavior": ms.liquidity_behavior,
        "news": ms.news_context,
    }
    _key_level_fields(
        ms_dict, ticker=ticker, consensus_summary=consensus_summary, exposures=exposures,
        diag=diag, em=em, gamma_voids=gamma_voids, kl_expiry_source=kl_expiry_source,
        contracts_use=contracts_use, spot_f=spot_f,
    )
    _signal_fields(ms_dict, price_levels=price_levels, em=em, vs=vs, pp=pp, sweep_score=sweep_score)
    _market_state_mirror_fields(ms_dict, ms)
    _context_fields(ms_dict, ves=ves, mkt_ctx=mkt_ctx, ofs=ofs)
    _confluence_fields(ms_dict, mkt_ctx)
    _runtime_status_fields(ms_dict, ms=ms, ticker=ticker, db_counts=db_counts)
    return ms_dict
