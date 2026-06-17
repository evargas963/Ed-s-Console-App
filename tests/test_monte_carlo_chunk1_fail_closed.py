"""monte_carlo chunk-1: I-01 fallback contract for invalid inputs and mc_feature_dict."""

from __future__ import annotations

from monte_carlo import simulate


def test_simulate_invalid_spot_returns_unavailable_fallback():
    out = simulate(spot=0.0, iv=0.18)
    assert out.available is False
    assert out.fallback_used is True
    assert out.expected_adverse_excursion is None


def test_simulate_invalid_iv_returns_unavailable_fallback():
    out = simulate(spot=450.0, iv=0.0)
    assert out.available is False
    assert out.fallback_used is True


def test_simulate_success_populates_excursions_and_mc_feature_dict():
    out = simulate(
        spot=450.0,
        iv=0.18,
        horizon_bars=5,
        n_paths=500,
        seed=42,
        regime="pinning",
        regime_confidence="high",
        realized_vol=0.15,
        atr=1.5,
    )
    assert out.available is True
    assert out.simulation_ok is True
    assert out.fallback_used is False
    assert out.expected_adverse_excursion is not None
    assert out.expected_favorable_excursion is not None
    feats = out.mc_feature_dict()
    assert feats["source"] == "derived_mc_normalized"
    assert "expected_move" in feats
