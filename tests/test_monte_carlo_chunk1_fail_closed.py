"""monte_carlo chunk-1: I-01 fallback contract for invalid inputs and mc_feature_dict."""

from __future__ import annotations

from monte_carlo import simulate


def test_simulate_invalid_spot_returns_unavailable_fallback():
    # horizon_bars is required since the BAR_MINUTES alignment removed the
    # dead DEFAULT_HORIZON; the fail-closed invariant is horizon-independent.
    out = simulate(spot=0.0, iv=0.18, horizon_bars=5)
    assert out.available is False
    assert out.fallback_used is True
    assert out.expected_adverse_excursion is None


def test_simulate_invalid_iv_returns_unavailable_fallback():
    out = simulate(spot=450.0, iv=0.0, horizon_bars=5)
    assert out.available is False
    assert out.fallback_used is True


