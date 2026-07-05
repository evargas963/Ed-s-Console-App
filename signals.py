"""
signals.py
Full model-stack orchestrator.

REQUIRED STACK ORDER (non-negotiable, enforced in code):
  1. Market Data          — inp (SignalInput)
  1b. Canonical snapshot   — InferenceSnapshotV1 once per tick (MVP row for vol/regime/MC/prediction filters)
  2. Volatility Regime    — classify_volatility_regime(inp, mvp_features=…); policy layer
  3. Market Regime        — classify_regime(inp, rules, mvp_features=…); needs rules for micro
  4. Feature Engineering  — build_fusion_model_overlay_for_stack **once per tick**, reused per horizon
  5. ML Models            — XGB/LSTM/Transformer per horizon slug; shared tabular ingest→overlay→m5 once/tick
  6. Monte Carlo          — monte_carlo.simulate (inside _run_model_stack; horizon bars vary by slug)
  7. Bayesian Fusion      — bayesian_fusion.fuse
  8. Decision Policy       — compute_call (The Call); consumes vol_regime
  9. Risk Engine          — _validate_trade (inside compute_call, after decision)
 10. Position Sizing      — compute_position_size (inside compute_call, after risk)

Rules (Right Now) is computed before Market Regime because regime needs micro structure.
"""
from __future__ import annotations

import json
import math
import logging
import os
from typing import Any, Optional

from signal_types import (
    SignalInput,
    RulesCard,
    PredictiveCard,
    TheCall,
    SignalOutput,
    StackStage,
    StackDecisionPath,
    CanonicalForecast,
)
from rules_engine import compute_rules
from prediction_engine import (
    compute_prediction_core,
    compute_prediction_enrichment,
    _predict_enrichment_enabled,
    _empty_prediction,
)
from call_engine import compute_call
from fusion_contract import fusion_is_authoritative, is_canonical_tradable
from numeric_contract import float_finite_or_none, float_positive_or_none, direction_from_normalized_triplet
from regime_engine import classify_regime
from volatility_regime import classify_volatility_regime
import bayesian_fusion
from ml_horizon import (
    ALL_GOVERNED_HORIZONS,
    PRIMARY_DECISION_HORIZONS,
    SECONDARY_SUPPORT_HORIZONS,
)
from multi_horizon_decision import (
    compute_multi_horizon_synthesis,
    finalize_multi_horizon_bundle,
)
from multi_horizon_ml_bundle import build_multi_horizon_ml_fusion_bundle
from features.stack_integrity_v1 import finalize_stack_integrity_v1, record_stack_degradation

log = logging.getLogger(__name__)


def canonical_forward_probs_for_display(
    canonical: CanonicalForecast,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Withhold forward probability mass on the prediction card when canonical is non-tradable."""
    if not is_canonical_tradable(canonical):
        return None, None, None
    return canonical.probability_up, canonical.probability_down, canonical.probability_flat


def _unavailable_model_namespace():
    """Fail-closed placeholder when a unified-stack ML layer fusion branch is missing or failed."""
    from types import SimpleNamespace

    return SimpleNamespace(
        available=False,
        prob_up=None,
        prob_down=None,
        prob_flat=None,
        dominant_class=None,
        confidence_label=None,
        continuation_support=None,
        reversal_support=None,
    )

try:
    from crash_trace import step as _dstep, step_done as _ddone, trace_crash as _dcrash, _on as _don
except ImportError:
    def _don(): return False
    def _dstep(n, t=""): pass
    def _ddone(n, t=""): pass
    def _dcrash(n, e, t=""): pass


# Live LSTM/XGB/TR inference: ml_predict.run_unified_stack_ml_once (single path per tick; Issue 13).


# ══════════════════════════════════════════════════════════════════════════════
# CANONICAL FORECAST (Issue 13 — one decision truth)
# ══════════════════════════════════════════════════════════════════════════════

def canonical_forecast_from_fusion(fusion) -> CanonicalForecast:
    """
    Build CanonicalForecast from Bayesian fusion posterior (directional triplet).

    When fusion is unavailable or directional probs are missing/invalid, returns a
    max-entropy **placeholder** triplet (1/3 each) with non-tradable ``provenance``.
    Consumers must gate on ``NON_TRADABLE_CANONICAL_PROVENANCE`` — not treat placeholders as signal.
    """
    u = 1.0 / 3.0
    if not fusion_is_authoritative(fusion):
        return CanonicalForecast(
            direction="flat",
            probability_up=u,
            probability_down=u,
            probability_flat=u,
            confidence="low",
            provenance="fusion_unavailable",
        )
    pu_raw = getattr(fusion, "prob_up", None)
    pd_raw = getattr(fusion, "prob_down", None)
    pf_raw = getattr(fusion, "prob_flat", None)
    if pu_raw is None or pd_raw is None or pf_raw is None:
        return CanonicalForecast(
            direction="flat",
            probability_up=u,
            probability_down=u,
            probability_flat=u,
            confidence="low",
            provenance="fusion_directional_missing",
        )
    pu, pd, pf = float(pu_raw), float(pd_raw), float(pf_raw)
    s = pu + pd + pf
    if s > 0:
        pu, pd, pf = pu / s, pd / s, pf / s
    else:
        return CanonicalForecast(
            direction="flat",
            probability_up=u,
            probability_down=u,
            probability_flat=u,
            confidence="low",
            provenance="fusion_directional_invalid",
        )
    d_raw = getattr(fusion, "dominant_direction", None)
    d = str(d_raw).strip().lower() if d_raw is not None else None
    if d not in ("up", "down", "flat"):
        d = direction_from_normalized_triplet(pu, pd, pf)
    conf_raw = getattr(fusion, "fusion_confidence", None)
    conf = str(conf_raw).strip().lower() if conf_raw is not None else None
    if conf not in ("low", "medium", "high"):
        conf = "low"
    return CanonicalForecast(
        direction=d,
        probability_up=pu,
        probability_down=pd,
        probability_flat=pf,
        confidence=conf,
        provenance="bayesian_fusion",
    )


def _debug_canonical_override(canonical: CanonicalForecast, direction: str, source: str) -> CanonicalForecast:
    """Debug/test only: force direction with honest maximum entropy — no synthetic conviction."""
    u = 1.0 / 3.0
    d = (direction or "flat").strip().lower()
    if d not in ("up", "down", "flat"):
        d = "flat"
    src = (source or "unknown").strip() or "unknown"
    return CanonicalForecast(
        direction=d,
        probability_up=u,
        probability_down=u,
        probability_flat=u,
        confidence="low",
        provenance=f"debug_override:{src}",
    )


def _pred_override_allowed() -> bool:
    return os.environ.get("ED_CONSOLE_ALLOW_PRED_OVERRIDE", "").strip() in ("1", "true", "TRUE", "yes", "YES")


def _live_model_stack_horizons(ticker: str) -> tuple[tuple[str, ...], dict[str, dict[str, Any]]]:
    """Primary horizons always run; secondary diagnostics run only with active artifacts."""
    from ml_predict import _model_dir_for_ticker, reset_ml_infer_horizon_slug, set_ml_infer_horizon_slug

    horizons: list[str] = []
    skipped_secondary: dict[str, dict[str, Any]] = {}
    for hz in ALL_GOVERNED_HORIZONS:
        if hz in PRIMARY_DECISION_HORIZONS:
            horizons.append(hz)
            continue
        tok = set_ml_infer_horizon_slug(hz)
        try:
            _model_dir_for_ticker(ticker)
        except FileNotFoundError as exc:
            skipped_secondary[hz] = {
                "horizon_tier": "secondary_support",
                "non_authoritative": True,
                "provenance": "skipped_missing_active_bundle",
                "fusion_available": False,
                "dominant_direction": None,
                "prob_up": None,
                "prob_down": None,
                "prob_flat": None,
                "skip_reason": str(exc),
            }
            continue
        finally:
            reset_ml_infer_horizon_slug(tok)
        horizons.append(hz)
    return tuple(horizons), skipped_secondary


def _log_decision_bundle(
    ticker: str,
    canonical: CanonicalForecast,
    fusion_avail: bool,
    *,
    final_signal: str,
    call_conviction: str,
    size_cue: str,
    gate_summary: str,
    pred_override_applied: bool,
    multi_horizon: Optional[dict] = None,
) -> None:
    """Structured server log for live alignment audits (Issue 13)."""
    try:
        payload = {
            "ticker": ticker,
            "canonical_direction": canonical.direction,
            "canonical_p_up": round(canonical.probability_up, 4),
            "canonical_p_down": round(canonical.probability_down, 4),
            "canonical_p_flat": round(canonical.probability_flat, 4),
            "canonical_confidence": canonical.confidence,
            "canonical_provenance": canonical.provenance,
            "fusion_available": fusion_avail,
            "fusion_directionally_available": fusion_avail,
            "final_signal": final_signal,
            "call_conviction": call_conviction,
            "size_cue": size_cue,
            "gate_summary": gate_summary,
            "pred_override_applied": pred_override_applied,
        }
        if isinstance(multi_horizon, dict):
            payload.update(
                {
                    "mh_primary_horizon": multi_horizon.get("primary_horizon"),
                    "mh_trade_mode": multi_horizon.get("trade_mode"),
                    "mh_alignment_state": multi_horizon.get("alignment_state"),
                    "mh_conflict_level": multi_horizon.get("conflict_level"),
                    "mh_final_bias": multi_horizon.get("final_bias"),
                    "mh_final_tradeable": multi_horizon.get("final_tradeable"),
                    "mh_wait_reason": multi_horizon.get("wait_reason"),
                }
            )
        log.info("DECISION_BUNDLE %s", json.dumps(payload, sort_keys=True))
    except Exception as e:
        log.debug("decision bundle log failed: %s", e)


def _build_calibration_payload(
    *,
    inp: SignalInput,
    ticker: str,
    regime: Any,
    vol_regime: Any,
    fusion: Any,
    canonical: CanonicalForecast,
    pred: PredictiveCard,
    call: TheCall,
    xgb_out: Any,
    lstm_out: Any,
    transformer_out: Any,
    mc_out: Any,
    ml_bundle: dict,
    mh_bundle: Any,
    signal_layer_v1: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Return calibration writer inputs; persistence is owned by the server lifecycle."""
    return {
        "inp": inp,
        "ticker": ticker,
        "canonical_timeframe": getattr(inp, "timeframe", None) or "1m",
        "regime": regime,
        "vol_regime": vol_regime,
        "fusion": fusion,
        "canonical": canonical,
        "pred": pred,
        "call": call,
        "xgb_out": xgb_out,
        "lstm_out": lstm_out,
        "transformer_out": transformer_out,
        "mc_out": mc_out,
        "ml_bundle": ml_bundle if isinstance(ml_bundle, dict) else {},
        "mh_bundle": mh_bundle,
        "signal_layer_v1": signal_layer_v1,
    }


# ══════════════════════════════════════════════════════════════════════════════
# MODEL STACK RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def _spot_for_mc_fusion_adjustment(
    mc_spot_ctx: Optional[dict],
    inference_snapshot_v1: dict,
) -> Optional[float]:
    """Canonical spot for post-fusion MC adjustment (same numeric_contract authority as MC resolve)."""
    if isinstance(mc_spot_ctx, dict) and "spot" in mc_spot_ctx:
        return float_positive_or_none(mc_spot_ctx.get("spot"))
    feats = inference_snapshot_v1.get("features") or {}
    return float_positive_or_none(feats.get("price.spot"))


