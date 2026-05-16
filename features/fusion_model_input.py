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
    zone_missing = z is None
    vwap_missing = vs is None
    return {
        "zone": z if z is not None else "unknown",
        "vwap_side": vs if vs is not None else "unknown",
        "zone_fallback": zone_missing,
        "vwap_side_fallback": vwap_missing,
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
