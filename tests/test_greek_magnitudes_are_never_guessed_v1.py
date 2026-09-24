"""Greek-vote magnitudes are never guessed (audit P0, 2026-09-23).

No producer computes a DEX magnitude, so it defaulted to "negligible" -- the Greeks vote's
net-delta leg never counted, silently. The Call also turned a missing magnitude into
"moderate", greek_bias scored any unknown label 0.7, and a missing net GEX was labelled
"negligible". Unknown now stays unknown and contributes nothing.
"""
from __future__ import annotations

import inspect

from math_exposure_core import gex_magnitude_label, greek_bias


def test_an_unknown_magnitude_contributes_nothing():
    # a strong net delta with an unknown magnitude cannot move the vote
    assert greek_bias(5e9, None, None, dex_magnitude=None) == "neutral"
    assert greek_bias(5e9, None, None, dex_magnitude="not-a-label") == "neutral"
    # a known magnitude still counts
    assert greek_bias(5e9, None, 0.5, dex_magnitude="large") == "bullish"


def test_absent_net_gex_is_not_labelled_negligible():
    assert gex_magnitude_label(None) is None
    assert gex_magnitude_label(0.0) == "negligible"


def test_no_default_magnitude_is_substituted_anywhere():
    import call_engine
    import market_state
    assert 'or "moderate"' not in inspect.getsource(call_engine)
    src = inspect.getsource(market_state)
    assert 'getattr(consensus_summary, "dex_magnitude"' not in src
    assert market_state.MarketState.__dataclass_fields__["dex_magnitude"].default is None
