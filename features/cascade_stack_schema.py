"""Cascade challenger run output shape (evaluation / audit; not production parallel)."""

from __future__ import annotations

from typing import Any, TypedDict

from features.cascade_stack_contract import CASCADE_STACK_SCHEMA_VERSION, CASCADE_UPSTREAM_BUNDLE_VERSION


class CascadeStageProbOutput(TypedDict, total=False):
    prob_up: float
    prob_down: float
    prob_flat: float
    available: bool


class CascadeChallengerRunRecord(TypedDict, total=False):
    architecture: str  # "cascade"
    schema_version: str
    upstream_bundle_version: str
    stages: dict[str, Any]
    fusion: dict[str, Any]
    model_outputs: dict[str, Any]
    lineage: dict[str, Any]
    parallel_runtime: bool


def build_cascade_challenger_run_metadata(
    *,
    feature_cache_key_prefix: str | None = None,
    data_fingerprint: str | None = None,
    ml_horizon_slug: str | None = None,
) -> dict[str, Any]:
    """References for evaluation manifests (same keys as parallel scheduler where applicable)."""
    return {
        "architecture": "cascade",
        "schema_version": CASCADE_STACK_SCHEMA_VERSION,
        "upstream_bundle_version": CASCADE_UPSTREAM_BUNDLE_VERSION,
        "feature_cache_key_prefix": feature_cache_key_prefix,
        "data_fingerprint": data_fingerprint,
        "ml_horizon_slug": ml_horizon_slug,
    }
