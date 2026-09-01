"""math_probabilities.compute_volume_oi_ratio/flow_imbalance_normalized_with_fallback
must not treat a missing (None) volume as a dormant zero -- collapsing "unknown" into
"zero" silently invents a bearish/bullish signal that was never observed."""
from __future__ import annotations

from math_probabilities import compute_volume_oi_ratio, flow_imbalance_normalized_with_fallback


def test_volume_oi_ratio_does_not_treat_missing_volume_as_dormant_zero():
    exposures = {
        500.0: {
            "call_volume": None,
            "put_volume": None,
            "call_oi": 100.0,
            "put_oi": 100.0,
        }
    }

    out = compute_volume_oi_ratio(exposures, 500.0)

    assert out["ratio"] is None
    assert out["label"] == "missing_volume"


def test_volume_oi_ratio_does_not_treat_missing_oi_as_zero_oi():
    exposures = {
        500.0: {
            "call_volume": 10.0,
            "put_volume": 5.0,
            "call_oi": None,
            "put_oi": None,
        }
    }

    out = compute_volume_oi_ratio(exposures, 500.0)

    assert out["ratio"] is None
    assert out["label"] == "missing_oi"


def test_flow_imbalance_volume_fallback_fails_closed_when_volume_missing():
    exposures = {
        500.0: {
            "call_volume": None,
            "put_volume": None,
            "call_bid_size": 0.0,
            "call_ask_size": 0.0,
            "put_bid_size": 0.0,
            "put_ask_size": 0.0,
        }
    }

    assert flow_imbalance_normalized_with_fallback(exposures, 500.0) == (None, "none")
