"""stack_bundle_eval_v1 fail-closed probability helpers and authority gates."""

from __future__ import annotations

from arch_competition.stack_bundle_eval_v1 import (
    POLICY_CALIBRATION_MAX_ECE,
    _authority_block,
    _dict_to_probs,
    _fusion_branch_to_prob_dict,
    _norm_triplet,
    _outcome_class_index,
    _probs_from_fusion_branch,
    _weighted_blend_probs,
    pack_metrics_for_probs,
)
import ml_predict as mp
from calibration.statistical_integrity import MIN_SAMPLES_STATISTICAL


def test_norm_triplet_none_on_degenerate_sum():
    assert _norm_triplet(0.0, 0.0, 0.0) is None


def test_norm_triplet_none_on_nan_inputs():
    assert _norm_triplet(float("nan"), 0.5, 0.5) is None


def test_outcome_class_index_none_for_missing_or_invalid():
    assert _outcome_class_index(None) is None
    assert _outcome_class_index("") is None
    assert _outcome_class_index("sideways") is None
    assert _outcome_class_index("up") == 0
    assert _outcome_class_index("FLAT") == 2


def test_dict_to_probs_none_when_any_key_missing():
    assert _dict_to_probs({"up": 0.5, "down": 0.5}) is None
    assert _dict_to_probs({}) is None


def test_probs_from_fusion_branch_none_when_prob_fields_missing():
    branch = {"available": True, "prob_up": 0.4}
    assert _probs_from_fusion_branch(branch) is None


def test_fusion_branch_to_prob_dict_none_when_uniform_defaults_would_apply():
    branch = {"available": True}
    assert _fusion_branch_to_prob_dict(branch) is None


def test_weighted_blend_probs_partial_xgb_lstm_renormalizes():
    xgb = {"up": 0.8, "down": 0.1, "flat": 0.1}
    lstm = {"up": 0.2, "down": 0.5, "flat": 0.3}
    out = _weighted_blend_probs(mp, "SPY", xgb_d=xgb, lstm_d=lstm, tr_d=None)
    assert out is not None
    # 0.40/(0.40+0.35)*xgb + 0.35/(0.40+0.35)*lstm on up leg
    expected_up = 0.8 * (0.40 / 0.75) + 0.2 * (0.35 / 0.75)
    assert abs(out[0] - expected_up) < 1e-9


def test_weighted_blend_probs_full_triple_delegates_to_weighted_average(monkeypatch):
    xgb = {"up": 0.4, "down": 0.3, "flat": 0.3}
    lstm = {"up": 0.4, "down": 0.3, "flat": 0.3}
    tr = {"up": 0.4, "down": 0.3, "flat": 0.3}
    calls: list[tuple] = []

    def _fake_wa(ticker, xgb_p, lstm_p, trans_p, collapsed=None):
        calls.append((ticker, collapsed))
        return {"up": 0.34, "down": 0.33, "flat": 0.33}

    monkeypatch.setattr(mp, "_active_base_collapse_flags", lambda _t: set())
    monkeypatch.setattr(mp, "_weighted_average", _fake_wa)
    out = _weighted_blend_probs(mp, "SPY", xgb_d=xgb, lstm_d=lstm, tr_d=tr)
    assert out == [0.34, 0.33, 0.33]
    assert calls == [("SPY", set())]


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
            "calibration_top_predicted_class_ece": POLICY_CALIBRATION_MAX_ECE - 0.05,
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


def test_authority_policy_calibration_above_threshold():
    by_config = {
        "xgb_only": {
            "multiclass_log_loss": 0.9,
            "n_rows_scored": 100,
            "calibration_top_predicted_class_ece": POLICY_CALIBRATION_MAX_ECE + 0.01,
        },
        "full_fusion": {
            "multiclass_log_loss": 1.0,
            "n_rows_scored": 100,
            "calibration_top_predicted_class_ece": 0.2,
        },
    }
    auth = _authority_block(by_config, min_rows=50, min_delta_log_loss=0.02)
    assert auth["policy_calibration_status"] == "above_threshold"
    assert auth["policy_calibration_may_proceed_heuristic"] is False


def test_pack_metrics_includes_regime_slices_when_rows_provided():
    n = MIN_SAMPLES_STATISTICAL
    y = [i % 3 for i in range(n)]
    templates = [[0.7, 0.2, 0.1], [0.2, 0.7, 0.1], [0.1, 0.2, 0.7]]
    probs = [templates[i % 3] for i in range(n)]
    rows = [{"vix_level": 12.0 if i % 2 == 0 else 20.0} for i in range(n)]
    m = pack_metrics_for_probs("test", y, probs, rows_used=rows)
    assert "regime_slices" in m
    assert "regime_conditional_ece" in m
    assert "low" in m["regime_slices"]

