"""
XGBoost tabular inference: consume InferenceSnapshotV1 only for MVP / structural fields.

Legacy `engineer_single_snapshot` expects DB-shaped keys (`spot`, `zone`, …). This module maps
canonical MVP features from `InferenceSnapshotV1["features"]` to those keys and merges
non-MVP keys (e.g. `pred_*`, `et_hour`) from an optional fusion overlay — overlay must never
override MVP-mapped columns (fail-closed duplicate semantics: canonical wins). Empirical `pred_*`
from the overlay are not copied into engineered XGB columns (no same-tick model-output feedback).
"""

from __future__ import annotations

from typing import Any

from instrument_identity import ticker_storage_key
from features.canonical_contract import (
    CANONICAL_FEATURE_CONTRACT_VERSION,
    CANONICAL_FEATURE_TIMEFRAME,
    INFERENCE_SNAPSHOT_TYPE,
    validate_feature_contract_row,
)


# Exact canonical → legacy tabular keys (single source for XGB engineering row).
CANONICAL_TO_XGB_TABULAR: dict[str, str] = {
    "price.spot": "spot",
    "price.spread_pts": "spread",
    "structure.zone": "zone",
    "structure.nearest_above_dist": "nearest_above_dist",
    "structure.nearest_below_dist": "nearest_below_dist",
    "structure.net_gamma": "net_gamma",
    "anchor.vwap_side": "vwap_side",
    "anchor.vwap_dist_pts": "vwap_dist_pts",
    "liquidity.absorption_score": "absorption_score",
    "liquidity.continuation_score": "continuation_score",
}

MVP_LEGACY_KEYS: frozenset[str] = frozenset(CANONICAL_TO_XGB_TABULAR.values())


class XgbInferenceInputError(ValueError):
    """InferenceSnapshotV1 is missing, invalid, or incompatible with XGB tabular inference."""


def validate_inference_snapshot_v1_envelope(snap: Any) -> None:
    """Structural checks for InferenceSnapshotV1 (type, version, timeframe, feature row shape)."""
    if not isinstance(snap, dict):
        raise XgbInferenceInputError("InferenceSnapshotV1 must be a dict")
    if snap.get("snapshot_type") != INFERENCE_SNAPSHOT_TYPE:
        raise XgbInferenceInputError(
            f"expected snapshot_type {INFERENCE_SNAPSHOT_TYPE!r}, got {snap.get('snapshot_type')!r}"
        )
    if snap.get("feature_contract_version") != CANONICAL_FEATURE_CONTRACT_VERSION:
        raise XgbInferenceInputError(
            f"feature_contract_version mismatch: expected {CANONICAL_FEATURE_CONTRACT_VERSION!r}, "
            f"got {snap.get('feature_contract_version')!r}"
        )
    if snap.get("canonical_timeframe") != CANONICAL_FEATURE_TIMEFRAME:
        raise XgbInferenceInputError(
            f"canonical_timeframe must be {CANONICAL_FEATURE_TIMEFRAME!r}, "
            f"got {snap.get('canonical_timeframe')!r}"
        )
    tkr = snap.get("ticker")
    if tkr is None or not str(tkr).strip():
        raise XgbInferenceInputError("InferenceSnapshotV1 missing non-empty ticker")
    ts = snap.get("as_of_ts")
    if ts is None:
        raise XgbInferenceInputError("InferenceSnapshotV1 missing as_of_ts")
    try:
        float(ts)
    except (TypeError, ValueError) as e:
        raise XgbInferenceInputError(f"as_of_ts not numeric: {ts!r}") from e
    feats = snap.get("features")
    if not isinstance(feats, dict):
        raise XgbInferenceInputError("InferenceSnapshotV1 missing features dict")
    ok, errs = validate_feature_contract_row(feats)
    if not ok:
        raise XgbInferenceInputError(f"invalid canonical feature row: {errs}")


def validate_inference_snapshot_v1_for_xgb(snap: Any) -> None:
    """
    Envelope validation plus XGB requirements: positive spot must be present for tabular row.
    """
    validate_inference_snapshot_v1_envelope(snap)
    feats = snap["features"]
    spot = feats.get("price.spot")
    if spot is None:
        raise XgbInferenceInputError("XGB inference requires price.spot (missing in canonical features)")
    try:
        sf = float(spot)
    except (TypeError, ValueError) as e:
        raise XgbInferenceInputError(f"price.spot not numeric: {spot!r}") from e
    if not (sf > 0.0):
        raise XgbInferenceInputError(f"XGB inference requires price.spot > 0, got {sf!r}")


def _et_from_ts_utc(ts_utc: float) -> tuple[int, int]:
    from time_et import et_clock_from_ts_utc

    h, m, _ = et_clock_from_ts_utc(ts_utc)
    return h, m


def inference_snapshot_v1_to_engineering_snapshot(
    inference_snapshot_v1: dict[str, Any],
) -> dict[str, Any]:
    """
    Map canonical MVP features to legacy DB-shaped keys for `engineer_single_snapshot`.
    Does not include pred_* or other fusion fields — use `merge_xgb_fusion_overlay`.
    """
    validate_inference_snapshot_v1_for_xgb(inference_snapshot_v1)
    feats: dict[str, Any] = inference_snapshot_v1["features"]
    out: dict[str, Any] = {}
    for canon, leg in CANONICAL_TO_XGB_TABULAR.items():
        out[leg] = feats.get(canon)

    tkr = inference_snapshot_v1["ticker"]
    out["ticker"] = ticker_storage_key(tkr)  # RC-345/F25: canonical feature-input identity (train/serve parity)
    ts = float(inference_snapshot_v1["as_of_ts"])
    out["ts_utc"] = ts
    eh, em = _et_from_ts_utc(ts)
    out["et_hour"] = eh
    out["et_minute"] = em
    return out


def merge_xgb_fusion_overlay(
    base: dict[str, Any],
    fusion_feature_overlay: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Merge fusion / empirical fields into the tabular snapshot. Keys in MVP_LEGACY_KEYS are
    never taken from the overlay (canonical snapshot is authoritative).
    """
    if not fusion_feature_overlay:
        return base
    out = dict(base)
    for k, v in fusion_feature_overlay.items():
        if k in MVP_LEGACY_KEYS:
            continue
        out[k] = v
    return out


def assert_not_raw_l1_payload(d: Any) -> None:
    """
    Guardrail: reject obvious raw Tier B / L1 shapes at the XGB boundary (nested liquidity, duplicate anchors).
    """
    if not isinstance(d, dict):
        return
    if "liquidity_summary" in d and "features" not in d:
        raise XgbInferenceInputError(
            "raw L1-style payload forbidden for XGB: found top-level liquidity_summary "
            "(use InferenceSnapshotV1 with canonical features)"
        )
    if "spot_anchors" in d and "snapshot_type" not in d:
        raise XgbInferenceInputError(
            "raw L1-style payload forbidden for XGB: found spot_anchors (use InferenceSnapshotV1)"
        )
