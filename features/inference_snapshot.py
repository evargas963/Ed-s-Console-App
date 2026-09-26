"""
Model-agnostic live inference snapshot (V1) built from Tier B / L1 payload + MVP features.
"""

from __future__ import annotations

from typing import Any

from features.canonical_contract import (
    CANONICAL_FEATURE_CONTRACT_VERSION,
    CANONICAL_FEATURE_TIMEFRAME,
    INFERENCE_SNAPSHOT_SOURCE_LIVE_L1,
    INFERENCE_SNAPSHOT_TYPE,
    get_mvp_feature_names,
    validate_feature_contract_row,
)

# Allowed `source` values for InferenceSnapshotV1 (envelope audit).
_INFERENCE_SNAPSHOT_ALLOWED_SOURCES: frozenset[str] = frozenset(
    {INFERENCE_SNAPSHOT_SOURCE_LIVE_L1, "db_snapshot_row"}
)
from features.db_feature_adapter import build_db_mvp_feature_row
from instrument_identity import ticker_storage_key


def build_feature_lineage_map(
    features: dict[str, Any],
    *,
    envelope_source: str,
    transform: str = "canonical_mvp_adapter",
) -> dict[str, dict[str, Any]]:
    """
    Per-field lineage for every MVP canonical feature: source, transform, fallback_flag.
    """
    lineage: dict[str, dict[str, Any]] = {}
    for key in get_mvp_feature_names():
        val = features.get(key)
        lineage[key] = {
            "source": envelope_source,
            "transform": transform,
            "fallback_flag": val is None,
        }
    return lineage


def _feature_quality_from_row(features: dict[str, Any]) -> dict[str, Any]:
    present = [k for k, v in features.items() if v is not None]
    missing = [k for k, v in features.items() if v is None]
    return {
        "present_count": len(present),
        "missing_count": len(missing),
        "missing_fields": missing,
    }


def build_inference_snapshot_v1_from_feature_row(
    *,
    ticker: str,
    expiry: str | None,
    as_of_ts: float | None,
    features: dict[str, Any],
    source: str = INFERENCE_SNAPSHOT_SOURCE_LIVE_L1,
) -> dict[str, Any]:
    """
    Wrap an already-built MVP canonical feature row (e.g. from DB adapter) in InferenceSnapshotV1.

    No L1 payload — used for replay, training utilities, and tests.
    """
    ok, errs = validate_feature_contract_row(features)
    if not ok:
        raise ValueError(f"Invalid MVP feature row: {errs}")

    ts_f: float | None
    try:
        ts_f = float(as_of_ts) if as_of_ts is not None else None
    except (TypeError, ValueError):
        ts_f = None

    out: dict[str, Any] = {
        "snapshot_type": INFERENCE_SNAPSHOT_TYPE,
        "feature_contract_version": CANONICAL_FEATURE_CONTRACT_VERSION,
        "canonical_timeframe": CANONICAL_FEATURE_TIMEFRAME,
        "ticker": ticker_storage_key(ticker),  # RC-345/F25: canonical serving-snapshot identity
        "expiry": expiry,
        "as_of_ts": ts_f,
        "features": features,
        "feature_lineage": build_feature_lineage_map(features, envelope_source=source),
        "feature_quality": _feature_quality_from_row(features),
        "source": source,
    }
    _assert_inference_snapshot_v1(out)
    return out


def build_inference_snapshot_v1_from_db_row(
    *,
    ticker: str,
    expiry: str | None,
    as_of_ts: float | None,
    db_row: dict[str, Any],
) -> dict[str, Any]:
    """Build InferenceSnapshotV1 from a normalized DB / snapshot row dict (no L1 payload)."""
    features = build_db_mvp_feature_row(db_row)
    return build_inference_snapshot_v1_from_feature_row(
        ticker=ticker,
        expiry=expiry,
        as_of_ts=as_of_ts,
        features=features,
        source="db_snapshot_row",
    )






def _assert_inference_snapshot_v1(snap: dict[str, Any]) -> None:
    """Hard assertions for mandatory fields and internal consistency."""
    if snap.get("snapshot_type") != INFERENCE_SNAPSHOT_TYPE:
        raise ValueError("InferenceSnapshotV1: snapshot_type mismatch")
    if snap.get("feature_contract_version") != CANONICAL_FEATURE_CONTRACT_VERSION:
        raise ValueError("InferenceSnapshotV1: feature_contract_version mismatch")
    if snap.get("canonical_timeframe") != CANONICAL_FEATURE_TIMEFRAME:
        raise ValueError("InferenceSnapshotV1: canonical_timeframe must be '1m'")
    src = snap.get("source")
    if src not in _INFERENCE_SNAPSHOT_ALLOWED_SOURCES:
        raise ValueError(
            f"InferenceSnapshotV1: source must be one of {sorted(_INFERENCE_SNAPSHOT_ALLOWED_SOURCES)}"
        )
    fq = snap.get("feature_quality")
    if not isinstance(fq, dict):
        raise ValueError("InferenceSnapshotV1: feature_quality missing or not a dict")
    pc = fq.get("present_count")
    mc = fq.get("missing_count")
    mf = fq.get("missing_fields")
    if not isinstance(pc, int) or not isinstance(mc, int):
        raise ValueError("InferenceSnapshotV1: feature_quality counts invalid")
    if not isinstance(mf, list):
        raise ValueError("InferenceSnapshotV1: missing_fields must be a list")
    if pc + mc != 10:
        raise ValueError("InferenceSnapshotV1: present_count + missing_count must equal 10")
    if len(mf) != mc:
        raise ValueError("InferenceSnapshotV1: missing_fields length must equal missing_count")
    feats = snap.get("features")
    if not isinstance(feats, dict):
        raise ValueError("InferenceSnapshotV1: features missing or not a dict")
    lineage = snap.get("feature_lineage")
    if not isinstance(lineage, dict):
        raise ValueError("InferenceSnapshotV1: feature_lineage missing or not a dict")
    for key in get_mvp_feature_names():
        entry = lineage.get(key)
        if not isinstance(entry, dict):
            raise ValueError(f"InferenceSnapshotV1: feature_lineage missing entry for {key!r}")
        for field in ("source", "transform", "fallback_flag"):
            if field not in entry:
                raise ValueError(f"InferenceSnapshotV1: feature_lineage[{key!r}] missing {field!r}")
        if entry["fallback_flag"] is not (feats.get(key) is None):
            raise ValueError(
                f"InferenceSnapshotV1: feature_lineage[{key!r}].fallback_flag inconsistent with features"
            )


# ── Operator-visible Tier-C field lineage (Lane A — metadata only, no calc change) ──













