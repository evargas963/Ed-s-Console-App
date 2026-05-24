"""COH-SA: VIX tier classification — single authority (math_volatility.vix_tier_token).

Locks the 15/20/30 threshold contract shared between SignalInput.vix_bucket
(math_volatility.vix_bucket) and the L1 adaptive-materiality engine
(planes.l1_thresholds._vol_regime). Prior to this refactor each function carried
its own copy of the cuts; this test guards against re-drift.
"""

from __future__ import annotations

import math

import pytest

from math_volatility import (
    VIX_TIER_ELEVATED_MAX,
    VIX_TIER_LOW_MAX,
    VIX_TIER_NORMAL_MAX,
    vix_bucket,
    vix_tier_token,
)


def test_vix_tier_cuts_are_15_20_30() -> None:
    assert VIX_TIER_LOW_MAX == 15.0
    assert VIX_TIER_NORMAL_MAX == 20.0
    assert VIX_TIER_ELEVATED_MAX == 30.0


@pytest.mark.parametrize(
    "vix,expected",
    [
        (5.0, "low"),
        (14.99, "low"),
        (15.0, "normal"),
        (19.99, "normal"),
        (20.0, "elevated"),
        (29.99, "elevated"),
        (30.0, "high"),
        (50.0, "high"),
    ],
)
def test_vix_tier_token_canonical_cuts(vix: float, expected: str) -> None:
    assert vix_tier_token(vix) == expected


@pytest.mark.parametrize("bad", [None, 0, -1, -100.0, float("nan")])
def test_vix_tier_token_rejects_degenerate(bad) -> None:
    assert vix_tier_token(bad) is None


def test_vix_tier_token_rejects_non_numeric_string() -> None:
    assert vix_tier_token("not-a-number") is None


def test_vix_bucket_label_format_preserved() -> None:
    """SignalInput.vix_bucket must still emit 'vix_*' prefixed labels for downstream consumers."""
    assert vix_bucket(10.0) == "vix_low"
    assert vix_bucket(17.0) == "vix_normal"
    assert vix_bucket(25.0) == "vix_elevated"
    assert vix_bucket(40.0) == "vix_high"


def test_vix_bucket_rejects_degenerate_inputs() -> None:
    """Pre-refactor, vix_bucket(0) returned 'vix_low' and vix_bucket(NaN) returned 'vix_high'
    (NaN comparisons propagated to the final else branch). Both are misleading on degenerate
    inputs; vix_tier_token authority now rejects them so the bucket label is also None."""
    assert vix_bucket(None) is None
    assert vix_bucket(0) is None
    assert vix_bucket(-5.0) is None
    assert vix_bucket(float("nan")) is None


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