def production_fusion_payload_for_stack(
    inp,
    rules,
    regime,
    db=None,
    *,
    inference_snapshot_v1: dict,
    fusion_overlay: Optional[dict[str, Any]] = None,
    mc_spot_ctx: Optional[dict[str, Any]] = None,
    mc_context_error: Optional[BaseException] = None,
    xgb_pre_engineering_snapshot: Optional[dict[str, Any]] = None,
    signal_layer_v1=None,
    fusion_tick_cache=None,
    shared_sequence_context=None,
    stack_integrity_events=None,
    meta_tabular_overlay: Optional[dict[str, Any]] = None,
) -> tuple[Any, dict[str, Any]]:
    """Single production fusion path: model stack → bayesian_fusion → MC adjustment.

    Meta participates via ``ml_bundle`` stack_probs → ``mc_model_direction_inputs`` inside
    ``_run_model_stack`` (same as live ``signals._compute_signals_impl``). Returns payload +
    audit dict with **derived** ``stack_layers_scored`` (never hardcoded).
    """
    import bayesian_fusion
    from governed_stack_contract import derive_stack_layers_scored
    from mc_fusion_adjustment import fuse_payload_apply_mc_adjustment

    xgb_out, lstm_out, transformer_out, mc_out, ml_bundle = _run_model_stack(
        inp,
        rules,
        regime,
        db,
        inference_snapshot_v1=inference_snapshot_v1,
        fusion_overlay=fusion_overlay,
        mc_spot_ctx=mc_spot_ctx,
        mc_context_error=mc_context_error,
        xgb_pre_engineering_snapshot=xgb_pre_engineering_snapshot,
        stack_integrity_events=stack_integrity_events,
        shared_sequence_context=shared_sequence_context,
        meta_tabular_overlay=meta_tabular_overlay,
    )
    _ftc = fusion_tick_cache
    if _ftc is None:
        _ftc = bayesian_fusion.build_fusion_tick_cache(regime, rules)
    fusion_payload_base = bayesian_fusion.fuse(
        regime,
        xgb_out,
        lstm_out,
        transformer_out,
        mc_out,
        rules,
        signal_layer_v1=signal_layer_v1,
        fusion_tick_cache=_ftc,
    )
    fusion_payload_full = fusion_payload_base
    try:
        _adj_spot = _spot_for_mc_fusion_adjustment(mc_spot_ctx, inference_snapshot_v1)
        fusion_payload_full = fuse_payload_apply_mc_adjustment(
            fusion_payload_base,
            mc_out,
            _adj_spot,
        )
    except Exception as e:
        if stack_integrity_events is not None:
            record_stack_degradation(
                stack_integrity_events,
                component="mc_fusion_payload_adjustment",
                severity="warning",
                reason="fuse_payload_apply_mc_adjustment_failed",
                exc_type=type(e).__name__,
                detail=str(e),
                fallback_used=True,
                authority_intact=False,
                dedupe_key="mc_fusion_payload_adjustment",
            )
        log.warning(
            "fuse_payload_apply_mc_adjustment failed (unadjusted fusion payload): %s",
            e,
            exc_info=True,
        )
    layers_scored = derive_stack_layers_scored(
        xgb_out=xgb_out,
        lstm_out=lstm_out,
        transformer_out=transformer_out,
        mc_out=mc_out,
        ml_bundle=ml_bundle if isinstance(ml_bundle, dict) else {},
        regime=regime,
        fusion_payload=fusion_payload_full,
    )
    audit = {
        "stack_layers_scored": layers_scored,
        "mc_stack_probability_source": (
            ml_bundle.get("mc_stack_probability_source")
            if isinstance(ml_bundle, dict)
            else None
        ),
        "xgb_out": xgb_out,
        "lstm_out": lstm_out,
        "transformer_out": transformer_out,
        "mc_out": mc_out,
        "ml_bundle": ml_bundle,
    }
    return fusion_payload_full, audit


def production_fusion_triplet_from_payload(fusion_payload) -> list[float]:
    """Directional triplet list [up, down, flat] from a FusionPayload."""
    return [
        float(fusion_payload.prob_up),
        float(fusion_payload.prob_down),
        float(fusion_payload.prob_flat),
    ]


