"""Layer 5 cascade_stack_schema + cascade_stack_contract: gap-fill contract locks."""

from __future__ import annotations


from features.cascade_stack_contract import (
    LSTM_STAGE_CASCADE_INPUT_FROM_XGB,
    TRANSFORMER_STAGE_CASCADE_INPUT_FROM_UPSTREAM,
)
















def test_upstream_tensor_name_constants_match_ml_predict_counts():
    assert len(LSTM_STAGE_CASCADE_INPUT_FROM_XGB) == 3
    assert len(TRANSFORMER_STAGE_CASCADE_INPUT_FROM_UPSTREAM) == 6
    assert LSTM_STAGE_CASCADE_INPUT_FROM_XGB[0] == "xgb_prob_up"
