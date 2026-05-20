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
from features.live_feature_adapter import build_live_mvp_feature_row


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
        "ticker": (ticker or "").upper().strip(),
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


def build_inference_snapshot_v1_from_signal_input(inp: Any, *, as_of_ts: float | None = None) -> dict[str, Any]:
    """
    Build InferenceSnapshotV1 from `SignalInput` using the same adapter path as live L1
    (flat dict only — no `liquidity_summary` / `spot_anchors` on the wire).
    """
    def _dist_to_vwap_pts() -> float | None:
        """
        Map SignalInput.vwap_dist_pts to anchor.vwap_dist_pts (signed distance).

        Magnitude-only contract: only ``vwap_side == "below"`` negates; all other sides
        (including ``above`` and empty) return positive magnitude. Replay must use the
        same side convention as live L1 when comparing distances.
        """
        d = getattr(inp, "vwap_dist_pts", None)
        if d is None:
            return None
        side = (getattr(inp, "vwap_side", None) or "").lower()
        try:
            mag = abs(float(d))
        except (TypeError, ValueError):
            return None
        if side == "below":
            return -mag
        return mag

    # Keys must match live_feature_adapter.build_live_mvp_feature_row (spread_pts not spread).
    l1_equiv: dict[str, Any] = {
        "spot": getattr(inp, "spot", None),
        "spread_pts": getattr(inp, "spread", None),
        "zone": getattr(inp, "zone", None),
        "nearest_above_dist": getattr(inp, "nearest_above_dist", None),
        "nearest_below_dist": getattr(inp, "nearest_below_dist", None),
        "net_gamma": getattr(inp, "net_gamma", None),
        "vwap_side": getattr(inp, "vwap_side", None),
        "dist_to_vwap_pts": _dist_to_vwap_pts(),
    }
    # Authoritative decision/eval instant: prefer caller as_of, then bar refresh time.
    ts = as_of_ts
    if ts is None:
        ts = getattr(inp, "refresh_ts_utc", None)
    try:
        ts_f = float(ts) if ts is not None else None
    except (TypeError, ValueError):
        ts_f = None
    return build_inference_snapshot_v1(
        ticker=getattr(inp, "ticker", "") or "",
        expiry=getattr(inp, "expiry", None),
        as_of_ts=ts_f,
        l1_payload=l1_equiv,
    )


def build_inference_snapshot_v1(
    *,
    ticker: str,
    expiry: str | None,
    as_of_ts: float | None,
    l1_payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Build InferenceSnapshotV1: canonical MVP features + quality summary from live L1.

    Fails hard if `build_live_mvp_feature_row` raises `MvpFeatureSourceError` (invalid present
    source values) or if the row fails `validate_feature_contract_row` (e.g. spot ≤ 0).

    `expiry` uses the same convention as L1 scope: None means auto / unspecified expiry.
    `as_of_ts` comes from the explicit argument, else optional `l1_payload["as_of_ts"]` when the
    L1 producer stamped a decision instant there. Wall-clock `_server_build_ts` is not used
    (S017 — no silent ingestion clock in evaluation time).
    """
    features = build_live_mvp_feature_row(l1_payload)
    ok, errs = validate_feature_contract_row(features)
    if not ok:
        raise ValueError(f"Invalid MVP feature row: {errs}")

    ts = as_of_ts
    if ts is None:
        ts = l1_payload.get("as_of_ts")
    try:
        ts_f = float(ts) if ts is not None else None
    except (TypeError, ValueError):
        ts_f = None

    out: dict[str, Any] = {
        "snapshot_type": INFERENCE_SNAPSHOT_TYPE,
        "feature_contract_version": CANONICAL_FEATURE_CONTRACT_VERSION,
        "canonical_timeframe": CANONICAL_FEATURE_TIMEFRAME,
        "ticker": (ticker or "").upper().strip(),
        "expiry": expiry,
        "as_of_ts": ts_f,
        "features": features,
        "feature_lineage": build_feature_lineage_map(
            features, envelope_source=INFERENCE_SNAPSHOT_SOURCE_LIVE_L1
        ),
        "feature_quality": _feature_quality_from_row(features),
        "source": INFERENCE_SNAPSHOT_SOURCE_LIVE_L1,
    }
    _assert_inference_snapshot_v1(out)
    return out


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
