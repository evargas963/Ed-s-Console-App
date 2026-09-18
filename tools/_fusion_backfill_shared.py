#!/usr/bin/env python3
"""Shared helpers for the fusion-backfill tool family (backfill_fusion_policy_complete_v1.py,
validate_fusion_backfill_complete_v1.py, backfill_fusion_policy_columns_expanded_v1.py).

Relocated 2026-09-17 (no-fallback lock repair, calibration_ml_governance group).

_classify_failure reads ONLY a producer-assigned typed reason (exc.reason) or a
distinct exception type. It does not inspect message text. When the producer
supplies no proven reason the category is UNCLASSIFIED.

MonteCarloStackInputError is not historical insufficiency: its reasons are
MISSING_CANONICAL_SPOT, INVALID_CANONICAL_SPOT, and LINEAGE_DISAGREEMENT.
"""
from __future__ import annotations

from ml_horizon import ML_HORIZON_SLUGS


def _incomplete_fused_sql() -> str:
    parts = [f"fused_move_prob_{hz} IS NULL" for hz in ML_HORIZON_SLUGS]
    return "(" + " OR ".join(parts) + ")"


def _classify_failure(exc: BaseException, hint: str = "") -> str:
    """Return the producer reason code, or UNCLASSIFIED.

    ``hint`` is accepted for call-site compatibility and is ignored: classification
    is never inferred from caller strings or exception messages.
    """
    del hint
    from ml_predict import ParallelRuntimeArtifactError

    reason = getattr(exc, "reason", None)
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    if isinstance(exc, ParallelRuntimeArtifactError):
        return "MISSING_ARTIFACTS"
    if isinstance(exc, FileNotFoundError):
        return "MISSING_ARTIFACTS"
    return "UNCLASSIFIED"
