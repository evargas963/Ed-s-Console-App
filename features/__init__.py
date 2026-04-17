"""Canonical feature contract and adapters (1m-first MVP)."""

from features.canonical_contract import (
    ALLOWED_VWAP_SIDE_VALUES,
    ALLOWED_ZONE_VALUES,
    CANONICAL_FEATURE_CONTRACT_VERSION,
    CANONICAL_FEATURE_TIMEFRAME,
    INFERENCE_SNAPSHOT_SOURCE_LIVE_L1,
    get_mvp_feature_names,
    get_feature_spec,
    get_mvp_field_semantics,
    validate_feature_contract_row,
)
from features.mvp_source_coercion import MvpFeatureSourceError

__all__ = [
    "ALLOWED_VWAP_SIDE_VALUES",
    "ALLOWED_ZONE_VALUES",
    "CANONICAL_FEATURE_CONTRACT_VERSION",
    "CANONICAL_FEATURE_TIMEFRAME",
    "INFERENCE_SNAPSHOT_SOURCE_LIVE_L1",
    "MvpFeatureSourceError",
    "get_mvp_feature_names",
    "get_feature_spec",
    "get_mvp_field_semantics",
    "validate_feature_contract_row",
]
