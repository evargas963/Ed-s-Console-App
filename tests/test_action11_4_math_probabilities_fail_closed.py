"""Action 11.4: math_probabilities fail-closed on missing inputs."""

from __future__ import annotations

from math_probabilities import (
    compute_smart_money_signal,
    option_flow_book_imbalance,
)














def test_flow_imbalance_none_when_no_chain_data():
    assert option_flow_book_imbalance({}, 500.0) == (None, "none")


def test_smart_money_no_data_returns_none_fields():
    out = compute_smart_money_signal({}, 500.0)
    assert out["score"] is None
    assert out["direction"] is None
    assert out["label"] is None
