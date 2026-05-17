"""stack_bundle_eval_v1 fail-closed probability helpers and authority gates."""

from __future__ import annotations

from arch_competition.stack_bundle_eval_v1 import (
    _authority_block,
    _dict_to_probs,
    _fusion_branch_to_prob_dict,
    _norm_triplet,
    _probs_from_fusion_branch,
    pack_metrics_for_probs,
)
from calibration.statistical_integrity import MIN_SAMPLES_STATISTICAL


def test_norm_triplet_none_on_degenerate_sum():
    assert _norm_triplet(0.0, 0.0, 0.0) is None


def test_dict_to_probs_none_when_any_key_missing():
    assert _dict_to_probs({"up": 0.5, "down": 0.5}) is None
    assert _dict_to_probs({}) is None


def test_probs_from_fusion_branch_none_when_prob_fields_missing():
    branch = {"available": True, "prob_up": 0.4}
    assert _probs_from_fusion_branch(branch) is None


def test_fusion_branch_to_prob_dict_none_when_uniform_defaults_would_apply():
    branch = {"available": True}
    assert _fusion_branch_to_prob_dict(branch) is None


def test_pack_metrics_requires_min_samples_statistical():
    n = MIN_SAMPLES_STATISTICAL - 1
    y = [i % 3 for i in range(n)]
    templates = [[0.7, 0.2, 0.1], [0.2, 0.7, 0.1], [0.1, 0.2, 0.7]]
    probs = [templates[i % 3] for i in range(n)]
    m = pack_metrics_for_probs("test", y, probs)
    assert m.get("error") == "insufficient_rows_or_misaligned_probs"
    assert m["n_rows_scored"] == n


def test_pack_metrics_ok_at_min_samples_statistical():
    n = MIN_SAMPLES_STATISTICAL
    y = [i % 3 for i in range(n)]
    templates = [[0.7, 0.2, 0.1], [0.2, 0.7, 0.1], [0.1, 0.2, 0.7]]
    probs = [templates[i % 3] for i in range(n)]
    m = pack_metrics_for_probs("test", y, probs)
    assert m["n_rows_scored"] == n
    assert "multiclass_log_loss" in m


def test_authority_policy_calibration_missing_ece_blocks_heuristic():
    by_config = {
        "xgb_only": {
            "multiclass_log_loss": 0.9,
            "n_rows_scored": 100,
            "error": "insufficient_rows_or_misaligned_probs",
        },
        "full_fusion": {
            "multiclass_log_loss": 1.0,
            "n_rows_scored": 100,
        },
    }
    auth = _authority_block(by_config, min_rows=50, min_delta_log_loss=0.02)
    assert auth["authoritative_winner_config"] == "xgb_only"
    assert auth["policy_calibration_may_proceed_heuristic"] is False
    assert auth["policy_calibration_status"] == "missing_ece"
    assert auth["trade_plan_work_may_proceed_heuristic"] is False


def test_authority_policy_calibration_ok_when_ece_below_threshold():
    by_config = {
        "xgb_only": {
            "multiclass_log_loss": 0.9,
            "n_rows_scored": 100,
            "calibration_top_predicted_class_ece": 0.1,
        },
        "full_fusion": {
            "multiclass_log_loss": 1.0,
            "n_rows_scored": 100,
            "calibration_top_predicted_class_ece": 0.2,
        },
    }
    auth = _authority_block(by_config, min_rows=50, min_delta_log_loss=0.02)
    assert auth["policy_calibration_status"] == "ok"
    assert auth["policy_calibration_may_proceed_heuristic"] is True

