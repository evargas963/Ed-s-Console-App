"""
Cascade challenger stack — versioned upstream features and lineage rules.

Production default remains **parallel** (`run_unified_stack_ml_once`). This module defines the
**challenger-only** cascade contract: what may be passed between stages, and how evaluation
lineage must match shared canonical artifacts (same cache keys / contracts as parallel).

No alternate dataset generation: cascade training in `ml_scheduler.train_cascade_candidate` uses
the same `compute_feature_cache_key` / `feature_cache_dir` / `db_training_fingerprint` as parallel.
"""

from __future__ import annotations

from typing import Any, Mapping

from features.canonical_contract import CANONICAL_FEATURE_CONTRACT_VERSION, CANONICAL_FEATURE_TIMEFRAME
from features.xgb_model_input import (
    CANONICAL_TO_XGB_TABULAR,
    validate_inference_snapshot_v1_envelope,
    XgbInferenceInputError,
)

# Bundle version for upstream-derived tensors passed between cascade stages (inference).
CASCADE_UPSTREAM_BUNDLE_VERSION = "1"

# Schema version for cascade challenger run outputs (`features/cascade_stack_schema.py`).
CASCADE_STACK_SCHEMA_VERSION = "1"

# --- Approved upstream-derived features only (no raw L1 / SignalInput / legacy MVP dict) ---

# Stage 2 LSTM: confluence vector appended with exactly these 3 scalars from Stage 1 XGB:
#   [P(up), P(down), P(flat)] from `_predict_xgb` → `_probs_dict_to_arr` (same order as CLASS_NAMES).
LSTM_STAGE_CASCADE_INPUT_FROM_XGB = (
    "xgb_prob_up",
    "xgb_prob_down",
    "xgb_prob_flat",
)

# Stage 3 Transformer: sequence tensor appended per timestep with 6 scalars:
#   [xgb_up, xgb_down, xgb_flat, lstm_up, lstm_down, lstm_flat]
# from validated `_predict_xgb` and `_predict_lstm` outputs only.
TRANSFORMER_STAGE_CASCADE_INPUT_FROM_UPSTREAM = (
    "xgb_prob_up",
    "xgb_prob_down",
    "xgb_prob_flat",
    "lstm_prob_up",
    "lstm_prob_down",
    "lstm_prob_flat",
)

# Counts must match ml_predict._CASCADE_LSTM_CONF_EXTRA (3) and _CASCADE_TRANSFORMER_SEQ_EXTRA (6).
assert len(LSTM_STAGE_CASCADE_INPUT_FROM_XGB) == 3
assert len(TRANSFORMER_STAGE_CASCADE_INPUT_FROM_UPSTREAM) == 6


class CascadeChallengerError(ValueError):
    """Cascade challenger inference cannot load artifacts or complete staged pipeline."""


class CascadeLineageError(CascadeChallengerError):
    """Shared cache / contract / split lineage does not match evaluation requirements."""


class CascadeStageError(CascadeChallengerError):
    """A required upstream stage output is missing for downstream cascade."""


def validate_cascade_inference_lineage(
    inference_snapshot_v1: Mapping[str, Any] | None,
    *,
    expected_feature_contract_version: str | None = None,
    expected_canonical_timeframe: str | None = None,
    expected_data_fingerprint: str | None = None,
    actual_data_fingerprint: str | None = None,
) -> None:
    """
    Fail closed when optional expected lineage tokens do not match.

    Used for challenger evaluation parity with parallel (same `InferenceSnapshotV1` envelope
    and same training data fingerprint as recorded in scheduler manifests).
    """
    if inference_snapshot_v1 is None:
        raise CascadeLineageError("cascade challenger requires inference_snapshot_v1")

    try:
        validate_inference_snapshot_v1_envelope(inference_snapshot_v1)
    except XgbInferenceInputError as e:
        raise CascadeLineageError(str(e)) from e

    ev = expected_feature_contract_version
    if ev is not None and inference_snapshot_v1.get("feature_contract_version") != ev:
        raise CascadeLineageError(
            f"feature_contract_version mismatch: expected {ev!r}, "
            f"got {inference_snapshot_v1.get('feature_contract_version')!r}"
        )
    if ev is None and inference_snapshot_v1.get("feature_contract_version") != CANONICAL_FEATURE_CONTRACT_VERSION:
        # Default: must match live canonical contract
        raise CascadeLineageError(
            f"feature_contract_version must be {CANONICAL_FEATURE_CONTRACT_VERSION!r} for cascade challenger"
        )

    tf = expected_canonical_timeframe
    if tf is not None and inference_snapshot_v1.get("canonical_timeframe") != tf:
        raise CascadeLineageError(
            f"canonical_timeframe mismatch: expected {tf!r}, "
            f"got {inference_snapshot_v1.get('canonical_timeframe')!r}"
        )
    if tf is None and inference_snapshot_v1.get("canonical_timeframe") != CANONICAL_FEATURE_TIMEFRAME:
        raise CascadeLineageError(
            f"canonical_timeframe must be {CANONICAL_FEATURE_TIMEFRAME!r} for cascade challenger"
        )

    if expected_data_fingerprint is not None:
        if actual_data_fingerprint is None:
            raise CascadeLineageError(
                "expected_data_fingerprint set but actual_data_fingerprint missing — cannot prove shared cache lineage"
            )
        if actual_data_fingerprint != expected_data_fingerprint:
            raise CascadeLineageError(
                f"data_fingerprint mismatch: expected {expected_data_fingerprint!r}, got {actual_data_fingerprint!r}"
            )


def assert_no_legacy_mvp_in_fusion_overlay(overlay: Mapping[str, Any] | None) -> None:
    """Cascade stages use the same fusion overlay rules as parallel — no MVP keys."""
    forbidden = set(CANONICAL_TO_XGB_TABULAR.values())
    if overlay is None:
        return
    bad = forbidden & set(overlay.keys())
    if bad:
        raise CascadeChallengerError(
            f"cascade fusion overlay must not contain legacy MVP keys: {sorted(bad)}"
        )
