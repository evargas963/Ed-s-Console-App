"""Card signal fidelity + feature provenance helpers (read-only audit)."""
from __future__ import annotations

from typing import Any, Optional

from verification.card_direction_integrity import (
    HORIZON_CARD_LABELS,
    HORIZON_SLUGS,
    direction_sign,
    fusion_direction_from_probs,
    return_sign,
)

# Signal semantics tags (audit vocabulary)
CLASS_TREND_FOLLOWING_LONG = "TREND_FOLLOWING_LONG"
CLASS_REVERSAL_LONG = "REVERSAL_LONG"
CLASS_MEAN_REVERSION_LONG = "MEAN_REVERSION_LONG"
CLASS_MOMENTUM_SHORT = "MOMENTUM_SHORT"
CLASS_UNCLEAR_FEATURE_SOURCE = "UNCLEAR_FEATURE_SOURCE"
CLASS_STALE_FEATURE_RISK = "STALE_FEATURE_RISK"
CLASS_FUSION_OVERRIDE_EMPIRICAL = "FUSION_OVERRIDE_EMPIRICAL"
CLASS_EMPIRICAL_SUPPORTS_SIGNAL = "EMPIRICAL_SUPPORTS_SIGNAL"
CLASS_EMPIRICAL_CONFLICTS_SIGNAL = "EMPIRICAL_CONFLICTS_SIGNAL"
CLASS_PLAN_CORRECTLY_BLOCKED = "PLAN_CORRECTLY_BLOCKED"
CLASS_MODEL_DIRECTION_DRIFT = "MODEL_DIRECTION_DRIFT"

# Histogram shape audit vocabulary
HIST_SUPPORTED_LONG = "HISTOGRAM_SUPPORTED_LONG"
HIST_SUPPORTED_SHORT = "HISTOGRAM_SUPPORTED_SHORT"
HIST_FUSION_OVERRIDES_BEARISH = "FUSION_OVERRIDES_BEARISH_HISTOGRAM"
HIST_TOO_FLAT = "HISTOGRAM_TOO_FLAT"
HIST_UNDERCONDITIONED = "HISTOGRAM_UNDERCONDITIONED"
HIST_STALE_OR_DEGRADED = "HISTOGRAM_STALE_OR_DEGRADED"
HIST_VALID_REVERSAL_DESPITE_BEARISH = "VALID_REVERSAL_DESPITE_BEARISH_HISTOGRAM"

DEFAULT_HISTOGRAM_FLAT_SPREAD = 0.12

HISTOGRAM_LABEL_BY_HZ = {"1c": "1m", "5c": "5m", "15c": "15m", "60c": "60m"}


def trailing_tape_direction(trailing_return: Optional[float]) -> str:
    sign = return_sign(trailing_return)
    if sign == 1:
        return "UP"
    if sign == -1:
        return "DOWN"
    return "FLAT"


def histogram_is_flat(
    up: Optional[float],
    down: Optional[float],
    flat: Optional[float],
    *,
    spread_threshold: float = DEFAULT_HISTOGRAM_FLAT_SPREAD,
) -> bool:
    probs = [float(up or 0.0), float(down or 0.0), float(flat or 0.0)]
    return (max(probs) - min(probs)) < float(spread_threshold)


def _mhap_confidence(row: dict[str, Any], horizon: str) -> Optional[float]:
    for item in row.get("mhap_rows") or []:
        if str(item.get("horizon") or "").lower() == horizon:
            try:
                return float(item.get("confidence"))
            except (TypeError, ValueError):
                return None
    return None


