"""
Fusion stack overlay: non-MVP tabular context for ML engineering (pred_*, walls, et_hour, …).

MVP canonical fields must come only from InferenceSnapshotV1 — never duplicated from
SignalInput or legacy snapshot dicts on this path. Use `strip_mvp_keys_from_fusion_overlay`
and `assert_fusion_overlay_has_no_mvp_keys` to enforce.
"""

from __future__ import annotations

from typing import Any, Mapping

from canonical_distances import canonicalize_distance_read

from features.db_feature_adapter import build_db_mvp_feature_row
from features.mvp_source_coercion import MvpFeatureSourceError
from features.xgb_model_input import (
    MVP_LEGACY_KEYS,
    validate_inference_snapshot_v1_envelope,
    XgbInferenceInputError,
)


class FusionModelInputError(ValueError):
    """Invalid InferenceSnapshotV1 or illegal MVP keys on the fusion overlay path."""


def similar_setup_filters_from_canonical_features(features: dict[str, Any]) -> dict[str, Any]:
    """
    Parameters for `db.get_similar_setups` derived from MVP canonical feature row only
    (not from raw SignalInput fields).
    """
    z = features.get("structure.zone")
    vs = features.get("anchor.vwap_side")
    nad = features.get("structure.nearest_above_dist")
    nbd = features.get("structure.nearest_below_dist")
    nad_f, nbd_f = canonicalize_distance_read(nad, nbd)
    return {
        "zone": z,
        "vwap_side": vs,
        "zone_fallback": z is None,
        "vwap_side_fallback": vs is None,
        "nearest_above_dist": nad_f,
        "nearest_below_dist": nbd_f,
    }


def similar_setup_filters_from_db_snapshot_row(snapshot_row: Mapping[str, Any]) -> dict[str, Any]:
    """
    Same SQL filter semantics as production: DB column semantics → canonical MVP row
    (``build_db_mvp_feature_row``) → ``similar_setup_filters_from_canonical_features``.

    Replay / diagnostics must use this (or full InferenceSnapshotV1) — not parallel reads of
    legacy columns into SQL without the adapter.
    """
    if not isinstance(snapshot_row, Mapping):
        raise FusionModelInputError(
            f"snapshot_row must be a Mapping for similar_setup_filters, "
            f"got {type(snapshot_row).__name__!r}"
        )
    try:
        canon = build_db_mvp_feature_row(dict(snapshot_row))
    except MvpFeatureSourceError as e:
        raise FusionModelInputError(f"DB row cannot be coerced to canonical MVP for similarity: {e}") from e
    return similar_setup_filters_from_canonical_features(canon)


def strip_mvp_keys_from_fusion_overlay(d: dict[str, Any]) -> dict[str, Any]:
    """Remove legacy MVP tabular keys if present (defensive)."""
    return {k: v for k, v in d.items() if k not in MVP_LEGACY_KEYS}


def assert_fusion_overlay_has_no_mvp_keys(overlay: dict[str, Any]) -> None:
    """Fail closed if any MVP legacy key appears in the fusion model overlay."""
    bad = set(overlay.keys()) & MVP_LEGACY_KEYS
    if bad:
        raise FusionModelInputError(
            f"fusion model overlay must not contain MVP keys (use InferenceSnapshotV1 only): {sorted(bad)}"
        )


def validate_inference_snapshot_for_fusion_stack(snap: Any) -> None:
    """Envelope + canonical row shape; same as XGB tabular envelope (no spot>0 requirement)."""
    try:
        validate_inference_snapshot_v1_envelope(snap)
    except XgbInferenceInputError as e:
        raise FusionModelInputError(str(e)) from e


_META_CATEGORICAL_COLUMNS: frozenset[str] = frozenset(
    {
        "prev_zone",
        "candle_direction",
        "session_bucket",
        "vix_bucket",
        "charm_direction",
        "charm_magnitude",
        "iv_direction",
        "qqq_vs_spy",
        "iwm_risk_signal",
        "combined_signal",
        "combined_conviction",
    }
)

# Stable ordinal maps — training + inference must share these (meta v2 tabular ingest).
_META_CATEGORICAL_ORDINALS: dict[str, dict[str, float]] = {
    "prev_zone": {
        "pin_bull": 0.0,
        "pin_bear": 1.0,
        "pin_neutral": 2.0,
        "pin_chaos": 3.0,
        "breakout": 4.0,
        "breakdown": 5.0,
    },
    "candle_direction": {"up": 1.0, "down": -1.0, "flat": 0.0},
    "session_bucket": {"open": 0.0, "mid": 1.0, "close": 2.0, "power_hour": 3.0},
    "vix_bucket": {"low": 0.0, "normal": 1.0, "elevated": 2.0, "extreme": 3.0},
    "charm_direction": {"positive": 1.0, "negative": -1.0, "neutral": 0.0},
    "charm_magnitude": {"low": 0.0, "medium": 1.0, "high": 2.0},
    "iv_direction": {"up": 1.0, "down": -1.0, "flat": 0.0},
    "qqq_vs_spy": {"leading": 1.0, "lagging": -1.0, "inline": 0.0},
    "iwm_risk_signal": {"risk_on": 1.0, "risk_off": -1.0, "neutral": 0.0},
    "combined_signal": {"long": 1.0, "short": -1.0, "wait": 0.0},
    "combined_conviction": {"high": 2.0, "medium": 1.0, "low": 0.0},
}


def _meta_encode_column_value(column: str, raw: Any) -> float:
    from numeric_contract import float_finite_or_none

    if column in _META_CATEGORICAL_COLUMNS:
        if raw is None or raw == "":
            return 0.0
        key = str(raw).strip().lower()
        mapped = _META_CATEGORICAL_ORDINALS.get(column, {}).get(key)
        if mapped is not None:
            return float(mapped)
        return 0.0
    v = float_finite_or_none(raw)
    return float(v) if v is not None else 0.0


def meta_tabular_vector_from_overlay(overlay: Mapping[str, Any]) -> list[float]:
    """Raw fusion-overlay columns → fixed-order float vector for meta-learner v2."""
    from governed_stack_contract import meta_tabular_feature_order

    return [_meta_encode_column_value(col, overlay.get(col)) for col in meta_tabular_feature_order()]


def meta_tabular_input_dim() -> int:
    from governed_stack_contract import meta_tabular_feature_order

    return len(meta_tabular_feature_order())


def apply_ablation_knockout_columns(
    base: Mapping[str, Any],
    permuted: Mapping[str, Any],
    columns: list[str],
) -> dict[str, Any]:
    """Layer-scoped knockout: clean base with permuted values only on ``columns``."""
    out = dict(base)
    for col in columns:
        if col in permuted:
            out[col] = permuted[col]
    return out
