"""Layer 5 cascade_stack_schema + cascade_stack_contract: gap-fill contract locks."""

from __future__ import annotations

import pytest

from features.cascade_stack_contract import (
    CASCADE_STACK_SCHEMA_VERSION,
    CASCADE_UPSTREAM_BUNDLE_VERSION,
    LSTM_STAGE_CASCADE_INPUT_FROM_XGB,
    TRANSFORMER_STAGE_CASCADE_INPUT_FROM_UPSTREAM,
    CascadeChallengerError,
    CascadeLineageError,
    assert_no_legacy_mvp_in_fusion_overlay,
    validate_cascade_inference_lineage,
)
from features.cascade_stack_schema import build_cascade_challenger_run_metadata
from tests.test_cascade_challenger_stack import _minimal_inf_v1


def test_build_cascade_challenger_run_metadata_fields():
    meta = build_cascade_challenger_run_metadata(
        feature_cache_key_prefix="pfx",
        data_fingerprint="fp1",
        ml_horizon_slug="5c",
    )
    assert meta["architecture"] == "cascade"
    assert meta["schema_version"] == CASCADE_STACK_SCHEMA_VERSION
    assert meta["upstream_bundle_version"] == CASCADE_UPSTREAM_BUNDLE_VERSION
    assert meta["feature_cache_key_prefix"] == "pfx"
    assert meta["data_fingerprint"] == "fp1"
    assert meta["ml_horizon_slug"] == "5c"


def test_validate_lineage_requires_inference_snapshot():
    with pytest.raises(CascadeLineageError, match="requires inference_snapshot_v1"):
        validate_cascade_inference_lineage(None)


def test_validate_lineage_rejects_wrong_explicit_contract_version():
    snap = _minimal_inf_v1()
    with pytest.raises(CascadeLineageError, match="feature_contract_version mismatch"):
        validate_cascade_inference_lineage(
            snap,
            expected_feature_contract_version="bogus",
        )


def test_validate_lineage_rejects_missing_actual_fingerprint():
    snap = _minimal_inf_v1()
    with pytest.raises(CascadeLineageError, match="actual_data_fingerprint missing"):
        validate_cascade_inference_lineage(
            snap,
            expected_data_fingerprint="abc",
            actual_data_fingerprint=None,
        )


def test_validate_lineage_accepts_matching_fingerprints():
    snap = _minimal_inf_v1()
    assert validate_cascade_inference_lineage(
        snap,
        expected_data_fingerprint="same",
        actual_data_fingerprint="same",
    ) is None  # matching fingerprints -> returns None (raises on mismatch)


def test_assert_no_legacy_mvp_allows_none_overlay():
    assert_no_legacy_mvp_in_fusion_overlay(None)


def test_assert_no_legacy_mvp_rejects_legacy_keys():
    with pytest.raises(CascadeChallengerError, match="legacy MVP keys"):
        assert_no_legacy_mvp_in_fusion_overlay({"spot": 450.0, "pred_1c_up_prob": 0.5})


def test_upstream_tensor_name_constants_match_ml_predict_counts():
    assert len(LSTM_STAGE_CASCADE_INPUT_FROM_XGB) == 3
    assert len(TRANSFORMER_STAGE_CASCADE_INPUT_FROM_UPSTREAM) == 6
    assert LSTM_STAGE_CASCADE_INPUT_FROM_XGB[0] == "xgb_prob_up"
