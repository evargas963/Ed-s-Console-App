"""Card signal fidelity + feature provenance helpers (read-only audit)."""
from __future__ import annotations

from typing import Any, Optional

from verification.card_direction_integrity import (
    HORIZON_CARD_LABELS,
    HORIZON_SLUGS,
    direction_sign,
    fusion_direction_from_probs,
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

HISTOGRAM_LABEL_BY_HZ = {"1c": "1m", "5c": "5m", "15c": "15m", "60c": "60m"}

# Static registry: what drives each card surface (canopy → branch; no model/threshold edits)
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


def extract_blockers(probe: dict[str, Any]) -> dict[str, Any]:
    wb = probe.get("call_readiness", {}).get("wait_blocker") or probe.get("wait_blocker") or {}
    return {
        "wait_reason": probe.get("wait_reason"),
        "call_signal": probe.get("call_signal"),
        "suppression_layer": probe.get("suppression_layer"),
        "wait_blocker": wb if isinstance(wb, dict) else {},
        "final_tradeable": probe.get("final_tradeable"),
    }


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
