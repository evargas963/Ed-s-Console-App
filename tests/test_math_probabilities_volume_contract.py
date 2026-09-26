"""math_probabilities.compute_volume_oi_ratio/option_flow_book_imbalance
must not treat a missing (None) volume as a dormant zero -- collapsing "unknown" into
"zero" silently invents a bearish/bullish signal that was never observed."""
from __future__ import annotations

from math_probabilities import (
    option_flow_book_imbalance,
)






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

    assert option_flow_book_imbalance(exposures, 500.0) == (None, "none")
