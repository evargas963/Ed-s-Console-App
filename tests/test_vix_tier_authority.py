"""COH-SA: VIX tier classification — single authority (math_volatility.vix_tier_token).

Locks the 15/20/30 threshold contract shared between SignalInput.vix_bucket
(math_volatility.vix_bucket) and the L1 adaptive-materiality engine
(planes.l1_thresholds._vol_regime). Prior to this refactor each function carried
its own copy of the cuts; this test guards against re-drift.
"""

from __future__ import annotations

















def test_vol_regime_label_delegates_to_vix_tier_token() -> None:
    """L1 adaptive-materiality regime token uses the same cuts as vix_bucket."""
    from planes.l1_thresholds import _vol_regime

    assert _vol_regime(10.0) == "low"
    assert _vol_regime(17.0) == "normal"
    assert _vol_regime(25.0) == "elevated"
    assert _vol_regime(40.0) == "high"
    # _vol_regime preserves its 'unknown' fallback on degenerate inputs.
    assert _vol_regime(None) == "unknown"
    assert _vol_regime(0) == "unknown"
    assert _vol_regime(-1.0) == "unknown"
    assert _vol_regime(float("nan")) == "unknown"


def test_single_authority_no_duplicate_thresholds_in_l1_thresholds() -> None:
    """Lock the refactor: planes/l1_thresholds._vol_regime must not re-inline the 15/20/30 cuts."""
    import inspect

    from planes.l1_thresholds import _vol_regime as fn

    src = inspect.getsource(fn)
    # Should reference the authority module, not the literal cuts.
    assert "vix_tier_token" in src
    assert "15.0" not in src
    assert "20.0" not in src
    assert "30.0" not in src