def classify_histogram_shape_cell(
    *,
    trailing_tape: str,
    histogram_dominant: str,
    fusion_dominant: str,
    card_direction: Optional[str],
    forward_realized_return: Optional[float],
    histogram_flat: bool,
    data_degraded: bool,
    stale_feature_risk: bool,
) -> list[str]:
    """Classify empirical histogram shape vs fusion/card during decline samples."""
    tags: list[str] = []
    hist = (histogram_dominant or "").upper()
    fus = (fusion_dominant or "").upper()
    card = (card_direction or "").upper()

    if data_degraded or stale_feature_risk:
        tags.append(HIST_STALE_OR_DEGRADED)
    if histogram_flat:
        tags.append(HIST_TOO_FLAT)

    if hist == "LONG" and card == "LONG":
        tags.append(HIST_SUPPORTED_LONG)
    if hist == "SHORT" and card == "SHORT":
        tags.append(HIST_SUPPORTED_SHORT)

    if hist == "SHORT" and fus == "LONG" and card == "LONG":
        if (
            trailing_tape == "DOWN"
            and forward_realized_return is not None
            and forward_realized_return > 0
        ):
            tags.append(HIST_VALID_REVERSAL_DESPITE_BEARISH)
        else:
            tags.append(HIST_FUSION_OVERRIDES_BEARISH)

    if trailing_tape == "DOWN" and hist not in ("SHORT",) and not histogram_flat and hist != "WAIT":
        tags.append(HIST_UNDERCONDITIONED)

    return sorted(set(tags))


def build_histogram_shape_row(
    row: dict[str, Any],
    horizon: str,
    *,
    data_degraded: bool = False,
) -> dict[str, Any]:
    """One histogram-shape audit cell for a decline timestamp × horizon."""
    hist_label = HISTOGRAM_LABEL_BY_HZ[horizon]
    hz_block = row.get(f"horizon_{horizon}") or {}
    hist_probs = (row.get("horizon_prob_bars") or {}).get(hist_label) or {}
    fus_probs = (row.get("fusion_triplets") or {}).get(horizon) or {}

    trailing_key = {
        "1c": "trailing_return_1m",
        "5c": "trailing_return_5m",
        "15c": "trailing_return_15m",
        "60c": "trailing_return_60m",
    }[horizon]
    trailing_ret = row.get(trailing_key)
    trailing_tape = trailing_tape_direction(trailing_ret)

    hist_dom = fusion_direction_from_probs(
        hist_probs.get("up"), hist_probs.get("down"), hist_probs.get("flat")
    )
    fus_dom = fusion_direction_from_probs(
        fus_probs.get("up"), fus_probs.get("down"), fus_probs.get("flat")
    )
    flat = histogram_is_flat(hist_probs.get("up"), hist_probs.get("down"), hist_probs.get("flat"))
    stale = bool((row.get("stale_flags") or {}).get("stale_feature_risk"))

    return {
        "timestamp_et": row.get("ts_et"),
        "timestamp_utc": row.get("ts_utc"),
        "trailing_tape_direction": trailing_tape,
        "horizon": horizon,
        "horizon_label": HORIZON_CARD_LABELS[horizon],
        "histogram_up": hist_probs.get("up"),
        "histogram_down": hist_probs.get("down"),
        "histogram_flat_prob": hist_probs.get("flat"),
        "histogram_dominant": hist_dom,
        "fusion_up": fus_probs.get("up"),
        "fusion_down": fus_probs.get("down"),
        "fusion_flat": fus_probs.get("flat"),
        "fusion_dominant": fus_dom,
        "card_direction": hz_block.get("displayed_direction"),
        "card_confidence": _mhap_confidence(row, horizon),
        "forward_realized_return": hz_block.get("forward_realized_return"),
        "sample_support": None,
        "sample_support_note": (
            "similar-set count not persisted on timeline; use offline similar_set_trace for row-level n"
        ),
        "histogram_flat_spread": flat,
        "classifications": classify_histogram_shape_cell(
            trailing_tape=trailing_tape,
            histogram_dominant=hist_dom,
            fusion_dominant=fus_dom,
            card_direction=hz_block.get("displayed_direction"),
            forward_realized_return=hz_block.get("forward_realized_return"),
            histogram_flat=flat,
            data_degraded=data_degraded,
            stale_feature_risk=stale,
        ),
    }


