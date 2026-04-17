"""
prediction_engine.py
Extracted Phase 1 Card 2 logic from signals.py
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
from datetime import timezone, timedelta
from typing import Any, Dict, List, Optional

from math_exposure import (
    compute_probs, dominant_direction, determine_confidence,
    compute_percentile_range, classify_reversal_risk, is_pin_zone,
    MIN_SAMPLES_STATISTICAL, MIN_SAMPLES_CONFIDENT, APPROACH_PTS,
    REVERSAL_RISK_LOW_MAX, REVERSAL_RISK_MOD_MAX,
)
from signal_types import SignalInput, PredictiveCard, CanonicalForecast
from timeframe_config import CANONICAL_TIMEFRAME
from features.regime_mvp_context import mvp_spot, mvp_zone, mvp_vwap_side
from db import (
    similarity_empirically_viable,
    similarity_labeled_counts,
    similarity_tier_stop_viable,
)

from ml_horizon import PRIMARY_DECISION_HORIZONS
from features.stack_integrity_v1 import (
    finalize_stack_integrity_v1,
    merge_stack_integrity_events,
    record_stack_degradation,
)

log = logging.getLogger(__name__)
ET = timezone(timedelta(hours=-5))

_TIER_LABELS: dict[int, str] = {
    1: "exact setup + session + VIX match",
    2: "zone + VWAP + session + VIX + proximity",
    3: "zone + VWAP + session + VIX match",
    4: "zone + VWAP + VIX match",
    5: "zone + VWAP match",
    6: "zone match",
    7: "general dataset",
}


@dataclass
class PredictionEnrichmentState:
    """Cold-path inputs for compute_prediction_enrichment (single similar-set pass; no second DB query)."""

    similar: list
    avg_move: dict
    lit_1c: tuple
    lit_5c: tuple
    lit_15c: tuple
    lit_60c: tuple
    match_tier: int
    spot: float
    mvp: dict


def _predict_enrichment_enabled() -> bool:
    return os.environ.get("ED_PREDICT_ENRICHMENT", "1").strip().lower() not in ("0", "false", "no")


def _as_of_ts_utc_for_similarity(
    inp: SignalInput,
    inference_snapshot_v1: Optional[Dict[str, Any]],
) -> Optional[float]:
    """
    Rows in snapshots used for empirical similarity must not be from the future relative to
    the decision instant. Prefer InferenceSnapshotV1.as_of_ts (aligned with refresh_ts_utc),
    then SignalInput.refresh_ts_utc. None disables SQL cutoff (legacy callers/tests only).
    """
    ts = None
    if inference_snapshot_v1:
        ts = inference_snapshot_v1.get("as_of_ts")
    if ts is None:
        ts = getattr(inp, "refresh_ts_utc", None)
    if ts is None:
        return None
    try:
        return float(ts)
    except (TypeError, ValueError):
        return None


def _count_labeled(similar: list, outcome_col: str) -> int:
    return sum(
        1 for r in similar
        if r.get(outcome_col) in ("up", "down", "flat")
    )


def _literal_empirical_horizon(
    similar: list,
    outcome_col: str,
    forward_bars: int,
) -> tuple[Optional[dict], str, str, int]:
    """
    Literal product horizons: empirical histogram from outcome_* when the **current**
    similar set has enough labeled rows; otherwise probabilities are withheld (None),
    re-evaluated every cycle — no sticky activation.
    """
    n = _count_labeled(similar, outcome_col)
    if n < MIN_SAMPLES_STATISTICAL:
        return (
            None,
            f"insufficient_labeled_{outcome_col}",
            (
                f"Insufficient labeled {outcome_col} in current match set ({n} rows; need "
                f"{MIN_SAMPLES_STATISTICAL}) — empirical probabilities withheld for this horizon."
            ),
            n,
        )
    p = compute_probs(similar, outcome_col)
    return (
        p,
        f"empirical_{outcome_col}",
        f"{forward_bars}×1m canonical bar closes vs bar anchor ({outcome_col}).",
        n,
    )


def _tri_probs(p: Optional[dict]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    if p is None:
        return None, None, None
    return (
        float(p.get("up", 0.33)),
        float(p.get("down", 0.33)),
        float(p.get("flat", 0.34)),
    )


def _norm_triplet_floats(u: float, d: float, f: float) -> tuple[float, float, float]:
    s = u + d + f
    if s <= 0:
        t = 1.0 / 3.0
        return t, t, t
    return u / s, d / s, f / s


def _overlay_multi_horizon_ml_on_product_triplets(
    empirical: dict[str, tuple[Optional[float], Optional[float], Optional[float]]],
    multi_horizon_ml_bundle: Optional[Any],
) -> tuple[
    dict[str, tuple[Optional[float], Optional[float], Optional[float]]],
    dict[str, str],
    List[dict[str, Any]],
]:
    """
    Per-horizon fusion is primary; empirical DB histograms are optional support (blend) or sole
    source when fusion is unavailable for that horizon.

    Third return value: structured degradation events when MH bundle cannot be applied
    (never silent — see stack_integrity_v1).
    """
    integrity_events: List[dict[str, Any]] = []
    out: dict[str, tuple[Optional[float], Optional[float], Optional[float]]] = {
        hz: empirical[hz] for hz in PRIMARY_DECISION_HORIZONS
    }
    src: dict[str, str] = {hz: "empirical_histogram" for hz in PRIMARY_DECISION_HORIZONS}
    if multi_horizon_ml_bundle is None:
        return out, src, integrity_events
    by_h: Any = {}
    try:
        _raw = getattr(multi_horizon_ml_bundle, "by_horizon", None)
        by_h = _raw if isinstance(_raw, dict) else {}
        if _raw is not None and not isinstance(_raw, dict):
            record_stack_degradation(
                integrity_events,
                component="mh_ml_product_overlay",
                severity="warning",
                reason="by_horizon_not_a_dict",
                authority_intact=False,
                detail="expected mapping horizon -> snapshot",
            )
            log.warning(
                "MH ML overlay: multi_horizon_ml_bundle.by_horizon is not a dict — using empirical-only triplets."
            )
    except Exception as e:
        # Broad catch: custom descriptors/__getattribute__ on bundle types may raise outside AttributeError.
        record_stack_degradation(
            integrity_events,
            component="mh_ml_product_overlay",
            severity="error",
            reason="multi_horizon_ml_bundle_by_horizon_access_failed",
            exc_type=type(e).__name__,
            authority_intact=False,
            fallback_used=True,
            detail=str(e),
        )
        log.warning(
            "MH ML overlay: failed to read by_horizon from multi_horizon_ml_bundle — empirical-only primary horizons.",
            exc_info=True,
        )
        by_h = {}
    try:
        w_sup = float(os.environ.get("ED_MH_EMPIRICAL_SUPPORT", "0.15"))
    except ValueError:
        w_sup = 0.15
    w_sup = max(0.0, min(1.0, w_sup))
    for hz in PRIMARY_DECISION_HORIZONS:
        snap = by_h.get(hz)
        eu, ed, ef = empirical[hz]
        if snap is None or not getattr(snap, "fusion_available", False):
            out[hz] = (eu, ed, ef)
            src[hz] = "empirical_histogram"
            continue
        mu = float(getattr(snap, "prob_up", 1.0 / 3.0))
        md = float(getattr(snap, "prob_down", 1.0 / 3.0))
        mf = float(getattr(snap, "prob_flat", 1.0 / 3.0))
        mu, md, mf = _norm_triplet_floats(mu, md, mf)
        emp_ok = all(x is not None for x in (eu, ed, ef))
        if emp_ok and w_sup > 0.0:
            u = (1.0 - w_sup) * mu + w_sup * float(eu)
            d = (1.0 - w_sup) * md + w_sup * float(ed)
            fl = (1.0 - w_sup) * mf + w_sup * float(ef)
            u, d, fl = _norm_triplet_floats(u, d, fl)
            out[hz] = (u, d, fl)
            src[hz] = "empirical_support_blend"
        else:
            out[hz] = (mu, md, mf)
            src[hz] = "fusion_ml_primary"
    return out, src, integrity_events


def _avg_outcome_pts(similar: list, pts_col: str) -> Optional[float]:
    pts = [float(r[pts_col]) for r in similar if r.get(pts_col) is not None]
    if len(pts) < 5:
        return None
    return round(sum(pts) / len(pts), 2)


def _pack_horizon_row(
    probs: Optional[dict],
    source: str,
    horizon_note: str,
    *,
    method: str,
    empirical_forward_bars: Optional[int],
    ui_label: Optional[str] = None,
    labeled_count: int = 0,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "source": source,
        "method": method,
        "horizon_note": horizon_note,
        "empirical_forward_bars": empirical_forward_bars,
    }
    if ui_label is not None:
        row["ui_label"] = ui_label
    if probs is None:
        row["up"] = None
        row["down"] = None
        row["flat"] = None
        row["labeled_count"] = labeled_count
        row["min_samples_required"] = MIN_SAMPLES_STATISTICAL
    else:
        row["up"] = float(probs.get("up", 0.33))
        row["down"] = float(probs.get("down", 0.33))
        row["flat"] = float(probs.get("flat", 0.34))
    return row


def _build_horizon_prob_bars(
    lit_1c: tuple[Optional[dict], str, str, int],
    lit_5c: tuple[Optional[dict], str, str, int],
    lit_15c: tuple[Optional[dict], str, str, int],
    lit_60c: tuple[Optional[dict], str, str, int],
) -> dict[str, Any]:
    """Per-horizon empirical bars; insufficient ⇒ null probs + counts (no placeholder thirds in UI)."""
    _emp_hist = "historical_empirical_histogram_from_db"
    p1, s1, n1, c1 = lit_1c
    p5, s5, n5, c5 = lit_5c
    p15, s15, n15, c15 = lit_15c
    p60, s60, n60, c60 = lit_60c
    return {
        "1m": _pack_horizon_row(
            p1, s1, n1, method=_emp_hist, empirical_forward_bars=1, labeled_count=c1
        ),
        "5m": _pack_horizon_row(
            p5, s5, n5, method=_emp_hist, empirical_forward_bars=5, labeled_count=c5
        ),
        "15m": _pack_horizon_row(
            p15, s15, n15, method=_emp_hist,
            empirical_forward_bars=15 if p15 is not None else None,
            ui_label="15m", labeled_count=c15,
        ),
        "60m": _pack_horizon_row(
            p60, s60, n60, method=_emp_hist,
            empirical_forward_bars=60 if p60 is not None else None,
            ui_label="60m", labeled_count=c60,
        ),
    }

def _timeframe_reads(inp: SignalInput, *, mvp_features: dict) -> dict:
    """
    Generate structural read for 15m and 60m based on available data.
    Zone / VWAP semantics come only from canonical MVP (``mvp_features``), not SignalInput.
    """
    reads = {}

    zone = mvp_zone(mvp_features)
    vwap_side = mvp_vwap_side(mvp_features)
    charm_dir = (inp.charm_direction or "").lower()

    # 15-minute structure approximation
    if is_pin_zone(zone) and vwap_side == "below":
        reads["15m"] = "Bearish structure — lower highs, below VWAP"
    elif is_pin_zone(zone) and vwap_side == "above":
        reads["15m"] = "Bullish structure — holding above VWAP"
    elif zone == "breakout":
        reads["15m"] = "Breakout structure — price above gamma walls"
    elif zone == "breakdown":
        reads["15m"] = "Breakdown structure — price below gamma walls"
    else:
        reads["15m"] = "Structure unclear — wait for levels"

    # ~60m context from charm + zone (product label 60m, not "1h")
    if charm_dir == "selling" and (is_pin_zone(zone) or zone == "breakdown"):
        reads["60m"] = "Downward drift likely into close (charm selling)"
    elif charm_dir == "buying" and (is_pin_zone(zone) or zone == "breakout"):
        reads["60m"] = "Upward drift likely into close (charm buying)"
    elif zone == "breakout":
        reads["60m"] = "Uptrend — don't hold shorts too long"
    elif zone == "breakdown":
        reads["60m"] = "Downtrend — don't hold longs"
    else:
        reads["60m"] = "No clear trend — day trading range"

    return reads

def _prediction_headline(
    inp: SignalInput,
    mvp_features: dict,
    dom_dir: str,
    dom_prob: float,
    n_used: int,
    confidence: str,
    avg_5c: Optional[float] = None,
    using_fallback: bool = False,
) -> str:
    """
    Plain English prediction headline (canonical zone via ``mvp_features``; unused legacy path).
    """
    zone = mvp_zone(mvp_features)
    pct   = int(dom_prob * 100)

    # No similar matches — fallback to broad dataset
    if using_fallback and n_used > 0:
        return (
            f"No close matches for this exact setup yet ({n_used} general setups analyzed). "
            f"Probabilities below are from the broader dataset — not specific to this situation."
        )

    # Data exists but market is balanced — probabilities near 33%
    if confidence == "low" and n_used >= MIN_SAMPLES_STATISTICAL:
        if avg_5c is not None:
            dir_word = "lower" if avg_5c < 0 else "higher"
            return (
                f"Market is balanced here. In {n_used} similar setups, "
                f"price drifted {dir_word} by {abs(avg_5c):.1f} pts on average over the 5m window — "
                f"no strong directional edge."
            )
        return (
            f"No strong edge in this setup. In {n_used} similar situations, "
            f"price split roughly evenly between up ({int(dom_prob*100)}%), down, and flat."
        )

    dir_words = {"up": "moved higher", "down": "moved lower", "flat": "stayed flat"}
    dir_word  = dir_words.get(dom_dir, "moved")

    # Strong or medium edge
    if is_pin_zone(zone):
        wall = inp.put_gamma_wall if dom_dir == "down" else inp.call_gamma_wall
        wall_str = f" toward {wall:.2f}" if wall else ""
        move_str = f", averaging {avg_5c:+.1f} pts over the 5m window" if avg_5c is not None else ""
        return (
            f"In {n_used} similar ceiling setups, price {dir_word} {pct}% of the time"
            f"{wall_str}{move_str}."
        )

    if zone in ("breakout", "breakdown"):
        move_str = f", avg {avg_5c:+.1f} pts (5m)" if avg_5c is not None else ""
        return f"In {n_used} similar {zone} setups, price {dir_word} {pct}% of the time{move_str}."

    move_str = f" Avg move: {avg_5c:+.1f} pts over the 5m window." if avg_5c is not None else ""
    return f"In {n_used} similar setups, price {dir_word} {pct}% of the time next candle.{move_str}"

def _get_all_recent(
    inp: SignalInput, db, n: int = 100, *, as_of_ts_utc: Optional[float] = None
) -> list:
    """Fallback: get all recent snapshots when similar-setup lookup is thin."""
    try:
        return db.get_recent_snapshots(
            inp.ticker,
            inp.timeframe,
            n=n,
            filled_only=True,
            as_of_ts_utc=as_of_ts_utc,
        )
    except Exception:
        return []


def build_fusion_model_overlay_for_stack(
    inp: SignalInput,
    db,
    rules=None,
    *,
    inference_snapshot_v1: dict,
) -> dict:
    """
    Non-MVP overlay for the ML stack: pred_*, walls, session, cross-asset, candle context, etc.

    MVP tabular fields (spot, zone, nearest_*, vwap_*, spread, net_gamma, liquidity scores) come
    only from InferenceSnapshotV1 on the XGB path — this dict must not contain those keys.
    Similar-setup DB filters use canonical features from `inference_snapshot_v1`, not raw SignalInput.
    """
    from features.fusion_model_input import (
        assert_fusion_overlay_has_no_mvp_keys,
        similar_setup_filters_from_canonical_features,
        strip_mvp_keys_from_fusion_overlay,
        validate_inference_snapshot_for_fusion_stack,
    )

    validate_inference_snapshot_for_fusion_stack(inference_snapshot_v1)
    _filters = similar_setup_filters_from_canonical_features(inference_snapshot_v1["features"])

    probs_1c = probs_5c = probs_3c = probs_8c = probs_13c = None
    probs_15m = probs_60m = None
    _asof_sim = _as_of_ts_utc_for_similarity(inp, inference_snapshot_v1)
    if db is not None:
        try:
            similar = db.get_similar_setups(
                ticker=inp.ticker,
                timeframe=inp.timeframe or CANONICAL_TIMEFRAME,
                zone=_filters["zone"],
                vwap_side=_filters["vwap_side"],
                nearest_above_dist=_filters["nearest_above_dist"],
                nearest_below_dist=_filters["nearest_below_dist"],
                as_of_ts_utc=_asof_sim,
            )
            probs_1c, _, _, _ = _literal_empirical_horizon(similar, "outcome_1c", 1)
            probs_3c, _, _, _ = _literal_empirical_horizon(similar, "outcome_3c", 3)
            probs_5c, _, _, _ = _literal_empirical_horizon(similar, "outcome_5c", 5)
            probs_8c, _, _, _ = _literal_empirical_horizon(similar, "outcome_8c", 8)
            probs_13c, _, _, _ = _literal_empirical_horizon(similar, "outcome_13c", 13)
            probs_15m, _, _, _ = _literal_empirical_horizon(similar, "outcome_15c", 15)
            probs_60m, _, _, _ = _literal_empirical_horizon(similar, "outcome_60c", 60)
        except Exception as e:
            log.debug("build_fusion_model_overlay_for_stack: DB lookup failed: %s", e)
            probs_1c = probs_3c = probs_5c = probs_8c = probs_13c = None
            probs_15m = probs_60m = None
    u1, d1, f1 = _tri_probs(probs_1c)
    u3, d3, f3 = _tri_probs(probs_3c)
    u5, d5, f5 = _tri_probs(probs_5c)
    u8, d8, f8 = _tri_probs(probs_8c)
    u13, d13, f13 = _tri_probs(probs_13c)
    u15, d15, f15 = _tri_probs(probs_15m)
    u60, d60, f60 = _tri_probs(probs_60m)

    _cvol = getattr(inp, "candle_volume", None)
    if _cvol is None and getattr(inp, "candles_1m", None):
        bars = inp.candles_1m
        if bars:
            _last_bar = bars[-1]
            _cvol = getattr(_last_bar, "volume", None)
            try:
                _cvol = float(_cvol) if _cvol is not None else None
            except (TypeError, ValueError):
                _cvol = None
    if _cvol is None and getattr(inp, "candles_5m", None):
        bars = inp.candles_5m   # 5m fallback when 1m unavailable
        if bars:
            _last_bar = bars[-1]
            _cvol = getattr(_last_bar, "volume", None)
            try:
                _cvol = float(_cvol) if _cvol is not None else None
            except (TypeError, ValueError):
                _cvol = None
    _imb = getattr(inp, "flow_imbalance", None) or getattr(inp, "bid_ask_imbalance", None)
    _imb = float(_imb) if _imb is not None and isinstance(_imb, (int, float)) else None
    _csig = getattr(rules, "signal", None) if rules else None
    _cconv = getattr(rules, "conviction", None) if rules else None
    _mins_open = (inp.et_hour - 9) * 60 + (inp.et_minute - 30) if inp.et_hour is not None and inp.et_minute is not None else None
    if _mins_open is not None and _mins_open < 0:
        _mins_open = 0.0

    raw = {
        "ticker": inp.ticker,
        "et_hour": inp.et_hour, "et_minute": inp.et_minute,
        "candle_body_pts": inp.candle_body_pts,
        "candle_range_pts": inp.candle_range_pts,
        "zone_since_bars": inp.zone_since_bars_1m or inp.zone_since_bars,  # 1m execution-layer (key kept for model compat)
        "dist_call_gamma_wall": inp.dist_call_gamma_wall,
        "dist_put_gamma_wall": inp.dist_put_gamma_wall,
        "dist_call_delta_wall": inp.dist_call_delta_wall,
        "dist_put_delta_wall": inp.dist_put_delta_wall,
        "dist_gamma_inflection": inp.dist_gamma_inflection,
        "dist_delta_inflection": inp.dist_delta_inflection,
        "dist_call_oi_wall": inp.dist_call_oi_wall,
        "dist_put_oi_wall": inp.dist_put_oi_wall,
        "dist_call_vanna_wall": getattr(inp, "dist_call_vanna_wall", None),
        "dist_put_vanna_wall": getattr(inp, "dist_put_vanna_wall", None),
        "pin_width_pts": inp.pin_width_pts,
        "net_delta": inp.net_delta,
        "net_vanna": inp.net_vanna, "charm_net": inp.charm_net,
        "iv_level": inp.iv_level,
        "put_call_oi_ratio": inp.put_call_oi_ratio,
        "spy_chg_pct": inp.spy_chg_pct,
        "qqq_chg_pct": inp.qqq_chg_pct,
        "iwm_chg_pct": inp.iwm_chg_pct,
        "spy_weighted_push": inp.spy_weighted_push,
        "qqq_weighted_push": getattr(inp, "qqq_weighted_push", None),
        "iwm_weighted_push": inp.iwm_weighted_push,
        "vix_level": inp.vix_level, "vix_vs_prev": inp.vix_vs_prev,
        "prev_zone": inp.prev_zone,
        "candle_direction": inp.candle_direction,
        "session_bucket": inp.session_bucket,
        "vix_bucket": inp.vix_bucket,
        "charm_direction": inp.charm_direction,
        "charm_magnitude": inp.charm_magnitude,
        "iv_direction": inp.iv_direction,
        "qqq_vs_spy": inp.qqq_vs_spy,
        "iwm_risk_signal": inp.iwm_risk_signal,
        "candle_volume": _cvol,
        "bid_ask_imbalance": _imb,
        "combined_signal": _csig,
        "combined_conviction": _cconv,
        "atr": getattr(inp, "atr", None),
        "iv_rank": getattr(inp, "iv_rank", None),
        "smart_money_score": getattr(inp, "smart_money_score", None),
        "breakout_score": getattr(inp, "breakout_score", None),
        "pin_score": getattr(inp, "pin_score", None),
        "minutes_since_open": _mins_open,
        "pred_1c_up_prob": u1,
        "pred_1c_down_prob": d1,
        "pred_1c_flat_prob": f1,
        "pred_5c_up_prob": u5,
        "pred_5c_down_prob": d5,
        "pred_5c_flat_prob": f5,
        "pred_3c_up_prob": u3,
        "pred_3c_down_prob": d3,
        "pred_3c_flat_prob": f3,
        "pred_8c_up_prob": u8,
        "pred_8c_down_prob": d8,
        "pred_8c_flat_prob": f8,
        "pred_13c_up_prob": u13,
        "pred_13c_down_prob": d13,
        "pred_13c_flat_prob": f13,
        "pred_15c_up_prob": u15,
        "pred_15c_down_prob": d15,
        "pred_15c_flat_prob": f15,
        "pred_60c_up_prob": u60,
        "pred_60c_down_prob": d60,
        "pred_60c_flat_prob": f60,
    }
    out = strip_mvp_keys_from_fusion_overlay(raw)
    assert_fusion_overlay_has_no_mvp_keys(out)
    return out

def _empty_prediction(
    inp: SignalInput,
    canonical: CanonicalForecast,
    *,
    inference_snapshot_v1: dict,
    multi_horizon_ml_bundle: Optional[Any] = None,
) -> PredictiveCard:
    """Return card when no DB — no empirical histograms; forward fields still from canonical fusion."""
    mvp = inference_snapshot_v1.get("features") or {}
    msg = "Database not connected — historical match statistics unavailable."
    nd = (None, "no_database", msg, 0)
    u = 1.0 / 3.0
    _mh_empirical_product = {
        "1c": (u, u, u),
        "5c": (u, u, u),
        "15c": (u, u, u),
        "60c": (u, u, u),
    }
    _tri_f, mh_prob_source_by_horizon, _mh_overlay_events = _overlay_multi_horizon_ml_on_product_triplets(
        _mh_empirical_product, multi_horizon_ml_bundle
    )
    _stack_integrity_v1 = finalize_stack_integrity_v1(_mh_overlay_events)
    u1, d1, f1 = _tri_f["1c"]
    u5, d5, f5 = _tri_f["5c"]
    u15, d15, f15 = _tri_f["15c"]
    u60, d60, f60 = _tri_f["60c"]
    return PredictiveCard(
        headline=msg,
        prediction_dir="none",
        prediction_target=None,
        historical_5c_dominant_dir="flat",
        historical_5c_dominant_prob=0.0,
        empirical_confidence="low",
        forward_direction=canonical.direction,
        forward_prob_up=canonical.probability_up,
        forward_prob_down=canonical.probability_down,
        forward_prob_flat=canonical.probability_flat,
        forward_confidence=canonical.confidence,
        forward_provenance=canonical.provenance,
        samples_used=0,
        model_note="Connect the database for empirical histograms; per-horizon fusion fills product horizons when available.",
        timeframe_reads=_timeframe_reads(inp, mvp_features=mvp),
        horizon_prob_bars=_build_horizon_prob_bars(nd, nd, nd, nd),
        fusion_policy_snapshot_cols=None,
        up_prob_1c=u1,
        down_prob_1c=d1,
        flat_prob_1c=f1,
        up_prob_5c=u5,
        down_prob_5c=d5,
        flat_prob_5c=f5,
        up_prob_15c=u15,
        down_prob_15c=d15,
        flat_prob_15c=f15,
        up_prob_60c=u60,
        down_prob_60c=d60,
        flat_prob_60c=f60,
        mh_empirical_product_triplets=dict(_mh_empirical_product),
        mh_prob_source_by_horizon=dict(mh_prob_source_by_horizon),
        stack_integrity_v1=_stack_integrity_v1,
    )


def compute_prediction_core(
    inp: SignalInput,
    db,
    regime=None,
    fusion=None,
    rules=None,
    mc_out=None,
    canonical: Optional[CanonicalForecast] = None,
    ml_bundle: Optional[Dict[str, Any]] = None,
    *,
    multi_horizon_ml_bundle: Optional[Any] = None,
    inference_snapshot_v1: Optional[dict[str, Any]] = None,
) -> tuple[PredictiveCard, PredictionEnrichmentState]:
    """
    Hot path: similar-set retrieval, primary empirical horizons (1c/5c/15c/60c), MH ML overlay,
    and PredictiveCard fields required for compute_multi_horizon_synthesis and compute_call.
    """
    from features.fusion_model_input import FusionModelInputError

    if inference_snapshot_v1 is None:
        raise FusionModelInputError(
            "compute_prediction requires inference_snapshot_v1 — "
            "similarity filters, timeframe reads, and spot semantics use the canonical MVP row only."
        )
    mvp = inference_snapshot_v1.get("features") or {}
    spot = mvp_spot(mvp)
    if spot is None:
        raise FusionModelInputError("compute_prediction requires canonical price.spot > 0")

    timeframe = inp.timeframe

    tf_reads = _timeframe_reads(inp, mvp_features=mvp)

    similar = []
    avg_move = {}
    if db is not None:
        from features.fusion_model_input import similar_setup_filters_from_canonical_features

        _filters = similar_setup_filters_from_canonical_features(mvp)
        _zone = _filters["zone"]
        _vwap = _filters["vwap_side"]
        _nad, _nbd = _filters["nearest_above_dist"], _filters["nearest_below_dist"]
    else:
        _zone = _vwap = ""
        _nad = _nbd = None
    _asof_sim = _as_of_ts_utc_for_similarity(inp, inference_snapshot_v1)
    if db is not None:
        try:
            similar = db.get_similar_setups(
                ticker=inp.ticker,
                timeframe=timeframe,
                zone=_zone,
                vwap_side=_vwap,
                nearest_above_dist=_nad,
                nearest_below_dist=_nbd,
                as_of_ts_utc=_asof_sim,
            )
            avg_move = db.get_avg_move(
                ticker=inp.ticker,
                timeframe=timeframe,
                zone=_zone,
                vwap_side=_vwap,
                nearest_above_dist=_nad,
                nearest_below_dist=_nbd,
                as_of_ts_utc=_asof_sim,
            )
        except Exception as e:
            log.warning(f"DB lookup failed: {e}")

    match_tier = 7
    if similar:
        match_tier = similar[0].get("match_tier", 7)

    tier_label = _TIER_LABELS.get(match_tier, "general dataset")

    lit_1c = _literal_empirical_horizon(similar, "outcome_1c", 1)
    lit_5c = _literal_empirical_horizon(similar, "outcome_5c", 5)
    lit_15c = _literal_empirical_horizon(similar, "outcome_15c", 15)
    lit_60c = _literal_empirical_horizon(similar, "outcome_60c", 60)
    probs_1c, _, _, _ = lit_1c
    probs_5c, _, _, _ = lit_5c
    probs_15m, _, _, _ = lit_15c
    probs_60m, _, _, _ = lit_60c

    su1, sd1, sf1 = _tri_probs(probs_1c)
    su5, sd5, sf5 = _tri_probs(probs_5c)
    su15, sd15, sf15 = _tri_probs(probs_15m)
    su60, sd60, sf60 = _tri_probs(probs_60m)

    _mh_empirical_product = {
        "1c": (su1, sd1, sf1),
        "5c": (su5, sd5, sf5),
        "15c": (su15, sd15, sf15),
        "60c": (su60, sd60, sf60),
    }
    _tri_f, mh_prob_source_by_horizon, _mh_overlay_events = _overlay_multi_horizon_ml_on_product_triplets(
        _mh_empirical_product, multi_horizon_ml_bundle
    )
    ou1, od1, of1 = _tri_f["1c"]
    ou5, od5, of5 = _tri_f["5c"]
    ou15, od15, of15 = _tri_f["15c"]
    ou60, od60, of60 = _tri_f["60c"]

    if canonical is None:
        raise ValueError("compute_prediction requires canonical=CanonicalForecast (Issue 13)")

    _mb = ml_bundle or {}
    _integrity_events = merge_stack_integrity_events(
        _mb.get("stack_integrity_events") if isinstance(_mb, dict) else None,
        _mh_overlay_events,
    )
    model_outputs = _mb.get("model_outputs")
    try:
        from ml_predict import stack_probs_bundle_key

        _spk = stack_probs_bundle_key()
    except ImportError:
        _spk = "stack_probs_1c"
    ml_version = "rules_v1"
    try:
        from ml_predict import get_model_version

        ml_version = get_model_version(inp.ticker)
    except ImportError:
        pass

    _model_source = "empirical_histogram_plus_fusion_forward"
    if multi_horizon_ml_bundle is not None:
        _model_source = "multi_horizon_fusion_primary_with_empirical_support_or_fallback"

    n_used = len(similar)

    _fusion_available = fusion is not None and getattr(fusion, "available", False)

    if probs_5c is None:
        emp_dom, emp_prob = "flat", 0.0
        empirical_confidence = "low"
    else:
        emp_dom, emp_prob = dominant_direction(
            float(probs_5c.get("up", 0.33)),
            float(probs_5c.get("down", 0.33)),
            float(probs_5c.get("flat", 0.34)),
        )
        empirical_confidence = determine_confidence(
            match_tier, n_used, emp_prob, similar=similar, outcome_col="outcome_5c"
        )

    avg5 = _avg_outcome_pts(similar, "outcome_5c_pts")
    avg15 = _avg_outcome_pts(similar, "outcome_15c_pts")
    avg60 = _avg_outcome_pts(similar, "outcome_60c_pts")

    move_range_lo, move_range_hi = compute_percentile_range(similar)

    if _fusion_available and getattr(fusion, "mc_available", False):
        _mc_lo = getattr(fusion, "mc_lower_50", None)
        _mc_hi = getattr(fusion, "mc_upper_50", None)
        if move_range_lo is None and _mc_lo is not None:
            move_range_lo = round(_mc_lo - spot, 2)
        if move_range_hi is None and _mc_hi is not None:
            move_range_hi = round(_mc_hi - spot, 2)

    prediction_dir = "none"
    prediction_target = None
    fwd = (canonical.direction or "flat").lower()
    if fwd in ("up", "down"):
        if canonical.confidence != "low" and avg5 is not None:
            prediction_dir = fwd
            prediction_target = round(spot + avg5, 2)
        elif canonical.dominant_probability() >= 0.45 and avg5 is not None:
            prediction_dir = fwd
            prediction_target = round(spot + avg5, 2)
        elif canonical.dominant_probability() >= 0.45:
            prediction_dir = fwd

    _stack_integrity_v1 = finalize_stack_integrity_v1(_integrity_events)
    if isinstance(ml_bundle, dict):
        ml_bundle["stack_integrity_v1"] = _stack_integrity_v1

    state = PredictionEnrichmentState(
        similar=similar,
        avg_move=avg_move,
        lit_1c=lit_1c,
        lit_5c=lit_5c,
        lit_15c=lit_15c,
        lit_60c=lit_60c,
        match_tier=match_tier,
        spot=spot,
        mvp=mvp,
    )

    card = PredictiveCard(
        headline="",
        prediction_dir=prediction_dir,
        prediction_target=prediction_target,
        historical_5c_dominant_dir=emp_dom,
        historical_5c_dominant_prob=emp_prob,
        empirical_confidence=empirical_confidence,
        forward_direction=canonical.direction,
        forward_prob_up=canonical.probability_up,
        forward_prob_down=canonical.probability_down,
        forward_prob_flat=canonical.probability_flat,
        forward_confidence=canonical.confidence,
        forward_provenance=canonical.provenance,
        samples_used=n_used,
        model_note="",
        timeframe_reads=tf_reads,
        up_prob_1c=ou1,
        down_prob_1c=od1,
        flat_prob_1c=of1,
        up_prob_5c=ou5,
        down_prob_5c=od5,
        flat_prob_5c=of5,
        up_prob_15c=ou15,
        down_prob_15c=od15,
        flat_prob_15c=of15,
        up_prob_60c=ou60,
        down_prob_60c=od60,
        flat_prob_60c=of60,
        avg_5c_pts=avg5,
        avg_15c_pts=avg15,
        avg_60c_pts=avg60,
        move_range_lo=move_range_lo,
        move_range_hi=move_range_hi,
        match_tier=match_tier,
        tier_label=tier_label,
        model_source=_model_source,
        model_version=ml_version,
        model_outputs=model_outputs,
        movement_head_probs=(
            _mb.get("movement_head_probs")
            if isinstance(_mb.get("movement_head_probs"), dict)
            else None
        ),
        fusion_policy_snapshot_cols=(
            _mb.get("fusion_policy_snapshot_cols")
            if isinstance(_mb.get("fusion_policy_snapshot_cols"), dict)
            else None
        ),
        mh_empirical_product_triplets=dict(_mh_empirical_product),
        mh_prob_source_by_horizon=dict(mh_prob_source_by_horizon),
        stack_integrity_v1=_stack_integrity_v1,
    )
    return card, state


def compute_prediction_enrichment(
    pred_core: PredictiveCard,
    state: PredictionEnrichmentState,
    inp: SignalInput,
    canonical: CanonicalForecast,
    regime=None,
    fusion=None,
    rules=None,
    ml_bundle: Optional[Dict[str, Any]] = None,
    *,
    multi_horizon_ml_bundle: Optional[Any] = None,
    inference_snapshot_v1: Optional[dict[str, Any]] = None,
) -> PredictiveCard:
    """
    Cold path: secondary horizons (3c/8c/13c), eval dashboard metrics, reversal analytics,
    horizon UI bars, headline, and model_note. Must run before snapshot persistence.
    """
    del inference_snapshot_v1  # reserved for API symmetry with compute_prediction

    similar = state.similar
    avg_move = state.avg_move
    mvp = state.mvp
    spot = state.spot
    match_tier = state.match_tier

    lit_1c = state.lit_1c
    lit_5c = state.lit_5c
    lit_15c = state.lit_15c
    lit_60c = state.lit_60c

    eval_acc_oos = eval_ll_oos = None
    eval_realized = None
    eval_realized_meta = None
    try:
        from eval_metrics_store import load_dashboard_eval_metrics

        pack = load_dashboard_eval_metrics().get((inp.ticker or "").upper(), {})
        par = pack.get("parallel") or {}
        if par:
            eval_acc_oos = par.get("eval_accuracy")
            eval_ll_oos = par.get("eval_log_loss")
            eval_realized = par.get("eval_pnl_realized_contract")
            eval_realized_meta = par.get("realized_contract_metrics")
            if eval_acc_oos is not None:
                eval_acc_oos = float(eval_acc_oos)
            if eval_ll_oos is not None:
                eval_ll_oos = float(eval_ll_oos)
            if eval_realized is not None:
                eval_realized = float(eval_realized)
    except Exception:
        pass

    lit_3c = _literal_empirical_horizon(similar, "outcome_3c", 3)
    lit_8c = _literal_empirical_horizon(similar, "outcome_8c", 8)
    lit_13c = _literal_empirical_horizon(similar, "outcome_13c", 13)
    probs_3c, _, _, _ = lit_3c
    probs_8c, _, _, _ = lit_8c
    probs_13c, _, _, _ = lit_13c
    probs_5c, _, _, _ = lit_5c

    _mb = ml_bundle or {}
    try:
        from ml_predict import stack_probs_bundle_key

        _spk = stack_probs_bundle_key()
    except ImportError:
        _spk = "stack_probs_1c"
    ml_stack_probs = _mb.get(_spk)

    up_3c, down_3c, flat_3c = _tri_probs(probs_3c)
    up_8c, down_8c, flat_8c = _tri_probs(probs_8c)
    up_13c, down_13c, flat_13c = _tri_probs(probs_13c)

    n_used = pred_core.samples_used
    _fusion_available = fusion is not None and getattr(fusion, "available", False)

    avg3 = _avg_outcome_pts(similar, "outcome_3c_pts")
    avg8 = _avg_outcome_pts(similar, "outcome_8c_pts")
    avg13 = _avg_outcome_pts(similar, "outcome_13c_pts")
    med3 = avg_move.get("median_3c_pts")

    emp_dom = pred_core.historical_5c_dominant_dir
    emp_prob = pred_core.historical_5c_dominant_prob
    empirical_confidence = pred_core.empirical_confidence
    avg5 = pred_core.avg_5c_pts

    reversal_risk = None
    reversal_label = ""
    if probs_5c is not None:
        pu = float(probs_5c.get("up", 0.33))
        pd = float(probs_5c.get("down", 0.33))
        pf = float(probs_5c.get("flat", 0.34))
        if emp_dom == "up":
            reversal_risk = round(pd, 2)
        elif emp_dom == "down":
            reversal_risk = round(pu, 2)
        elif emp_dom == "flat":
            reversal_risk = round(max(pu, pd), 2)
        reversal_label = classify_reversal_risk(reversal_risk)

    _regime_label = getattr(regime, "primary", None) if regime else None
    if reversal_risk is not None and _regime_label == "reversal_prone":
        if _fusion_available and getattr(fusion, "mc_available", False):
            _mc_eae = getattr(fusion, "mc_eae", None)
            _mc_efe = getattr(fusion, "mc_efe", None)
            if _mc_eae and _mc_efe and _mc_eae > _mc_efe * 1.2:
                reversal_risk = min(1.0, reversal_risk * 1.25)
                reversal_label = classify_reversal_risk(reversal_risk)

    reversal_shortfall = None
    reversal_severity = ""
    if emp_dom in ("up", "down") and similar:
        opposite = "down" if emp_dom == "up" else "up"
        bad_moves = []
        for row in similar:
            if row.get("outcome_5c") == opposite:
                pts = row.get("outcome_5c_pts")
                if pts is not None:
                    bad_moves.append(pts)
        if len(bad_moves) >= 5:
            avg_bad = sum(bad_moves) / len(bad_moves)
            reversal_shortfall = round(avg_bad, 2)
            spot_pct = abs(avg_bad) / spot if spot > 0 else 0
            if spot_pct >= 0.004:
                reversal_severity = "severe"
            elif spot_pct >= 0.002:
                reversal_severity = "moderate"
            else:
                reversal_severity = "mild"

    prediction_dir = pred_core.prediction_dir
    prediction_target = pred_core.prediction_target
    pct = int(emp_prob * 100)
    fwd = (canonical.direction or "flat").lower()
    dir_labels = {"up": "UP", "down": "DOWN", "flat": "FLAT", "none": "NO EDGE"}
    fwd_lbl = dir_labels.get(fwd, "FLAT")

    if probs_5c is None and n_used > 0:
        _n5 = lit_5c[3]
        headline = (
            f"Fusion forward: {fwd_lbl} ({canonical.confidence}). "
            f"Insufficient labeled outcome_5c ({_n5} < {MIN_SAMPLES_STATISTICAL}) — empirical bars withheld."
        )
    elif prediction_dir in ("up", "down") and prediction_target is not None:
        headline = (
            f"Fusion forward {fwd_lbl} ({canonical.confidence}) — illustrative target {prediction_target:.2f} "
            f"from signed avg 5m move in similar setups (historical 5c mode {emp_dom}, match {empirical_confidence})."
        )
    elif prediction_dir in ("up", "down"):
        headline = (
            f"Fusion forward {fwd_lbl} ({canonical.confidence}); historical 5c mode {emp_dom} at {pct}%."
        )
    elif n_used >= MIN_SAMPLES_STATISTICAL and match_tier <= 4:
        headline = (
            f"Fusion: {fwd_lbl} ({canonical.confidence}). Historical 5c balanced ({pct}% {emp_dom})."
        )
    else:
        headline = (
            f"Fusion: {fwd_lbl} ({canonical.confidence}). Historical match: {emp_dom} / {empirical_confidence} tier."
        )

    parts = []

    _slc = similarity_labeled_counts(similar) if similar else {}
    _tier_ok = similarity_tier_stop_viable(_slc)
    _all_tracked = similarity_empirically_viable(_slc)
    if similar:
        if _tier_ok and _all_tracked:
            parts.append(
                f"Similar-set tier {match_tier}: tier-stop and all tracked horizons satisfied "
                f"(≥{MIN_SAMPLES_STATISTICAL} labeled each; min {min(_slc.values())})."
            )
        elif _tier_ok:
            _aux = {k: v for k, v in _slc.items() if k not in (
                "outcome_1c", "outcome_5c", "outcome_15c")}
            _wk = min(_aux, key=_aux.get) if _aux else "—"
            parts.append(
                f"Similar-set tier {match_tier}: tier-stop horizons (1c/5c/15c) satisfied; "
                f"sparse auxiliary {_wk} ({_slc.get(_wk, 0)} labeled) — may be withheld in bars."
            )
        else:
            _st = {k: _slc.get(k, 0) for k in ("outcome_1c", "outcome_5c", "outcome_15c")}
            _wk = min(_st, key=_st.get) if _st else "—"
            parts.append(
                f"Similar-set tier {match_tier}: tier-stop weakest {_wk} "
                f"({_st.get(_wk, 0)} labeled vs {MIN_SAMPLES_STATISTICAL})."
            )

    if probs_5c is None:
        _n5 = lit_5c[3]
        parts.append(
            f"{n_used:,} similar setups; {_n5} labeled outcome_5c (need {MIN_SAMPLES_STATISTICAL} for empirical %)."
        )
    else:
        up_pct = int(float(probs_5c.get("up", 0.33)) * 100)
        dn_pct = int(float(probs_5c.get("down", 0.33)) * 100)
        fl_pct = int(float(probs_5c.get("flat", 0.34)) * 100)
        parts.append(f"{n_used:,} similar setups found. {up_pct}% went up, {dn_pct}% down, {fl_pct}% flat.")

    if empirical_confidence == "high" and emp_dom in ("up", "down"):
        parts.append(f"Historically strong lean {emp_dom} in this 5c bucket.")
    elif empirical_confidence == "medium" and emp_dom in ("up", "down"):
        parts.append(f"Historically moderate lean {emp_dom} — context only vs forward stack.")
    elif emp_dom == "flat":
        parts.append("Historical 5c distribution tends to chop here.")
    else:
        parts.append("Historical 5c edge weak — do not confuse with fusion forward.")

    if avg5 is not None:
        sign = "+" if avg5 >= 0 else ""
        parts.append(f"Avg 5m move: {sign}{avg5:.1f} pts.")

    zone_fresh_bars_1m = (inp.zone_since_bars_1m or inp.zone_since_bars) or 0
    prev_z = (inp.prev_zone or "").lower()
    cur_z = mvp_zone(mvp)
    if zone_fresh_bars_1m <= 3 and prev_z and prev_z != cur_z:
        parts.append(f"Zone just changed ({prev_z} → {cur_z}) — setup still forming.")

    if multi_horizon_ml_bundle is not None:
        parts.append(
            "Multi-horizon fusion: 1c/5c/15c/60c use per-horizon Bayesian fusion (parallel trained stacks); "
            "empirical similar-set histograms are calibration support or fallback when fusion is unavailable."
        )
    elif ml_stack_probs is not None:
        parts.append(
            f"ML stack ({pred_core.model_version}) is trained for the 1-minute horizon — see Model stack; "
            "horizon probability bars are empirical DB labels only."
        )

    _regime_label = getattr(regime, "primary", None) if regime else None
    if _regime_label and _regime_label != "unknown":
        _regime_conf = getattr(regime, "confidence", "low")
        parts.append(f"Regime: {_regime_label} ({_regime_conf}).")

    if _fusion_available:
        _dom = getattr(fusion, "dominant_outcome", "unknown")
        _dom_p = getattr(fusion, "dominant_probability", 0)
        _agree_label = getattr(fusion, "model_agreement_label", "low")
        _n_active = getattr(fusion, "n_sources_active", 0)
        if _n_active > 0:
            parts.append(f"Fusion: {_dom} ({_dom_p:.0%}), model agreement {_agree_label}.")

    if _fusion_available and getattr(fusion, "mc_available", False):
        _mc_efe = getattr(fusion, "mc_efe", None)
        _mc_eae = getattr(fusion, "mc_eae", None)
        _mc_contain = getattr(fusion, "mc_containment", None)
        _mc_expand = getattr(fusion, "mc_expansion", None)
        if _mc_efe is not None and _mc_eae is not None:
            parts.append(f"MC: EFE {_mc_efe:.1f}pts / EAE {_mc_eae:.1f}pts.")
        if _mc_contain is not None and _regime_label:
            if _regime_label in ("pinning", "mean_reversion", "vol_compression"):
                if _mc_contain < 0.40:
                    parts.append(f"⚠ Low containment ({_mc_contain:.0%}) despite {_regime_label} — breakout risk.")
                else:
                    parts.append(f"Containment: {_mc_contain:.0%} (normal for {_regime_label}).")
            elif _regime_label in ("breakout", "acceleration", "vol_expansion"):
                if _mc_contain > 0.60:
                    parts.append(f"⚠ High containment ({_mc_contain:.0%}) despite {_regime_label} — breakout may fail.")
                else:
                    parts.append(f"Expansion: {_mc_expand:.0%} (confirms {_regime_label}).")
            elif _regime_label == "reversal_prone":
                if _mc_eae is not None and _mc_efe is not None and _mc_eae > _mc_efe * 1.3:
                    parts.append(f"⚠ EAE exceeds EFE by {(_mc_eae/_mc_efe - 1):.0%} — adverse tail risk elevated.")
                else:
                    parts.append(f"Containment: {_mc_contain:.0%}.")
            else:
                parts.append(f"Containment: {_mc_contain:.0%}.")

    if canonical.confidence == "high" and fwd == "up":
        _action = "→ Forward stack: lean calls; weigh historical context above."
    elif canonical.confidence == "high" and fwd == "down":
        _action = "→ Forward stack: lean puts; weigh historical context above."
    elif canonical.confidence == "medium" and fwd == "up":
        _action = "→ Forward stack: slight call bias — size per The Call."
    elif canonical.confidence == "medium" and fwd == "down":
        _action = "→ Forward stack: slight put bias — size per The Call."
    elif fwd == "flat" and canonical.dominant_probability() >= 0.50:
        _action = "→ Forward stack balanced — favor patience unless The Call fires."
    else:
        _action = "→ Forward conviction low — default wait unless confluence clears gates."
    parts.append(_action)

    model_note = " ".join(parts)

    horizon_prob_bars = _build_horizon_prob_bars(lit_1c, lit_5c, lit_15c, lit_60c)

    return replace(
        pred_core,
        headline=headline,
        model_note=model_note,
        up_prob_3c=up_3c,
        down_prob_3c=down_3c,
        flat_prob_3c=flat_3c,
        up_prob_8c=up_8c,
        down_prob_8c=down_8c,
        flat_prob_8c=flat_8c,
        up_prob_13c=up_13c,
        down_prob_13c=down_13c,
        flat_prob_13c=flat_13c,
        avg_3c_pts=avg3,
        avg_8c_pts=avg8,
        avg_13c_pts=avg13,
        median_3c_pts=med3,
        reversal_risk=reversal_risk,
        reversal_label=reversal_label,
        reversal_shortfall=reversal_shortfall,
        reversal_severity=reversal_severity,
        horizon_prob_bars=horizon_prob_bars,
        eval_accuracy_oos=eval_acc_oos,
        eval_log_loss_oos=eval_ll_oos,
        eval_pnl_realized_contract_oos=eval_realized,
        eval_realized_contract_metrics_oos=eval_realized_meta,
        pred_action=_action,
    )


def compute_prediction(
    inp: SignalInput,
    db,
    regime=None,
    fusion=None,
    rules=None,
    mc_out=None,
    canonical: Optional[CanonicalForecast] = None,
    ml_bundle: Optional[Dict[str, Any]] = None,
    *,
    multi_horizon_ml_bundle: Optional[Any] = None,
    inference_snapshot_v1: Optional[dict[str, Any]] = None,
) -> PredictiveCard:
    """
    Statistical prediction from historical snapshots.

    Uses progressive relaxation in db.get_similar_setups (Issue 19):
      Tiers 1–4: zone/vwap/distance SQL filters; stops at the **narrowest** tier where
      outcome_1c / outcome_5c / outcome_15c each have >= MIN_SAMPLES_STATISTICAL labeled
      rows (aligned with multi_horizon primary horizons except sparse 60c; same bar as
      _literal_empirical_horizon for those columns). Auxiliary horizons (3c/8c/13c/60c)
      may still be withheld without broadening the tier.
      Tier 5: broadest pool (ticker+timeframe+outcome_1c) — always used if tiers 1–4 fail
      tier-stop viability; per-horizon withholding may still apply where counts are low.

    Confidence is driven by:
      - Match tier (tighter = more relevant = higher confidence)
      - Sample size
      - How dominant the winning direction is

    Implementation: compute_prediction_core (hot) + compute_prediction_enrichment (cold).
    Set ED_PREDICT_ENRICHMENT=0 to skip cold path (UI/analytics fields may be empty).
    """
    core, st = compute_prediction_core(
        inp,
        db,
        regime=regime,
        fusion=fusion,
        rules=rules,
        mc_out=mc_out,
        canonical=canonical,
        ml_bundle=ml_bundle,
        multi_horizon_ml_bundle=multi_horizon_ml_bundle,
        inference_snapshot_v1=inference_snapshot_v1,
    )
    if not _predict_enrichment_enabled():
        return core
    return compute_prediction_enrichment(
        core,
        st,
        inp,
        canonical,
        regime=regime,
        fusion=fusion,
        rules=rules,
        ml_bundle=ml_bundle,
        multi_horizon_ml_bundle=multi_horizon_ml_bundle,
        inference_snapshot_v1=inference_snapshot_v1,
    )
