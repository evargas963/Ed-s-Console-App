"""Layer 5 fusion_policy_contract chunk-1: gap-fill contract locks (Action 12.8 residuals)."""

from __future__ import annotations

from types import SimpleNamespace

from features.fusion_policy_contract import (
    fusion_payload_to_policy_columns,
    policy_dir_up_column,
    policy_move_column,
)


def test_fusion_none_yields_none_policy_probs():
    cols = fusion_payload_to_policy_columns("5c", None)
    assert cols["fused_move_prob_5c"] is None
    assert cols["fused_dir_up_prob_5c"] is None
    assert cols["fused_confidence_5c"] is None
    assert "fusion_unavailable" in cols["fused_stack_status_5c"]


def test_zero_sum_triplet_yields_none_policy_probs():
    fus = SimpleNamespace(
        available=True,
        prob_up=0.0,
        prob_down=0.0,
        prob_flat=0.0,
        fusion_confidence_score=0.5,
        contributing_models=[],
        dominant_direction="up",
        fusion_confidence="medium",
    )
    cols = fusion_payload_to_policy_columns("1c", fus)
    assert cols["fused_move_prob_1c"] is None
    assert cols["fused_dir_up_prob_1c"] is None


def test_non_numeric_triplet_yields_none_policy_probs():
    fus = SimpleNamespace(
        available=True,
        prob_up="bad",
        prob_down=0.3,
        prob_flat=0.2,
        fusion_confidence_score=0.5,
        contributing_models=[],
        dominant_direction="up",
        fusion_confidence="medium",
    )
    cols = fusion_payload_to_policy_columns("15c", fus)
    assert cols["fused_move_prob_15c"] is None


def test_policy_column_helpers():
    assert policy_move_column("60c") == "fused_move_prob_60c"
    assert policy_dir_up_column("60c") == "fused_dir_up_prob_60c"


def test_contributing_models_json_fail_emits_empty_array_when_avail():
    fus = SimpleNamespace(
        available=True,
        prob_up=0.5,
        prob_down=None,
        prob_flat=0.2,
        fusion_confidence_score=0.7,
        contributing_models=object(),
        dominant_direction="up",
        fusion_confidence="high",
    )
    cols = fusion_payload_to_policy_columns("5c", fus)
    assert cols["fused_contributing_models_5c"] == "[]"
    assert cols["fused_move_prob_5c"] is None


def test_complete_triplet_emits_bounded_probs_and_confidence():
    fus = SimpleNamespace(
        available=True,
        prob_up=0.6,
        prob_down=0.2,
        prob_flat=0.2,
        fusion_confidence_score=1.5,
        contributing_models=["xgb"],
        dominant_direction="up",
        fusion_confidence="high",
    )
    cols = fusion_payload_to_policy_columns("5c", fus)
    assert cols["fused_move_prob_5c"] == 0.8
    assert cols["fused_dir_up_prob_5c"] == 0.6
    assert cols["fused_confidence_5c"] == 1.0
    assert "fusion_ok" in cols["fused_stack_status_5c"]


def test_stack_status_uses_question_marks_when_dominant_direction_missing():
    fus = SimpleNamespace(
        available=True,
        prob_up=0.5,
        prob_down=0.25,
        prob_flat=0.25,
        fusion_confidence_score=0.8,
        contributing_models=[],
        fusion_confidence="high",
    )
    cols = fusion_payload_to_policy_columns("5c", fus)
    assert "dir=?" in cols["fused_stack_status_5c"]


def test_coh_i_g_contributing_models_json_truncation_named():
    """COH-I-G: cm_json truncation cap is a named constant, not a bare 8000 magic.
    The replay parser must tolerate truncated JSON; this guard locks the cap into a
    named symbol so it stays grep-discoverable and can be widened without churn.
    """
    import inspect
    from features.fusion_policy_contract import (
        FUSION_CONTRIBUTING_MODELS_JSON_MAX_CHARS,
        FUSION_STACK_STATUS_MAX_CHARS,
        fusion_payload_to_policy_columns,
    )
    import features.fusion_policy_contract as fpc

    assert FUSION_CONTRIBUTING_MODELS_JSON_MAX_CHARS == 8000
    assert FUSION_STACK_STATUS_MAX_CHARS == 500

    src = inspect.getsource(fpc)
    # The constant declaration line is allowed to have the literal; usage sites must use the name.
    body_only = src.replace("FUSION_CONTRIBUTING_MODELS_JSON_MAX_CHARS: int = 8000", "")
    body_only = body_only.replace("FUSION_STACK_STATUS_MAX_CHARS: int = 500", "")
    assert "[:8000]" not in body_only, "bare 8000 truncation still present"
    assert "[:500]" not in body_only, "bare 500 truncation still present"

    # Behavioral: cap honored when contributing_models is huge.
    from types import SimpleNamespace
    huge = [f"model_{i}" for i in range(10000)]
    fus = SimpleNamespace(
        available=True,
        prob_up=0.5, prob_down=0.3, prob_flat=0.2,
        fusion_confidence_score=0.7,
        contributing_models=huge,
        dominant_direction="up", fusion_confidence="high",
    )
    cols = fusion_payload_to_policy_columns("5c", fus)
    cm = cols["fused_contributing_models_5c"]
    assert cm is not None
    assert len(cm) <= FUSION_CONTRIBUTING_MODELS_JSON_MAX_CHARS