def _compute_display_wall_clock_mc_excursions(
    inp: SignalInput,
    *,
    regime,
    mc_spot_ctx: Optional[dict[str, Any]],
    mc_context_error: Optional[BaseException],
    xgb_out,
    lstm_out,
    transformer_out,
    ml_bundle: Optional[dict[str, Any]],
) -> dict[str, Optional[float]]:
    """
    Display-only wall-clock EFE/EAE for Key Levels (5m / 15m rows).

    Isolated from fusion posterior, sizing, and ML features. Uses
    ``wall_clock_minutes_to_mc_bars`` so BAR_MINUTES=5 maps 5m→1 bar, 15m→3 bars.
    Fail-closed: any blocked input => all keys None (UI omits rows).
    """
    keys = ("mc_efe_5m", "mc_eae_5m", "mc_efe_15m", "mc_eae_15m")
    out: dict[str, Optional[float]] = {k: None for k in keys}
    if mc_context_error is not None or not isinstance(mc_spot_ctx, dict):
        return out
    spot = float_positive_or_none(mc_spot_ctx.get("spot"))
    iv = float_finite_or_none(inp.iv_level)
    if spot is None or iv is None or iv <= 0:
        return out

    import monte_carlo
    from governed_stack_contract import (
        MC_DISPLAY_N_PATHS,
        MC_DISPLAY_WALL_CLOCK_MINUTES,
        mc_model_direction_inputs,
        wall_clock_minutes_to_mc_bars,
    )
    from ml_predict import stack_probs_bundle_key

    _mc_regime = getattr(regime, "primary", None) if regime else None
    if _mc_regime == "unknown":
        _mc_regime = None
    _mc_regime_conf = getattr(regime, "confidence", None) if regime else None
    _spk = stack_probs_bundle_key()
    _m_up, _m_dn, _m_conf, _, _ = mc_model_direction_inputs(
        xgb_out=xgb_out,
        lstm_out=lstm_out,
        transformer_out=transformer_out,
        stack_probs=ml_bundle.get(_spk) if isinstance(ml_bundle, dict) else None,
    )
    garch_full = mc_spot_ctx.get("garch_sigma_bars")

    for minutes in MC_DISPLAY_WALL_CLOCK_MINUTES:
        try:
            bars = wall_clock_minutes_to_mc_bars(minutes)
        except ValueError:
            continue
        garch_slice = None
        if garch_full is not None and len(garch_full) >= bars:
            garch_slice = garch_full[:bars]
        try:
            mc_out = monte_carlo.simulate(
                spot=spot,
                iv=iv,
                horizon_bars=bars,
                n_paths=MC_DISPLAY_N_PATHS,
                call_gamma_wall=mc_spot_ctx.get("call_gamma_wall"),
                put_gamma_wall=mc_spot_ctx.get("put_gamma_wall"),
                em_upper=mc_spot_ctx.get("em_upper"),
                em_lower=mc_spot_ctx.get("em_lower"),
                regime=_mc_regime,
                regime_confidence=_mc_regime_conf,
                realized_vol=mc_spot_ctx.get("realized_vol"),
                atr=mc_spot_ctx.get("atr"),
                model_prob_up=_m_up,
                model_prob_down=_m_dn,
                model_confidence=_m_conf,
                fusion_dominant=None,
                garch_sigma_bars=garch_slice,
            )
        except Exception as e:
            log.warning(
                "display wall-clock MC failed minutes=%s ticker=%s: %s",
                minutes,
                getattr(inp, "ticker", ""),
                e,
                exc_info=True,
            )
            continue
        if not getattr(mc_out, "available", False) or not getattr(mc_out, "simulation_ok", False):
            continue
        suffix = f"{minutes}m"
        out[f"mc_efe_{suffix}"] = float_finite_or_none(
            getattr(mc_out, "expected_favorable_excursion", None)
        )
        out[f"mc_eae_{suffix}"] = float_finite_or_none(
            getattr(mc_out, "expected_adverse_excursion", None)
        )
    return out


def _run_model_stack(
    inp: SignalInput,
    rules: RulesCard,
    regime,
    db=None,
    *,
    inference_snapshot_v1: dict,
    fusion_overlay: Optional[dict[str, Any]] = None,
    mc_spot_ctx: Optional[dict[str, Any]] = None,
    mc_context_error: Optional[BaseException] = None,
    xgb_pre_engineering_snapshot: Optional[dict[str, Any]] = None,
    stack_integrity_events: Optional[list[dict[str, Any]]] = None,
    shared_sequence_context: Any = None,
    meta_tabular_overlay: Optional[dict[str, Any]] = None,
):
    """
    STACK ORDER 4, 5, 6: Feature Engineering → unified stack ML layers → Monte Carlo.

    The xgb/lstm/transformer layers run in parallel as one team (no solo-green MC when team
    cannot authorize). Monte Carlo consumes stack/meta triplet inputs only when the team gate
    passes; otherwise MC fails closed with the rest of the stack.

    When ``fusion_overlay`` is provided, skips ``build_fusion_model_overlay_for_stack`` (caller
    builds it once per tick — includes 1c and all horizon empirical columns from one DB pass).

    When ``mc_spot_ctx`` is provided (or ``mc_context_error`` after a single resolve failure),
    skips redundant ``resolve_monte_carlo_stack_inputs`` per horizon.

    When ``xgb_pre_engineering_snapshot`` is provided (from ``build_xgb_pre_engineering_snapshot_for_tick``),
    ``run_unified_stack_ml_once`` skips repeated MVP→overlay→m5 tabular prep for each horizon.

    When ``shared_sequence_context`` is provided (from ``build_shared_sequence_context``), LSTM and Transformer
    skip redundant ``get_recent_snapshots`` / LSTM window merges for that tick.
    """
    direction_hint = rules.signal
    ticker = getattr(inp, "ticker", "") or ""

    # ── Canonical InferenceSnapshotV1 (MVP) — supplied by caller (single build per tick) ─
    from ml_predict import (
        ParallelRuntimeArtifactError,
        get_ml_infer_horizon_slug,
        run_unified_stack_ml_once,
        stack_probs_bundle_key,
    )
    from prediction_engine import build_fusion_model_overlay_for_stack

    # ── STACK ORDER 4: Fusion model overlay (pred_*, walls, session — no MVP duplicate keys) ─
    if fusion_overlay is not None:
        snap = fusion_overlay
    else:
        try:
            if _don():
                _dstep("model_stack_ml_snapshot", ticker)
            snap = build_fusion_model_overlay_for_stack(
                inp, db, rules, inference_snapshot_v1=inference_snapshot_v1
            )
            if _don():
                _ddone("ml_snapshot", ticker)
        except Exception as e:
            log.warning(
                "build_fusion_model_overlay_for_stack failed (minimal overlay fallback): %s",
                e,
                exc_info=True,
            )
            if stack_integrity_events is not None:
                record_stack_degradation(
                    stack_integrity_events,
                    component="fusion_model_overlay",
                    severity="warning",
                    reason="build_fusion_model_overlay_for_stack_failed",
                    exc_type=type(e).__name__,
                    detail=str(e),
                    fallback_used=True,
                    authority_intact=False,
                )
            snap = {"ticker": getattr(inp, "ticker", "") or ""}

    # ── XGB, LSTM, Transformer — single run_unified_stack_ml_once per tick (Issue 13)
    xgb_out = lstm_out = transformer_out = None

    _spk = stack_probs_bundle_key()
    ml_bundle: dict[str, Any] = {"model_outputs": None, _spk: None}
    try:
        if _don():
            _dstep("model_stack_ml_models", ticker)
        from types import SimpleNamespace
        _once = run_unified_stack_ml_once(
            snap,
            ticker,
            db,
            direction_hint,
            inference_snapshot_v1=inference_snapshot_v1,
            xgb_pre_engineering_snapshot=xgb_pre_engineering_snapshot,
            shared_sequence_context=shared_sequence_context,
            meta_tabular_overlay=meta_tabular_overlay,
        )
        ml_bundle = {
            "model_outputs": _once.get("model_outputs"),
            _spk: _once.get(_spk),
            "movement_head_probs": _once.get("movement_head_probs") or {},
        }
        fused = _once["fusion"]
        if fused.get("xgb"):
            xgb_out = SimpleNamespace(**fused["xgb"])
        else:
            xgb_out = _unavailable_model_namespace()
        if fused.get("lstm"):
            lstm_out = SimpleNamespace(**fused["lstm"])
        else:
            lstm_out = _unavailable_model_namespace()
        if fused.get("transformer"):
            transformer_out = SimpleNamespace(**fused["transformer"])
        else:
            transformer_out = _unavailable_model_namespace()
        if _don():
            _ddone("ml_models", ticker)
    except Exception as e:
        from features.fusion_model_input import FusionModelInputError
        from features.lstm_sequence_input import LstmSequenceInputError, TransformerSequenceInputError
        from features.xgb_model_input import XgbInferenceInputError

        if isinstance(
            e,
            (
                XgbInferenceInputError,
                LstmSequenceInputError,
                TransformerSequenceInputError,
                FusionModelInputError,
                ParallelRuntimeArtifactError,
            ),
        ) or (isinstance(e, ValueError) and "inference_snapshot_v1" in str(e)):
            raise
        if _don():
            _dcrash("run_unified_stack_ml_once", e, ticker)
        log.warning("run_unified_stack_ml_once failed (models marked unavailable): %s", e, exc_info=True)
        if stack_integrity_events is not None:
            record_stack_degradation(
                stack_integrity_events,
                component="run_unified_stack_ml_once",
                severity="warning",
                reason="run_unified_stack_ml_once_failed",
                exc_type=type(e).__name__,
                detail=str(e),
                fallback_used=True,
                authority_intact=False,
                dedupe_key="run_unified_stack_ml_once",
            )
        _fallback = _unavailable_model_namespace()
        xgb_out = lstm_out = transformer_out = _fallback
        ml_bundle = {"model_outputs": None, _spk: None, "movement_head_probs": {}}

    # ── STACK ORDER 6: Monte Carlo (after unified stack ML team; team gate — no solo green) ─
    try:
        if _don():
            _dstep("model_stack_monte_carlo", ticker)
        import monte_carlo
        from features.monte_carlo_stack_input import MonteCarloStackInputError, resolve_monte_carlo_stack_inputs
        from governed_stack_contract import (
            horizon_slug_to_mc_bars,
            mc_model_direction_inputs,
            mc_team_should_fail_closed,
            unified_stack_team_can_authorize,
        )

        if mc_context_error is not None:
            from monte_carlo import MonteCarloOutput

            mc_out = MonteCarloOutput(
                available=False,
                model_version=f"blocked ({mc_context_error})",
            )
        else:
            iv = float_finite_or_none(inp.iv_level)
            _mc_regime = getattr(regime, 'primary', None) if regime else None
            if _mc_regime == 'unknown':
                _mc_regime = None
            _mc_regime_conf = getattr(regime, 'confidence', None) if regime else None
            _mc_ctx = (
                mc_spot_ctx
                if mc_spot_ctx is not None
                else resolve_monte_carlo_stack_inputs(inp, inference_snapshot_v1)
            )
            _hz = get_ml_infer_horizon_slug()
            _mc_bars = horizon_slug_to_mc_bars(_hz)
            _spk2 = stack_probs_bundle_key()
            _stack_probs = ml_bundle.get(_spk2) if isinstance(ml_bundle, dict) else None
            _team_ok, _team_reason = unified_stack_team_can_authorize(
                xgb_out=xgb_out,
                lstm_out=lstm_out,
                transformer_out=transformer_out,
                stack_probs=_stack_probs if isinstance(_stack_probs, dict) else None,
            )
            _m_up, _m_dn, _m_conf, _avail_map, _mc_src = mc_model_direction_inputs(
                xgb_out=xgb_out,
                lstm_out=lstm_out,
                transformer_out=transformer_out,
                stack_probs=_stack_probs,
            )
            if isinstance(ml_bundle, dict):
                ml_bundle["governed_horizon_slug"] = _hz
                ml_bundle["mc_horizon_bars"] = _mc_bars
                ml_bundle["stack_layer_availability"] = dict(_avail_map)
                ml_bundle["mc_stack_probability_source"] = _mc_src
                ml_bundle["mc_model_prob_up"] = _m_up
                ml_bundle["mc_model_prob_down"] = _m_dn
                ml_bundle["mc_model_confidence"] = _m_conf
                ml_bundle["unified_stack_team_ok"] = _team_ok
                ml_bundle["unified_stack_team_reason"] = _team_reason
            if mc_team_should_fail_closed(_team_ok, _mc_src):
                from monte_carlo import MonteCarloOutput

                mc_out = MonteCarloOutput(
                    available=False,
                    model_version=f"blocked (unified_stack_team:{_team_reason})",
                )
            else:
                log.debug(
                    "MC_INPUT em_upper=%s em_lower=%s spot_canonical=%s",
                    inp.em_upper,
                    inp.em_lower,
                    _mc_ctx.get("spot"),
                )
                mc_out = monte_carlo.simulate(
                    spot=_mc_ctx["spot"],
                    iv=iv,
                    horizon_bars=_mc_bars,
                    call_gamma_wall=_mc_ctx.get("call_gamma_wall"),
                    put_gamma_wall=_mc_ctx.get("put_gamma_wall"),
                    em_upper=_mc_ctx.get("em_upper"),
                    em_lower=_mc_ctx.get("em_lower"),
                    regime=_mc_regime,
                    regime_confidence=_mc_regime_conf,
                    realized_vol=_mc_ctx.get("realized_vol"),
                    atr=_mc_ctx.get("atr"),
                    model_prob_up=_m_up,
                    model_prob_down=_m_dn,
                    model_confidence=_m_conf,
                    fusion_dominant=None,
                    garch_sigma_bars=_mc_ctx.get("garch_sigma_bars"),
                )
        if _don():
            _ddone("monte_carlo", ticker)
    except MonteCarloStackInputError as e:
        log.warning("Monte Carlo blocked (canonical): %s", e)
        from monte_carlo import MonteCarloOutput

        mc_out = MonteCarloOutput(available=False, model_version=f"blocked ({e})")
    except Exception as e:
        if _don():
            _dcrash("monte_carlo", e, ticker)
        log.warning("Monte Carlo model stack error: %s", e, exc_info=True)
        if stack_integrity_events is not None:
            record_stack_degradation(
                stack_integrity_events,
                component="monte_carlo_simulate",
                severity="warning",
                reason="monte_carlo_simulate_failed",
                exc_type=type(e).__name__,
                detail=str(e),
                fallback_used=True,
                authority_intact=False,
                dedupe_key="monte_carlo_simulate",
            )
        from monte_carlo import MonteCarloOutput
        mc_out = MonteCarloOutput(available=False, model_version=f"error ({e})")

    return xgb_out, lstm_out, transformer_out, mc_out, ml_bundle