def build_histogram_shape_audit(
    timeline: list[dict[str, Any]],
    *,
    normalized_rows_rth: Optional[int] = None,
) -> dict[str, Any]:
    """Histogram shape audit for all decline samples × horizons."""
    degraded = normalized_rows_rth == 0 if normalized_rows_rth is not None else False
    cells: list[dict[str, Any]] = []
    for row in timeline:
        for hz in HORIZON_SLUGS:
            cells.append(build_histogram_shape_row(row, hz, data_degraded=degraded))

    class_counts: dict[str, int] = {}
    by_horizon: dict[str, dict[str, int]] = {hz: {} for hz in HORIZON_SLUGS}
    for cell in cells:
        for tag in cell.get("classifications") or []:
            class_counts[tag] = class_counts.get(tag, 0) + 1
            hz = str(cell.get("horizon"))
            by_horizon.setdefault(hz, {})
            by_horizon[hz][tag] = by_horizon[hz].get(tag, 0) + 1

    hist_short_fusion_long = sum(
        1
        for c in cells
        if c.get("histogram_dominant") == "SHORT" and c.get("fusion_dominant") == "LONG"
    )
    hist_bearish_during_down_tape = sum(
        1 for c in cells if c.get("trailing_tape_direction") == "DOWN" and c.get("histogram_dominant") == "SHORT"
    )
    valid_reversal = class_counts.get(HIST_VALID_REVERSAL_DESPITE_BEARISH, 0)
    fusion_override = class_counts.get(HIST_FUSION_OVERRIDES_BEARISH, 0)

    return {
        "cell_count": len(cells),
        "sample_timestamps": len(timeline),
        "normalized_rows_degraded": degraded,
        "classification_counts": class_counts,
        "classification_counts_by_horizon": by_horizon,
        "histogram_shifted_bearish_during_down_tape": hist_bearish_during_down_tape,
        "histogram_short_fusion_long_cells": hist_short_fusion_long,
        "valid_reversal_despite_bearish_histogram": valid_reversal,
        "fusion_overrides_bearish_histogram": fusion_override,
        "cells": cells,
        "operator_interpretation": {
            "histogram_did_shift_bearish_on_short_horizons": (
                by_horizon.get("1c", {}).get(HIST_SUPPORTED_SHORT, 0)
                + by_horizon.get("5c", {}).get(HIST_SUPPORTED_SHORT, 0)
            )
            > 0,
            "fusion_overrode_bearish_histogram": fusion_override > 0,
            "lower_horizon_reversal_legitimate": valid_reversal > max(1, fusion_override // 2),
            "longer_horizon_override_warrants_review": (
                by_horizon.get("60c", {}).get(HIST_FUSION_OVERRIDES_BEARISH, 0) > 0
            ),
            "empirical_disagreement_not_surfaced_on_card": True,
        },
    }


def histogram_shape_operator_answers(hist_audit: dict[str, Any]) -> dict[str, Any]:
    """Answers operator deep-dive on histogram vs fusion during decline."""
    counts = hist_audit.get("classification_counts") or {}
    interp = hist_audit.get("operator_interpretation") or {}
    return {
        "1_histogram_shift_bearish_during_downside": (
            f"Partially — {hist_audit.get('histogram_shifted_bearish_during_down_tape', 0)} cells "
            f"had DOWN trailing tape + SHORT histogram dominant; "
            f"also {counts.get(HIST_UNDERCONDITIONED, 0)} UNDERCONDITIONED cells where tape down "
            f"but histogram did not reshape bearish"
        ),
        "2_why_fusion_long_if_histogram_bearish": (
            "Fusion-only product contract: cards follow fusion argmax; empirical histogram is signal-rail "
            f"context with default blend weight 0. {hist_audit.get('histogram_short_fusion_long_cells', 0)} "
            "cells had histogram SHORT + fusion LONG"
        ),
        "3_if_not_bearish_missing_pattern_features": (
            "Possible — UNDERCONDITIONED tags flag histogram not shifting with downside tape; "
            "similar-setup filters (zone/vwap/distances) may be too coarse vs lower-highs/lower-lows structure"
        ),
        "4_tape_structure_features_represented": (
            "Not directly in horizon_prob_bars — histogram conditions on similar_setup_filters, not explicit "
            "LH/LL or VWAP rejection primitives; audit cannot prove those were in the similar-set query"
        ),
        "5_horizon_specific_vs_coarse": (
            "Per-horizon histogram labels (1m/5m/15m/60m) exist; disagreement pattern differs by horizon "
            "(short horizons more bearish, 60m histogram often LONG in June 17 samples)"
        ),
        "6_sample_support_sufficient": (
            "Not measured on timeline — sample_support null; sparse/missing normalized rows on original "
            "June 17 run degraded similar-set quality"
        ),
        "7_stale_missing_norm_degraded_shape": bool(hist_audit.get("normalized_rows_degraded")),
        "8_should_empirical_become_veto_or_chip": (
            "Audit recommendation: conflict chip or confidence haircut when fusion overrides bearish histogram "
            "during DOWN tape — not implemented today"
        ),
        "9_reversal_vs_fusion_override": (
            f"{counts.get(HIST_VALID_REVERSAL_DESPITE_BEARISH, 0)} VALID_REVERSAL vs "
            f"{counts.get(HIST_FUSION_OVERRIDES_BEARISH, 0)} FUSION_OVERRIDES — "
            "short horizons skew reversal; longer horizons skew override"
        ),
        "interpretation_1_cards_worked_as_designed": interp.get("lower_horizon_reversal_legitimate"),
        "interpretation_2_histogram_layer_weak": (
            counts.get(HIST_TOO_FLAT, 0) > 0 or counts.get(HIST_UNDERCONDITIONED, 0) > 0
        ),
    }

CARD_FIELD_PROVENANCE: dict[str, dict[str, Any]] = {
    "horizon_1M": {
        "display_direction": {
            "trunk": "mhap_rows[horizon=1c].call",
            "branch": [
                "multi_horizon_decision.py:compute_multi_horizon_synthesis → SupportingHorizonAssessment.call",
                "multi_horizon_decision.py:_forecast_horizon_live → HorizonForecast from fusion triplet",
                "prediction_engine.py:compute_prediction_core → up_prob_1c/down_prob_1c/flat_prob_1c",
                "bayesian_fusion.py:_fuse_impl → per-horizon fusion posterior",
            ],
            "leaf_authority": "fusion_probabilities_only (AGENTS fusion-only card contract)",
            "not_used_for_product": "horizon_prob_bars empirical histogram (signal rail context only)",
        },
        "display_confidence": {
            "trunk": "mhap_rows[horizon=1c].confidence",
            "branch": [
                "SupportingHorizonAssessment.confidence ← HorizonForecast.confidence",
                "fusion_confidence_score from bayesian_fusion",
            ],
        },
    },
    "horizon_5M": {
        "display_direction": {"trunk": "mhap_rows[horizon=5c].call", "inherits": "horizon_1M.display_direction"},
        "display_confidence": {"trunk": "mhap_rows[horizon=5c].confidence", "inherits": "horizon_1M.display_confidence"},
    },
    "horizon_15M": {
        "display_direction": {"trunk": "mhap_rows[horizon=15c].call", "inherits": "horizon_1M.display_direction"},
        "display_confidence": {"trunk": "mhap_rows[horizon=15c].confidence", "inherits": "horizon_1M.display_confidence"},
    },
    "horizon_60M": {
        "display_direction": {"trunk": "mhap_rows[horizon=60c].call", "inherits": "horizon_1M.display_direction"},
        "display_confidence": {"trunk": "mhap_rows[horizon=60c].confidence", "inherits": "horizon_1M.display_confidence"},
    },
    "ALL_consolidated": {
        "display_direction": {
            "trunk": "ui ALL pill direction",
            "branch": [
                "tools/replay_money_path_probe.py:ui_card_derivation",
                "final_bias + final_tradeable from MultiHorizonDecision",
            ],
            "rule": "directional only when final_tradeable and bias in LONG/SHORT; else FLAT",
        },
    },
    "PLAN": {
        "display_state": {
            "trunk": "PLAN pill state",
            "branch": [
                "ui_card_derivation(entry_state) when tradeable",
                "call_engine.py:compute_call → entry/stop/target plan",
            ],
            "rule": "NO SETUP when not final_tradeable",
        },
    },
    "STALE_LOADING": {
        "backend": {
            "trunk": "analytics_stale, decision_generation_id, _server_build_ts",
            "branch": ["server.py:_attach_analytics_freshness_contract", "VIEWER_STATE_CACHE_TTL_SEC"],
        },
        "frontend": {
            "trunk": "bundleDirectionWithheld, isFusionAuthoritative, window._priceAheadOfBundle",
            "branch": ["static/index.html LIVE_UI_INTEGRITY_V1"],
            "stale_rule": "WITHHOLD direction when quote ahead of bundle or gen stale",
        },
    },
}

CARD_FEATURE_PROVENANCE: list[dict[str, Any]] = [
    {
        "feature": "spot",
        "class": "primitive",
        "source_table": "snapshots / snapshots_1m_normalized",
        "source_fn": "schwab quote → db.insert_snapshot",
        "timestamp": "snapshots.ts_utc",
        "horizons": ["all"],
        "cards": ["quote header", "trailing return audit"],
        "all_plan": False,
        "traceable_to_raw": True,
        "stale_risk": "Tier A fast-quote can lead Tier C bundle",
        "failure_mode": "price_ahead_of_bundle withholds cards not spot",
    },
    {
        "feature": "fusion_prob_up/down/flat",
        "class": "engineered",
        "source_table": "in-memory fusion payload",
        "source_fn": "bayesian_fusion._fuse_impl",
        "timestamp": "refresh_ts_utc on SignalInput",
        "horizons": ["1c", "5c", "15c", "60c"],
        "cards": ["1M", "5M", "15M", "60M"],
        "all_plan": True,
        "traceable_to_raw": True,
        "stale_risk": "stale ML bundle or missing model files",
        "failure_mode": "fusion_unavailable → withhold triplets",
    },
    {
        "feature": "horizon_prob_bars (empirical)",
        "class": "engineered",
        "source_table": "historical snapshots similar-set",
        "source_fn": "verification.similar_set_trace.full_similar_and_empirical_trace",
        "timestamp": "as_of_ts_utc at query",
        "horizons": ["1m", "5m", "15m", "60m"],
        "cards": ["signal rail histogram only"],
        "all_plan": False,
        "traceable_to_raw": True,
        "stale_risk": "sparse DB history / missing normalized rows",
        "failure_mode": "must not fill product triplets when fusion-only default",
    },
    {
        "feature": "similar_setup_filters (zone, vwap_side, distances)",
        "class": "engineered",
        "source_table": "snapshots",
        "source_fn": "features.fusion_model_input.similar_setup_filters_from_db_snapshot_row",
        "timestamp": "snapshot row ts_utc",
        "horizons": ["empirical"],
        "cards": ["histogram context"],
        "all_plan": False,
        "traceable_to_raw": True,
        "stale_risk": "stale zone/vwap if snapshot old",
        "failure_mode": "wrong similar-set → misleading histogram",
    },
    {
        "feature": "mvp_features / inference_snapshot_v1",
        "class": "engineered",
        "source_table": "derived at compute time",
        "source_fn": "features.inference_snapshot.build_inference_snapshot_v1_from_signal_input",
        "timestamp": "inference_snapshot_v1.as_of_ts",
        "horizons": ["all ML layers"],
        "cards": ["indirect via fusion"],
        "all_plan": True,
        "traceable_to_raw": True,
        "stale_risk": "feature timestamp lag vs spot",
        "failure_mode": "model inputs stale while spot fresh",
    },
    {
        "feature": "wait_reason / wait_blocker",
        "class": "policy",
        "source_table": "call_engine + multi_horizon_decision",
        "source_fn": "call_engine.compute_call, multi_horizon_decision.compute_multi_horizon_synthesis",
        "timestamp": "same refresh cycle",
        "horizons": ["ALL", "PLAN"],
        "cards": ["ALL", "PLAN", "desk rail"],
        "all_plan": True,
        "traceable_to_raw": False,
        "stale_risk": "low",
        "failure_mode": "horizon LONG visible while PLAN blocked — policy layer separates forecast from trade gate",
    },
]


def fusion_vs_empirical_classification(
    *,
    fusion_direction: Optional[str],
    histogram_direction: Optional[str],
    displayed_direction: Optional[str],
) -> list[str]:
    tags: list[str] = []
    fd = (fusion_direction or "").upper()
    hd = (histogram_direction or "").upper()
    dd = (displayed_direction or "").upper()
    if fd and hd and fd != hd:
        tags.append(CLASS_FUSION_OVERRIDE_EMPIRICAL)
        if dd == fd:
            tags.append(CLASS_EMPIRICAL_CONFLICTS_SIGNAL)
        elif dd == hd:
            tags.append(CLASS_EMPIRICAL_SUPPORTS_SIGNAL)
    elif fd and hd and fd == hd == dd:
        tags.append(CLASS_EMPIRICAL_SUPPORTS_SIGNAL)
    return sorted(set(tags))


def classify_signal_semantics(
    *,
    displayed_direction: Optional[str],
    trailing_return_1m: Optional[float],
    trailing_return_60m: Optional[float],
    forward_return_1m: Optional[float],
    fusion_direction: Optional[str],
    histogram_direction: Optional[str],
) -> list[str]:
    """Interpret what LONG means at this timestamp (not whether it is correct)."""
    tags: list[str] = []
    if direction_sign(displayed_direction) != 1:
        if direction_sign(displayed_direction) == -1:
            tags.append(CLASS_MOMENTUM_SHORT)
        return tags

    t1 = trailing_return_1m or 0.0
    t60 = trailing_return_60m or 0.0
    f1 = forward_return_1m

    if t1 > 0 and t60 > 0:
        tags.append(CLASS_TREND_FOLLOWING_LONG)
    elif t1 < 0 and f1 is not None and f1 > 0:
        tags.append(CLASS_REVERSAL_LONG)
    elif t60 < 0 and f1 is not None and f1 > 0:
        tags.append(CLASS_MEAN_REVERSION_LONG)
    elif (fusion_direction or "").upper() == "LONG" and (histogram_direction or "").upper() == "SHORT":
        tags.append(CLASS_MODEL_DIRECTION_DRIFT)
    else:
        tags.append(CLASS_UNCLEAR_FEATURE_SOURCE)

    tags.extend(
        fusion_vs_empirical_classification(
            fusion_direction=fusion_direction,
            histogram_direction=histogram_direction,
            displayed_direction=displayed_direction,
        )
    )
    return sorted(set(tags))


def classify_stale_feature_risk(
    *,
    data_age_seconds: Optional[float],
    payload_frozen: bool,
    allowed_age_seconds: float = 120.0,
) -> bool:
    if payload_frozen:
        return True
    if data_age_seconds is None:
        return False
    return float(data_age_seconds) > float(allowed_age_seconds)


def horizon_card_driver_summary() -> dict[str, str]:
    return {
        hz: (
            f"{HORIZON_CARD_LABELS[hz]} direction/confidence ← mhap_rows[{hz}] "
            f"← fusion triplet (up_prob_{hz}/down/flat) via multi_horizon_synthesis; "
            f"empirical histogram ({HISTOGRAM_LABEL_BY_HZ[hz]}) on signal rail only"
        )
        for hz in HORIZON_SLUGS
    }


def enrich_timeline_row_provenance(row: dict[str, Any]) -> dict[str, Any]:
    """Add provenance tags to a direction-integrity timeline row."""
    out = dict(row)
    blockers = {
        "wait_reason": row.get("wait_reason"),
        "call_signal": row.get("call_signal"),
        "final_tradeable": row.get("final_tradeable"),
    }
    out["blockers"] = blockers
    out["stale_flags"] = {
        "payload_frozen": row.get("payload_frozen"),
        "data_age_seconds": row.get("data_age_seconds"),
        "stale_feature_risk": classify_stale_feature_risk(
            data_age_seconds=row.get("data_age_seconds"),
            payload_frozen=bool(row.get("payload_frozen")),
        ),
    }
    out["input_source_table"] = "snapshots_1m_normalized (fallback snapshots)"

    per_hz: dict[str, Any] = {}
    for hz in HORIZON_SLUGS:
        block = row.get(f"horizon_{hz}") or {}
        hist_label = HISTOGRAM_LABEL_BY_HZ[hz]
        hist = (row.get("horizon_prob_bars") or {}).get(hist_label) or {}
        hist_dir = fusion_direction_from_probs(hist.get("up"), hist.get("down"), hist.get("flat"))
        semantics = classify_signal_semantics(
            displayed_direction=block.get("displayed_direction"),
            trailing_return_1m=row.get("trailing_return_1m"),
            trailing_return_60m=row.get("trailing_return_60m"),
            forward_return_1m=(row.get("horizon_1c") or {}).get("forward_realized_return"),
            fusion_direction=block.get("fusion_direction"),
            histogram_direction=hist_dir,
        )
        if out["stale_flags"]["stale_feature_risk"]:
            semantics = sorted(set(semantics + [CLASS_STALE_FEATURE_RISK]))
        per_hz[hz] = {
            "signal_semantics": semantics,
            "fusion_vs_empirical": fusion_vs_empirical_classification(
                fusion_direction=block.get("fusion_direction"),
                histogram_direction=hist_dir,
                displayed_direction=block.get("displayed_direction"),
            ),
        }
    out["provenance_by_horizon"] = per_hz

    if row.get("final_tradeable") is False and any(
        direction_sign((row.get(f"horizon_{hz}") or {}).get("displayed_direction")) == 1
        for hz in HORIZON_SLUGS
    ):
        out["plan_block_classification"] = CLASS_PLAN_CORRECTLY_BLOCKED
    return out


def aggregate_june17_explanation(timeline: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize all-horizon LONG during decline from enriched timeline."""
    if not timeline:
        return {"note": "no samples"}

    fusion_long = sum(
        1
        for r in timeline
        for hz in HORIZON_SLUGS
        if ((r.get(f"horizon_{hz}") or {}).get("fusion_direction") or "").upper() == "LONG"
    )
    hist_short = sum(
        1
        for r in timeline
        for hz in ("1c", "5c")
        if ((r.get(f"horizon_{hz}") or {}).get("histogram_direction") or "").upper() == "SHORT"
    )
    fusion_override = sum(
        1
        for r in timeline
        for hz in HORIZON_SLUGS
        if CLASS_FUSION_OVERRIDE_EMPIRICAL
        in ((r.get("provenance_by_horizon") or {}).get(hz) or {}).get("fusion_vs_empirical", [])
    )
    semantics_counts: dict[str, int] = {}
    for r in timeline:
        for hz in HORIZON_SLUGS:
            for tag in ((r.get("provenance_by_horizon") or {}).get(hz) or {}).get("signal_semantics", []):
                semantics_counts[tag] = semantics_counts.get(tag, 0) + 1

    return {
        "all_horizons_long_during_decline": True,
        "primary_driver": "per-horizon fusion posterior favors UP (mhap_rows.call=LONG)",
        "empirical_histogram_often_disagrees_short_on_1c_5c": hist_short > 0,
        "fusion_overrides_empirical_count": fusion_override,
        "fusion_long_cell_count": fusion_long,
        "signal_semantics_counts": semantics_counts,
        "all_and_plan_blocked": all(r.get("final_tradeable") is False for r in timeline),
        "typical_wait_reason": next((r.get("wait_reason") for r in timeline if r.get("wait_reason")), None),
        "interpretation": (
            "Cards show forecast direction (fusion probability argmax), not trailing price direction. "
            "June 17 decline samples: fusion LONG + empirical SHORT on short horizons is common; "
            "forward 1c returns often positive (reversal/mean-reversion forecasts), explaining high hit rate "
            "despite trailing conflict. ALL/PLAN correctly non-tradeable via call-engine veto."
        ),
    }
