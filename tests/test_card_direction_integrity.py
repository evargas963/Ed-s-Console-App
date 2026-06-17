"""Tests for card direction integrity classification helpers (deterministic)."""
from __future__ import annotations

from verification.card_direction_integrity import (
    CLASS_FROZEN_BACKEND,
    CLASS_STALE_PAYLOAD,
    CLASS_VALID_REVERSAL,
    aggregate_horizon_metrics,
    classify_long_during_decline,
    direction_hit,
    direction_sign,
    find_decline_intervals,
    forward_return_at_index,
    mhap_direction_map,
    stale_conflict,
    trailing_conflict,
    trailing_return_at_index,
    ui_card_state_from_probe,
)


def test_direction_hit_long_forward_positive():
    assert direction_hit("LONG", 0.002) is True


def test_direction_hit_long_forward_negative():
    assert direction_hit("LONG", -0.003) is False


def test_reversal_candidate_long_trailing_neg_forward_pos():
    tags = classify_long_during_decline(
        displayed_direction="LONG",
        trailing_return_1m=-0.001,
        trailing_return_60m=-0.01,
        forward_return_1m=0.002,
        forward_return_60m=-0.001,
        data_age_seconds=30,
        payload_frozen=False,
        fusion_stayed_long=True,
        histogram_stayed_long=True,
        final_tradeable=False,
    )
    assert CLASS_VALID_REVERSAL in tags


def test_stale_conflict_long_trailing_negative_stale_timestamp():
    assert trailing_conflict("LONG", -0.002) is True
    assert stale_conflict(trailing_conflict_flag=True, data_age_seconds=300.0) is True
    tags = classify_long_during_decline(
        displayed_direction="LONG",
        trailing_return_1m=-0.002,
        trailing_return_60m=-0.01,
        forward_return_1m=-0.001,
        forward_return_60m=-0.002,
        data_age_seconds=300.0,
        payload_frozen=False,
        fusion_stayed_long=True,
        histogram_stayed_long=True,
        final_tradeable=False,
    )
    assert CLASS_STALE_PAYLOAD in tags


def test_frozen_payload_classification():
    tags = classify_long_during_decline(
        displayed_direction="LONG",
        trailing_return_1m=-0.002,
        trailing_return_60m=-0.01,
        forward_return_1m=-0.001,
        forward_return_60m=-0.002,
        data_age_seconds=30.0,
        payload_frozen=True,
        fusion_stayed_long=True,
        histogram_stayed_long=True,
        final_tradeable=False,
    )
    assert CLASS_FROZEN_BACKEND in tags


def test_all_plan_non_tradeable_does_not_erase_horizon_direction():
    ui = ui_card_state_from_probe(
        {
            "final_bias": "LONG",
            "final_tradeable": False,
            "entry_state": "no_setup",
            "mhap_rows": [{"horizon": "1c", "call": "LONG", "confidence": 0.41}],
        }
    )
    assert ui["ALL_direction"] == "FLAT"
    assert ui["PLAN_state"] == "NO SETUP"
    mhap = mhap_direction_map([{"horizon": "1c", "call": "LONG"}])
    assert mhap["1c"] == "LONG"


def test_find_decline_interval_on_synthetic_series():
    ts = [float(i * 60) for i in range(120)]
    prices = [100.0 - i * 0.05 for i in range(120)]
    intervals = find_decline_intervals(ts, prices, min_decline_minutes=30, min_drawdown_fraction=0.001)
    assert intervals


def test_forward_and_trailing_returns():
    prices = [100.0, 101.0, 102.0, 101.0, 100.0]
    assert trailing_return_at_index(prices, 2, 2) == 0.02
    assert forward_return_at_index(prices, 1, 2) == 0.0


def test_aggregate_horizon_metrics():
    rows = [
        {
            "horizon_1c": {
                "direction_hit": True,
                "trailing_conflict": True,
                "stale_conflict": False,
            }
        },
        {
            "horizon_1c": {
                "direction_hit": False,
                "trailing_conflict": True,
                "stale_conflict": True,
            }
        },
    ]
    m = aggregate_horizon_metrics(rows, "1c")
    assert m["direction_hits"] == 1
    assert m["direction_misses"] == 1
    assert m["trailing_conflict_count"] == 2


def test_direction_sign_neutral():
    assert direction_sign("WAIT") == 0
    assert direction_sign("FLAT") == 0
