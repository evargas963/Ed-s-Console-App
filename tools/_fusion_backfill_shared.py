#!/usr/bin/env python3
"""Shared helpers for the fusion-backfill tool family (backfill_fusion_policy_complete_v1.py,
validate_fusion_backfill_complete_v1.py, backfill_fusion_policy_columns_expanded_v1.py).

Relocated 2026-09-17 (no-fallback lock repair, calibration_ml_governance group): both
helpers used to live in tools/legacy/horizon_7/backfill_fusion_policy_columns_v1.py, a
quarantined file deleted along with the rest of that directory (every file there carried an
identical "DEPRECATED -- 7-horizon era... do not run against post-D3 databases" banner).
Neither helper is specific to the deprecated 7-horizon schema; they were only defined
alongside it incidentally. Given three separate files import these, they are collected here
as the ONE shared producer rather than duplicated three times.
"""
from __future__ import annotations

from ml_horizon import ML_HORIZON_SLUGS


def _incomplete_fused_sql() -> str:
    parts = [f"fused_move_prob_{hz} IS NULL" for hz in ML_HORIZON_SLUGS]
    return "(" + " OR ".join(parts) + ")"


def _classify_failure(exc: BaseException, hint: str = "") -> str:
    from features.fusion_model_input import FusionModelInputError
    from features.lstm_sequence_input import LstmSequenceInputError, TransformerSequenceInputError
    from features.monte_carlo_stack_input import MonteCarloStackInputError
    from features.xgb_model_input import XgbInferenceInputError
    from ml_predict import ParallelRuntimeArtifactError

    s = f"{hint} {exc!r}".lower()
    if isinstance(exc, MonteCarloStackInputError):
        return "HISTORICAL_CONTEXT_INSUFFICIENT"
    if isinstance(
        exc,
        (XgbInferenceInputError, LstmSequenceInputError, TransformerSequenceInputError, FusionModelInputError),
    ):
        return "FEATURE_RECONSTRUCTION_FAILURE"
    if isinstance(exc, ParallelRuntimeArtifactError):
        return "MISSING_ARTIFACTS"
    if isinstance(exc, FileNotFoundError):
        return "MISSING_ARTIFACTS"
    if isinstance(exc, ValueError) and "inference" in s:
        return "FEATURE_RECONSTRUCTION_FAILURE"
    if "no such file" in s or ".pkl" in s or "artifact" in s:
        return "MISSING_ARTIFACTS"
    if "sequence" in s or "bar" in s or "history" in s:
        return "HISTORICAL_CONTEXT_INSUFFICIENT"
    if isinstance(exc, (ImportError, OSError)) and "model" in s:
        return "MODEL_LOAD_FAILURE"
    return "OTHER"
