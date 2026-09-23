"""
No-fallback lock repair (2026-09-17): math_exposure_core.greek_bias used to default a
missing/unrecognized dex_magnitude or charm_magnitude to "moderate" (MAG_SCALE 0.7) --
a specific, meaningful weight standing in for "we don't know how significant this
exposure is." An unrecognized/unavailable magnitude must exclude that vote's
contribution entirely, not assume a moderate significance for it.
"""
from __future__ import annotations

from math_exposure import greek_bias


def test_none_dex_magnitude_excludes_delta_vote_entirely():
    """A large net_delta with dex_magnitude=None must not vote at all (moderate's 0.7
    scale would have crossed GREEK_BIAS_THRESHOLD on its own)."""
    with_known = greek_bias(1000.0, None, None, dex_magnitude="moderate", charm_magnitude=None)
    with_unavailable = greek_bias(1000.0, None, None, dex_magnitude=None, charm_magnitude=None)
    assert with_known == "bullish"
    assert with_unavailable == "neutral", (
        "an unavailable dex_magnitude must exclude the delta vote, not silently apply "
        "moderate's 0.7 scale"
    )


def test_none_charm_magnitude_excludes_charm_vote_entirely():
    # charm alone can never clear GREEK_BIAS_THRESHOLD (max charm contribution
    # GREEK_BIAS_CHARM_WEIGHT*1.0 == 0.5 == threshold, never strictly greater), so pair
    # it with a bullish put_call_oi_ratio contribution to make the charm vote's presence
    # or absence the deciding factor between "neutral" and "bullish".
    with_known = greek_bias(None, "buying", 0.5, dex_magnitude=None, charm_magnitude="large")
    with_unavailable = greek_bias(None, "buying", 0.5, dex_magnitude=None, charm_magnitude=None)
    assert with_known == "bullish"
    assert with_unavailable == "neutral", (
        "an unavailable charm_magnitude must exclude the charm vote, not silently apply "
        "moderate's 0.7 scale"
    )


def test_unrecognized_magnitude_string_also_excludes_the_vote():
    """A non-None but unrecognized magnitude label must not fall back to moderate
    either -- excluded the same as None, never silently treated as a known bucket."""
    result = greek_bias(1000.0, None, None, dex_magnitude="unrecognized_value", charm_magnitude=None)
    assert result == "neutral"


def test_default_parameters_are_none_not_moderate():
    import inspect

    sig = inspect.signature(greek_bias)
    assert sig.parameters["dex_magnitude"].default is None
    assert sig.parameters["charm_magnitude"].default is None