def compute_fusion_policy_flat_for_replay(
    inp: SignalInput,
    db,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """
    Replay the governed per-horizon stack (XGB + LSTM + Transformer → MC → Fusion) without
    compute_prediction / compute_call. Returns flat fused_* column keys, per-horizon error records,
    and stack_integrity_v1 (degradation audit).
    """
    from features.fusion_policy_contract import fusion_payload_to_policy_columns
    from features.inference_snapshot import build_inference_snapshot_v1_from_signal_input
    from ml_predict import reset_ml_infer_horizon_slug, set_ml_infer_horizon_slug

    ticker = getattr(inp, "ticker", "") or ""

    inference_snapshot_v1 = build_inference_snapshot_v1_from_signal_input(inp)
    _mvp = inference_snapshot_v1.get("features")

    replay_integrity_events: list[dict[str, Any]] = []

    signal_layer_v1 = None
    if db is not None:
        try:
            from features.signal_layer_v1 import compute_signal_layer_v1_for_calibration

            _asof = inference_snapshot_v1.get("as_of_ts")
            if _asof is not None:
                signal_layer_v1 = compute_signal_layer_v1_for_calibration(
                    db, ticker, float(_asof), inp
                )
                inference_snapshot_v1["signal_layer_v1"] = signal_layer_v1
        except Exception as e:
            log.warning("signal_layer_v1 replay: %s", e, exc_info=True)
            record_stack_degradation(
                replay_integrity_events,
                component="signal_layer_v1",
                severity="info",
                reason="signal_layer_v1_compute_failed",
                exc_type=type(e).__name__,
                detail=str(e),
                fallback_used=True,
                authority_intact=True,
            )

    rules = compute_rules(inp, mvp_features=_mvp)
    regime = classify_regime(inp, rules, mvp_features=_mvp)

    from prediction_engine import build_fusion_model_overlay_for_stack
    from features.monte_carlo_stack_input import MonteCarloStackInputError, resolve_monte_carlo_stack_inputs

    shared_fusion_overlay: dict[str, Any]
    try:
        shared_fusion_overlay = build_fusion_model_overlay_for_stack(
            inp, db, rules, inference_snapshot_v1=inference_snapshot_v1
        )
    except Exception as e:
        log.warning("replay build_fusion_model_overlay_for_stack failed: %s", e, exc_info=True)
        record_stack_degradation(
            replay_integrity_events,
            component="fusion_model_overlay",
            severity="warning",
            reason="build_fusion_model_overlay_replay_failed",
            exc_type=type(e).__name__,
            detail=str(e),
            fallback_used=True,
            authority_intact=False,
            dedupe_key="fusion_overlay_replay",
        )
        shared_fusion_overlay = {"ticker": getattr(inp, "ticker", "") or ""}

    shared_mc_ctx: Optional[dict[str, Any]] = None
    mc_ctx_err: Optional[BaseException] = None
    try:
        shared_mc_ctx = resolve_monte_carlo_stack_inputs(inp, inference_snapshot_v1)
    except MonteCarloStackInputError as e:
        mc_ctx_err = e

    fusion_policy_flat: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []

    fusion_tick_cache = bayesian_fusion.build_fusion_tick_cache(regime, rules)

    from ml_predict import build_xgb_pre_engineering_snapshot_for_tick

    xgb_pre_eng: Optional[dict[str, Any]] = None
    try:
        xgb_pre_eng = build_xgb_pre_engineering_snapshot_for_tick(
            inference_snapshot_v1, shared_fusion_overlay
        )
    except Exception as e:
        log.warning("build_xgb_pre_engineering_snapshot_for_tick (replay): %s", e, exc_info=True)
        record_stack_degradation(
            replay_integrity_events,
            component="xgb_pre_engineering",
            severity="warning",
            reason="build_xgb_pre_engineering_snapshot_failed",
            exc_type=type(e).__name__,
            detail=str(e),
            fallback_used=True,
            authority_intact=True,
            dedupe_key="xgb_pre_engineering_replay",
        )

    for _hz in ALL_GOVERNED_HORIZONS:
        _tok = set_ml_infer_horizon_slug(_hz)
        try:
            _xgb, _lstm, _tf, _mc, _mb = _run_model_stack(
                inp,
                rules,
                regime,
                db,
                inference_snapshot_v1=inference_snapshot_v1,
                fusion_overlay=shared_fusion_overlay,
                mc_spot_ctx=shared_mc_ctx,
                mc_context_error=mc_ctx_err,
                xgb_pre_engineering_snapshot=xgb_pre_eng,
                stack_integrity_events=replay_integrity_events,
            )
            _fus = bayesian_fusion.fuse(
                regime,
                _xgb,
                _lstm,
                _tf,
                _mc,
                rules,
                signal_layer_v1=signal_layer_v1,
                fusion_tick_cache=fusion_tick_cache,
            )
            try:
                from mc_fusion_adjustment import fuse_payload_apply_mc_adjustment

                _adj_spot = _spot_for_mc_fusion_adjustment(shared_mc_ctx, inference_snapshot_v1)
                _fus = fuse_payload_apply_mc_adjustment(_fus, _mc, _adj_spot)
            except Exception as e:
                log.warning("fuse_payload_apply_mc_adjustment (replay): %s", e, exc_info=True)
                record_stack_degradation(
                    replay_integrity_events,
                    component="mc_fusion_payload_adjustment",
                    severity="warning",
                    reason="fuse_payload_apply_mc_adjustment_failed",
                    exc_type=type(e).__name__,
                    detail=str(e),
                    fallback_used=True,
                    authority_intact=False,
                    dedupe_key="mc_fusion_payload_adjustment",
                )
            fusion_policy_flat.update(fusion_payload_to_policy_columns(_hz, _fus))
        except Exception as e:
            errors.append({"horizon": _hz, "error": repr(e)})
            log.warning("replay fusion hz=%s ticker=%s: %s", _hz, ticker, e)
        finally:
            reset_ml_infer_horizon_slug(_tok)

    return fusion_policy_flat, errors, finalize_stack_integrity_v1(replay_integrity_events)


# ══════════════════════════════════════════════════════════════════════════════
# STACK DECISION PATH
# ══════════════════════════════════════════════════════════════════════════════

def _build_stack_decision_path(xgb_out, lstm_out, transformer_out, mc_out, fusion, call) -> StackDecisionPath:
    """
    Build explicit ordered stack path: XGB → LSTM → Transformer → MC → Fusion → Final Call.
    Monte Carlo is a first-class stage with expansion/containment, skew, directional support.
    """
    def _model_stage(name, out, stage_id) -> StackStage:
        if not getattr(out, "available", False):
            return StackStage(stage_id=stage_id, status="inactive", note=f"{name}: inactive")
        pu = float_finite_or_none(getattr(out, "prob_up", None))
        pd = float_finite_or_none(getattr(out, "prob_down", None))
        pf = float_finite_or_none(getattr(out, "prob_flat", None))
        dom = (
            direction_from_normalized_triplet(pu, pd, pf)
            if pu is not None and pd is not None and pf is not None
            else None
        )
        conf = getattr(out, "confidence_label", None) or getattr(out, "confidence", None)
        prob = getattr(out, "prob_up", None)
        if dom == "down":
            prob = getattr(out, "prob_down", None)
        elif dom == "flat":
            prob = getattr(out, "prob_flat", None)
        note = f"{name}: {dom or '—'} ({conf})"
        return StackStage(stage_id=stage_id, status="active", direction=dom, confidence=conf, probability=prob, note=note)

    # 1. XGBoost
    xgb_stage = _model_stage("XGBoost", xgb_out, "xgboost")

    # 2. LSTM
    lstm_stage = _model_stage("LSTM", lstm_out, "lstm")

    # 3. Transformer
    trans_stage = _model_stage("Transformer", transformer_out, "transformer")

    # 4. Monte Carlo — first-class: expansion vs containment, skew, directional support
    mc_avail = getattr(mc_out, "available", False)
    cont = getattr(mc_out, "containment_prob", None)
    exp = getattr(mc_out, "expansion_prob", None)
    _d_bias_raw = getattr(mc_out, "directional_bias", None)
    d_bias = float(_d_bias_raw) if _d_bias_raw is not None else None
    _t_risk_raw = getattr(mc_out, "tail_risk", None)
    t_risk = float(_t_risk_raw) if _t_risk_raw is not None else None

    if not mc_avail:
        mc_stage = StackStage(stage_id="monte_carlo", status="inactive", note="Monte Carlo: inactive")
    else:
        mode = pct = None
        if exp is not None and cont is not None:
            is_expansion = exp >= cont
            mode = "expansion" if is_expansion else "containment"
            pct = int(100 * (exp if is_expansion else cont))
        elif exp is not None:
            mode = "expansion"
            pct = int(100 * exp)
        elif cont is not None:
            mode = "containment"
            pct = int(100 * cont)

        if d_bias is None:
            skew = None
            mc_dir = None
            support_note = None
        else:
            skew = (
                "upside skew" if d_bias > 1e-4
                else "downside skew" if d_bias < -1e-4
                else "neutral"
            )
            call_sig = getattr(call, "signal", "wait")
            mc_dir = "up" if d_bias > 1e-4 else "down" if d_bias < -1e-4 else "flat"
            supports = (
                (mc_dir == "up" and call_sig == "long")
                or (mc_dir == "down" and call_sig == "short")
                or (mc_dir == "flat" and call_sig == "wait")
            )
            contr = (
                (mc_dir == "up" and call_sig == "short")
                or (mc_dir == "down" and call_sig == "long")
            )
            if supports:
                support_note = "supports stack"
            elif contr:
                support_note = "contradicts stack"
            else:
                support_note = "neutral"

        note_parts = ["Monte Carlo: active"]
        if mode is not None and pct is not None:
            note_parts.append(f"{mode} {pct}%")
        if skew is not None:
            note_parts.append(skew)
        if support_note is not None:
            note_parts.append(support_note)
        note = " | ".join(note_parts)

        prob_val = None
        if t_risk is not None and t_risk > 0:
            prob_val = t_risk
        elif mode == "expansion" and exp is not None:
            prob_val = exp
        elif mode == "containment" and cont is not None:
            prob_val = cont

        mc_stage = StackStage(
            stage_id="monte_carlo",
            status="active",
            direction=mc_dir,
            confidence=(
                "high" if pct is not None and pct > 60
                else "medium" if pct is not None and pct > 40
                else "low"
            ),
            probability=prob_val,
            note=note,
        )

    # 5. Fusion
    fus_avail = fusion_is_authoritative(fusion)
    if not fus_avail:
        fus_stage = StackStage(stage_id="fusion", status="inactive", note="Fusion: inactive")
    else:
        dom = getattr(fusion, "dominant_outcome", None)
        dom_dir = getattr(fusion, "dominant_direction", None)
        prob = getattr(fusion, "dominant_probability", None)
        conf = getattr(fusion, "fusion_confidence", None)
        agree = getattr(fusion, "model_agreement", None)
        agree_pct = int(agree * 100) if agree is not None else None
        dom_label = dom if dom is not None else "—"
        conf_label = conf if conf is not None else "—"
        dir_label = dom_dir if dom_dir is not None else "—"
        prob_pct = int(prob * 100) if prob is not None else None
        agree_suffix = f" | agreement {agree_pct}%" if agree_pct is not None else ""
        prob_suffix = f" @ {prob_pct}%" if prob_pct is not None else ""
        note = f"Fusion: {dom_label} ({conf_label}) | dir={dir_label}{prob_suffix}{agree_suffix}"
        fus_stage = StackStage(
            stage_id="fusion",
            status="active",
            direction=dom_dir,
            confidence=conf,
            probability=prob,
            note=note,
        )

    # 6. Final Call
    call_sig = getattr(call, "signal", "wait")
    call_conv = getattr(call, "conviction", "low")
    if call_sig == "wait":
        call_stage = StackStage(stage_id="final_call", status="active", direction="wait", confidence=call_conv, note=f"Final Call: WAIT ({call_conv})")
    else:
        dir_word = "LONG" if call_sig == "long" else "SHORT"
        call_stage = StackStage(stage_id="final_call", status="active", direction=call_sig, confidence=call_conv, note=f"Final Call: {dir_word} ({call_conv})")

    return StackDecisionPath(
        xgboost=xgb_stage,
        lstm=lstm_stage,
        transformer=trans_stage,
        monte_carlo=mc_stage,
        fusion=fus_stage,
        final_call=call_stage,
    )


# ══════════════════════════════════════════════════════════════════════════════
# SNAPSHOT DICT (for DB — unchanged contract)
# ══════════════════════════════════════════════════════════════════════════════

def _build_snapshot_dict(inp: SignalInput, rules: RulesCard,
                          pred: PredictiveCard, call: TheCall,
                          canonical: CanonicalForecast) -> dict:
    """Build the dict that maps to SnapshotRow for DB insertion."""
    out = {
        "rules_signal":         rules.signal,
        "rules_conviction":     rules.conviction,
        "rules_entry":          call.entry,
        "rules_stop":           call.stop,
        "rules_target":         call.target,
        "rules_summary":        rules.headline + " " + rules.detail,
        "pred_1c_up_prob":      pred.up_prob_1c,
        "pred_1c_down_prob":    pred.down_prob_1c,
        "pred_1c_flat_prob":    pred.flat_prob_1c,
        "pred_5c_up_prob":      pred.up_prob_5c,
        "pred_5c_down_prob":    pred.down_prob_5c,
        "pred_5c_flat_prob":    pred.flat_prob_5c,
        "pred_15c_up_prob":     pred.up_prob_15c,
        "pred_15c_down_prob":   pred.down_prob_15c,
        "pred_15c_flat_prob":   pred.flat_prob_15c,
        "pred_60c_up_prob":     getattr(pred, "up_prob_60c", None),
        "pred_60c_down_prob":   getattr(pred, "down_prob_60c", None),
        "pred_60c_flat_prob":   getattr(pred, "flat_prob_60c", None),
        "pred_model_version":   pred.model_version or "statistical_v1",
        "pred_empirical_confidence": pred.empirical_confidence,
        "pred_samples_used":    pred.samples_used,
        "canonical_direction":  canonical.direction,
        "canonical_confidence": canonical.confidence,
        "canonical_provenance": canonical.provenance,
        "combined_signal":      call.signal,
        "combined_conviction":  call.conviction,
        "rules_pred_agree":     call.rules_pred_agree,
    }
    mh = getattr(pred, "movement_head_probs", None) or {}
    if isinstance(mh, dict):
        for k, v in mh.items():
            if not isinstance(k, str):
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if math.isfinite(fv):
                out[k] = fv
    _si = getattr(pred, "stack_integrity_v1", None)
    if isinstance(_si, dict):
        out["stack_integrity_v1"] = _si
    return out


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def compute_signals(inp: SignalInput, db=None, pred_override: Optional[dict] = None) -> SignalOutput:
    """
    Main entry point. Enforces REQUIRED STACK ORDER:
      1. Market Data (inp)
      2. Volatility Regime
      3. Market Regime
      4. Feature Engineering
      5. ML Models
      6. Monte Carlo
      7. Bayesian Fusion
      8. Decision Policy (The Call)
      9. Risk Engine
     10. Position Sizing

    pred_override: Ignored unless ED_CONSOLE_ALLOW_PRED_OVERRIDE=1. When allowed, forces canonical
    direction only (max-entropy probs, low confidence) for debug — never injects synthetic histograms.
    """
    ticker = getattr(inp, "ticker", "") or ""
    try:
        return _compute_signals_impl(inp, db, ticker, pred_override=pred_override)
    except Exception as e:
        if _don():
            _dcrash("compute_signals", e, ticker)
        raise


def _compute_signals_impl(inp: SignalInput, db=None, ticker: str = "",
                         pred_override: Optional[dict] = None) -> SignalOutput:
    if not ticker:
        ticker = getattr(inp, "ticker", "") or ""
    # ── STACK ORDER 1: Market Data (inp) ──────────────────────────────────────
    # inp = SignalInput, provided by caller (build_market_state)
    # Canonical InferenceSnapshotV1 once — shared by vol/regime policy, fusion overlay, ML, MC.
    from features.inference_snapshot import build_inference_snapshot_v1_from_signal_input

    inference_snapshot_v1 = build_inference_snapshot_v1_from_signal_input(inp)
    _mvp = inference_snapshot_v1.get("features")

    stack_integrity_events: list[dict[str, Any]] = []

    signal_layer_v1 = None
    if db is not None:
        try:
            from features.signal_layer_v1 import compute_signal_layer_v1_for_calibration

            _asof = inference_snapshot_v1.get("as_of_ts")
            if _asof is not None:
                signal_layer_v1 = compute_signal_layer_v1_for_calibration(
                    db, ticker, float(_asof), inp
                )
                inference_snapshot_v1["signal_layer_v1"] = signal_layer_v1
        except Exception as e:
            log.warning(
                "signal_layer_v1 optional enrichment unavailable: %s",
                e,
                exc_info=True,
            )
            record_stack_degradation(
                stack_integrity_events,
                component="signal_layer_v1",
                severity="info",
                reason="signal_layer_v1_compute_failed",
                exc_type=type(e).__name__,
                detail=str(e),
                fallback_used=True,
                authority_intact=True,
            )

    if _don():
        _dstep("signals_vol_regime", ticker)
    # ── STACK ORDER 2: Volatility Regime ──────────────────────────────────────
    # MUST run immediately after market data. Policy layer for downstream interpretation.
    vol_regime = classify_volatility_regime(inp, mvp_features=_mvp)
    if _don():
        _ddone("vol_regime", ticker)

    if _don():
        _dstep("signals_rules_regime", ticker)
    # ── STACK ORDER 3: Market Regime ─────────────────────────────────────────
    # Rules provides micro structure; regime needs it. Order: rules → regime.
    rules = compute_rules(inp, mvp_features=_mvp)   # Right Now / micro structure (canonical MVP zone/VWAP)
    regime = classify_regime(inp, rules, mvp_features=_mvp)
    if _don():
        _ddone("rules_regime", ticker)

    if _don():
        _dstep("signals_model_stack", ticker)
    # ── STACK ORDER 4, 5, 6: Feature Engineering, ML Models, Monte Carlo ──────
    # One stack + fusion per **governed** horizon (slug sets MC horizon bars + model artifacts).
    from features.fusion_policy_contract import fusion_payload_to_policy_columns
    from features.monte_carlo_stack_input import MonteCarloStackInputError, resolve_monte_carlo_stack_inputs
    from ml_predict import (
        build_xgb_pre_engineering_snapshot_for_tick,
        get_ml_infer_horizon_slug,
        ml_bundle_ticker_scope,
        reset_ml_infer_horizon_slug,
        set_ml_infer_horizon_slug,
    )
    from governed_stack_contract import (
        guest_anchor_context_scope,
        remap_prob_sources_for_guest_anchor,
        resolve_guest_anchor_for_ticker,
    )
    from prediction_engine import build_fusion_model_overlay_for_stack

    _guest_anchor = resolve_guest_anchor_for_ticker(ticker)

    # Same-tick similarity dedup (burndown 2026-07-05): the fusion overlay and
    # compute_prediction_core below run an identical tiered get_similar_setups;
    # this ctx lets the second call reuse the first result when — and only when —
    # the exact query args match (prediction_engine._similar_setups_shared).
    _similar_tick_ctx: dict[str, Any] = {}

    shared_fusion_overlay: dict[str, Any]
    try:
        shared_fusion_overlay = build_fusion_model_overlay_for_stack(
            inp, db, rules, inference_snapshot_v1=inference_snapshot_v1,
            similar_ctx=_similar_tick_ctx,
        )
    except Exception as e:
        log.warning(
            "build_fusion_model_overlay_for_stack (shared tick) failed — minimal overlay: %s",
            e,
            exc_info=True,
        )
        record_stack_degradation(
            stack_integrity_events,
            component="fusion_model_overlay",
            severity="warning",
            reason="build_fusion_model_overlay_shared_tick_failed",
            exc_type=type(e).__name__,
            detail=str(e),
            fallback_used=True,
            authority_intact=False,
            dedupe_key="fusion_overlay_shared_tick",
        )
        shared_fusion_overlay = {"ticker": getattr(inp, "ticker", "") or ""}

    shared_mc_ctx: Optional[dict[str, Any]] = None
    mc_ctx_err: Optional[BaseException] = None
    try:
        shared_mc_ctx = resolve_monte_carlo_stack_inputs(inp, inference_snapshot_v1)
    except MonteCarloStackInputError as e:
        mc_ctx_err = e

    fusion_tick_cache = bayesian_fusion.build_fusion_tick_cache(regime, rules)

    xgb_pre_eng: Optional[dict[str, Any]] = None
    try:
        xgb_pre_eng = build_xgb_pre_engineering_snapshot_for_tick(
            inference_snapshot_v1, shared_fusion_overlay
        )
    except Exception as e:
        log.warning(
            "build_xgb_pre_engineering_snapshot_for_tick failed — legacy per-horizon tabular prep: %s",
            e,
            exc_info=True,
        )
        record_stack_degradation(
            stack_integrity_events,
            component="xgb_pre_engineering",
            severity="warning",
            reason="build_xgb_pre_engineering_snapshot_failed",
            exc_type=type(e).__name__,
            detail=str(e),
            fallback_used=True,
            authority_intact=True,
            dedupe_key="xgb_pre_engineering_tick",
        )

    _live_hz = get_ml_infer_horizon_slug()
    fusion_policy_flat: dict[str, Any] = {}
    fusion_by_hz: dict[str, Any] = {}
    secondary_support_fusion_audit: dict[str, Any] = {}
    xgb_out = lstm_out = transformer_out = None
    mc_out = None
    ml_bundle: dict[str, Any] = {}
    fusion = None

    with guest_anchor_context_scope(_guest_anchor), ml_bundle_ticker_scope(
        _guest_anchor.anchor_ticker if _guest_anchor else None
    ):
        shared_sequence_context = None
        _seq_ctx_err: Optional[str] = None
        if db is not None:
            from features.shared_sequence_context import (
                build_guest_wire_sequence_context,
                build_shared_sequence_context,
            )

            _ctx, _seq_ctx_err = build_shared_sequence_context(db, ticker, inference_snapshot_v1)
            if _ctx is not None:
                shared_sequence_context = _ctx
        if (
            shared_sequence_context is None
            and _guest_anchor is not None
            and inference_snapshot_v1
        ):
            from features.shared_sequence_context import build_guest_wire_sequence_context

            _wire_ctx, _wire_err = build_guest_wire_sequence_context(
                inference_snapshot_v1,
                inp=inp,
            )
            if _wire_ctx is not None:
                shared_sequence_context = _wire_ctx
                _seq_ctx_err = None
                log.info(
                    "guest_wire_sequence_context guest=%s anchor=%s (provisional LSTM/TR surface)",
                    ticker,
                    _guest_anchor.anchor_ticker,
                )
            elif _wire_err:
                _seq_ctx_err = _wire_err
        if shared_sequence_context is None and _seq_ctx_err:
            log.warning(
                "shared_sequence_context unavailable — per-horizon LSTM/Transformer DB reads (%s)",
                _seq_ctx_err,
            )
            record_stack_degradation(
                stack_integrity_events,
                component="shared_sequence_context",
                severity="warning",
                reason="shared_sequence_context_build_failed",
                detail=_seq_ctx_err or "",
                fallback_used=True,
                authority_intact=True,
            )

        live_stack_horizons, skipped_secondary_support = _live_model_stack_horizons(ticker)
        secondary_support_fusion_audit.update(skipped_secondary_support)

        for _hz in live_stack_horizons:
            _tok = set_ml_infer_horizon_slug(_hz)
            try:
                _fus, _fusion_audit = production_fusion_payload_for_stack(
                    inp,
                    rules,
                    regime,
                    db,
                    inference_snapshot_v1=inference_snapshot_v1,
                    fusion_overlay=shared_fusion_overlay,
                    mc_spot_ctx=shared_mc_ctx,
                    mc_context_error=mc_ctx_err,
                    xgb_pre_engineering_snapshot=xgb_pre_eng,
                    signal_layer_v1=signal_layer_v1,
                    fusion_tick_cache=fusion_tick_cache,
                    stack_integrity_events=stack_integrity_events,
                    shared_sequence_context=shared_sequence_context,
                )
                fusion_policy_flat.update(fusion_payload_to_policy_columns(_hz, _fus))
                if _hz in SECONDARY_SUPPORT_HORIZONS:
                    secondary_support_fusion_audit[_hz] = {
                        "horizon_tier": "secondary_support",
                        "non_authoritative": True,
                        "provenance": "governed_stack_diagnostics_only",
                        "fusion_available": fusion_is_authoritative(_fus),
                        "dominant_direction": getattr(_fus, "dominant_direction", None),
                        "prob_up": getattr(_fus, "prob_up", None),
                        "prob_down": getattr(_fus, "prob_down", None),
                        "prob_flat": getattr(_fus, "prob_flat", None),
                    }
                if _hz in PRIMARY_DECISION_HORIZONS:
                    fusion_by_hz[_hz] = _fus
                if _hz == _live_hz:
                    xgb_out = _fusion_audit["xgb_out"]
                    lstm_out = _fusion_audit["lstm_out"]
                    transformer_out = _fusion_audit["transformer_out"]
                    mc_out = _fusion_audit["mc_out"]
                    ml_bundle = _fusion_audit.get("ml_bundle") or {}
                    fusion = _fus
            except Exception as e:
                log.warning("signals: per-horizon stack+fusion failed hz=%s ticker=%s: %s", _hz, ticker, e)
                from features.fusion_policy_contract import fusion_policy_columns_horizon_failed

                fusion_policy_flat.update(
                    fusion_policy_columns_horizon_failed(_hz, reason=type(e).__name__)
                )
            finally:
                reset_ml_infer_horizon_slug(_tok)

        _missing_primary = [hz for hz in PRIMARY_DECISION_HORIZONS if hz not in fusion_by_hz]
        if _missing_primary:
            raise RuntimeError(
                f"signals: incomplete primary fusion_by_hz missing={_missing_primary!r} "
                f"ticker={ticker!r} live_hz={_live_hz!r}"
            )

        if fusion is None or xgb_out is None:
            raise RuntimeError(
                f"signals: live horizon stack unavailable (live_hz={_live_hz!r} ticker={ticker!r})"
            )

        if _guest_anchor is not None:
            log.info(
                "guest_anchor_inference guest=%s anchor=%s",
                _guest_anchor.guest_ticker,
                _guest_anchor.anchor_ticker,
            )

    mc_display_excursions = _compute_display_wall_clock_mc_excursions(
        inp,
        regime=regime,
        mc_spot_ctx=shared_mc_ctx,
        mc_context_error=mc_ctx_err,
        xgb_out=xgb_out,
        lstm_out=lstm_out,
        transformer_out=transformer_out,
        ml_bundle=ml_bundle,
    )

    if _don():
        _ddone("model_stack", ticker)

    if _don():
        _dstep("signals_fusion", ticker)
    if _don():
        _ddone("fusion", ticker)

    _n_base_live = sum(
        1 for o in (xgb_out, lstm_out, transformer_out) if getattr(o, "available", False)
    )
    mh_ml_fusion_bundle = build_multi_horizon_ml_fusion_bundle(
        fusion_by_hz,
        live_canonical_horizon_slug=_live_hz,
    )
    if set(mh_ml_fusion_bundle.by_horizon.keys()) != set(PRIMARY_DECISION_HORIZONS):
        raise RuntimeError(
            f"signals: multi_horizon_ml_fusion_bundle incomplete "
            f"ticker={ticker!r} keys={sorted(mh_ml_fusion_bundle.by_horizon.keys())!r}"
        )
    if isinstance(ml_bundle, dict):
        ml_bundle["fusion_policy_snapshot_cols"] = fusion_policy_flat
        ml_bundle["horizon_governance_contract"] = {
            "all_governed_horizons": tuple(ALL_GOVERNED_HORIZONS),
            "primary_decision_horizons": tuple(PRIMARY_DECISION_HORIZONS),
            "secondary_support_horizons": tuple(SECONDARY_SUPPORT_HORIZONS),
        }
        ml_bundle["secondary_support_fusion_audit"] = secondary_support_fusion_audit
        ml_bundle["multi_horizon_ml_fusion_bundle"] = mh_ml_fusion_bundle
        ml_bundle["fusion_contributing_models"] = list(getattr(fusion, "contributing_models", []) or [])
        ml_bundle["fusion_missing_models"] = list(getattr(fusion, "missing_models", []) or [])
        ml_bundle["stack_integrity_events"] = stack_integrity_events

    canonical = canonical_forecast_from_fusion(fusion)
    pred_override_applied = False
    pred_override_source: Optional[str] = None
    if pred_override and isinstance(pred_override, dict):
        direction = pred_override.get("direction")
        if direction in ("up", "flat", "down"):
            if _pred_override_allowed():
                src = str(pred_override.get("source") or "api")
                canonical = _debug_canonical_override(canonical, direction, src)
                pred_override_applied = True
                pred_override_source = src
                if db is not None:
                    try:
                        from db import DB_PATH
                        from override_registry import append_override_record
                        from release_object import get_current_release

                        rel = get_current_release(required=False)
                        append_override_record(
                            ticker=ticker,
                            route="signals._compute_signals_impl",
                            override_source=src,
                            override_direction=direction,
                            override_payload=dict(pred_override),
                            db_path=DB_PATH,
                            release_id=(rel or {}).get("release_id") if rel else None,
                        )
                    except Exception as oreg_exc:
                        log.warning("override_registry append failed: %s", oreg_exc)
                log.warning(
                    "ED_CONSOLE_ALLOW_PRED_OVERRIDE: canonical direction=%s source=%s (empirical histograms unchanged)",
                    direction,
                    src,
                )
            else:
                log.warning(
                    "pred_override ignored for ticker=%s (set ED_CONSOLE_ALLOW_PRED_OVERRIDE=1 for debug only)",
                    ticker,
                )

    if _don():
        _dstep("signals_prediction", ticker)
    pred_core = None
    pred_state = None
    if db:
        pred_core, pred_state = compute_prediction_core(
            inp,
            db,
            regime=regime,
            fusion=fusion,
            rules=rules,
            mc_out=mc_out,
            canonical=canonical,
            ml_bundle=ml_bundle,
            multi_horizon_ml_bundle=mh_ml_fusion_bundle,
            inference_snapshot_v1=inference_snapshot_v1,
            similar_ctx=_similar_tick_ctx,
        )
    else:
        pred_core = _empty_prediction(
            inp,
            canonical=canonical,
            inference_snapshot_v1=inference_snapshot_v1,
            multi_horizon_ml_bundle=mh_ml_fusion_bundle,
        )
    if _don():
        _ddone("prediction", ticker)

    # MH + The Call use hot-path card only (UI enrichment must not change stack decisions).
    pred_for_stack = pred_core

    if _don():
        _dstep("signals_compute_call", ticker)
    mh_syn = compute_multi_horizon_synthesis(inp, pred_for_stack, canonical, mh_ml_fusion_bundle)
    if _guest_anchor is not None:
        mh_syn.tradeable = False
        mh_syn.size_modifier = 0.0
        mh_syn.wait_reason = _guest_anchor.wait_reason
    call = compute_call(
        inp,
        rules,
        pred_for_stack,
        regime=regime,
        fusion=fusion,
        vol_regime=vol_regime,
        canonical=canonical,
        mvp_features=_mvp,
        mh_policy=mh_syn,
    )
    if _don():
        _ddone("compute_call", ticker)

    # Cold path after stack (headline, secondary horizons, eval dashboard, horizon bars).
    if db and pred_state is not None and _predict_enrichment_enabled():
        pred = compute_prediction_enrichment(
            pred_for_stack,
            pred_state,
            inp,
            canonical,
            regime=regime,
            fusion=fusion,
            rules=rules,
            ml_bundle=ml_bundle,
            multi_horizon_ml_bundle=mh_ml_fusion_bundle,
            inference_snapshot_v1=inference_snapshot_v1,
        )
    else:
        pred = pred_core

    if _guest_anchor is not None:
        for _pred_obj in (pred_core, pred):
            if _pred_obj is None:
                continue
            _src = getattr(_pred_obj, "mh_prob_source_by_horizon", None)
            if isinstance(_src, dict):
                _pred_obj.mh_prob_source_by_horizon = remap_prob_sources_for_guest_anchor(_src)

    _call_pre_mh = {
        "signal": call.signal,
        "conviction": call.conviction,
        "validation_passed": getattr(call, "validation_passed", None),
        "validation_summary": (getattr(call, "validation_summary", None) or "")[:200],
        "execution_mode": getattr(call, "execution_mode", None),
        "call_state": getattr(call, "call_state", None),
        "mh_primary_horizon": mh_syn.selected,
        "mh_alignment_state": mh_syn.align.alignment_state,
    }

    # ── Multi-horizon bundle (plan/audit only; policy already applied inside compute_call) ─
    mh_bundle = finalize_multi_horizon_bundle(mh_syn, call, inp, mh_ml_fusion_bundle)
    mh_dec = mh_bundle.final_decision

    if _don():
        _dstep("signals_post_stack", ticker)
    stack_path = _build_stack_decision_path(xgb_out, lstm_out, transformer_out, mc_out, fusion, call)
    snapshot = _build_snapshot_dict(inp, rules, pred, call, canonical)
    if _don():
        _ddone("post_stack", ticker)

    from fusion_contract import fusion_has_tradable_direction

    _log_decision_bundle(
        ticker,
        canonical,
        fusion_has_tradable_direction(fusion),
        final_signal=call.signal,
        call_conviction=call.conviction,
        size_cue=call.size_cue,
        gate_summary=call.validation_summary or "",
        pred_override_applied=pred_override_applied,
        multi_horizon={
            "primary_horizon": mh_dec.primary_horizon,
            "trade_mode": mh_dec.trade_mode,
            "alignment_state": mh_dec.alignment_state,
            "conflict_level": mh_dec.alignment_report.conflict_level,
            "final_bias": mh_dec.final_bias,
            "final_tradeable": mh_dec.final_tradeable,
            "wait_reason": mh_dec.wait_reason,
        },
    )

    calibration_payload = _build_calibration_payload(
        inp=inp,
        ticker=ticker,
        regime=regime,
        vol_regime=vol_regime,
        fusion=fusion,
        canonical=canonical,
        pred=pred,
        call=call,
        xgb_out=xgb_out,
        lstm_out=lstm_out,
        transformer_out=transformer_out,
        mc_out=mc_out,
        ml_bundle=ml_bundle,
        mh_bundle=mh_bundle,
        signal_layer_v1=signal_layer_v1,
    )

    try:
        from live_pipeline_diag import emit_compute_signals_diag

        emit_compute_signals_diag(
            ticker=ticker,
            xgb_out=xgb_out,
            lstm_out=lstm_out,
            transformer_out=transformer_out,
            mc_out=mc_out,
            fusion=fusion,
            canonical=canonical,
            pred=pred,
            call_pre_mh=_call_pre_mh,
            call_post_mh={
                "signal": call.signal,
                "conviction": call.conviction,
                "validation_passed": getattr(call, "validation_passed", None),
                "validation_summary": (getattr(call, "validation_summary", None) or "")[:200],
                "execution_mode": getattr(call, "execution_mode", None),
                "size_cue": getattr(call, "size_cue", None),
            },
            mh_bundle=mh_bundle,
            ml_bundle=ml_bundle,
        )
    except Exception:
        # Optional dev-only diag hook; failures here must not affect the decision path.
        log.debug("emit_compute_signals_diag failed", exc_info=True)

    return SignalOutput(
        rules=rules,
        predictive=pred,
        call=call,
        snapshot=snapshot,
        canonical_forecast=canonical,
        regime=regime,
        fusion=fusion,
        stack_decision_path=stack_path,
        vol_regime=vol_regime,
        pred_override_source=pred_override_source,
        multi_horizon_bundle=mh_bundle,
        calibration_payload=calibration_payload,
        mc_display_excursions=mc_display_excursions,
        guest_anchor_active=_guest_anchor is not None,
        guest_anchor_weights_ticker=(
            _guest_anchor.anchor_ticker if _guest_anchor is not None else None
        ),
        guest_anchor_affiliation=(
            _guest_anchor.affiliation if _guest_anchor is not None else None
        ),
        guest_anchor_rationale=(
            _guest_anchor.rationale if _guest_anchor is not None else None
        ),
    )
