"""LM-1: cross-ticker tradeable_score uses spot-normalized distance penalty."""

from __future__ import annotations

from server import _liquidity_zone_tradeable_fields


def _zone_score(spot: float, zone_low: float, zone_high: float) -> float:
    zp = {
        "zone_low": zone_low,
        "zone_high": zone_high,
        "source_tags": ["GAMMA_CALL_WALL"],
    }
    _liquidity_zone_tradeable_fields(zp, spot)
    return float(zp["tradeable_score"])


def test_tradeable_score_same_pct_distance_same_penalty_across_spot():
    """Equal fractional distance from zone → equal dist_pen (cross-ticker comparable)."""
    # spot 115, zone 100–110 → d=5, pct ≈ 5/115
    high_priced = _zone_score(115.0, 100.0, 110.0)
    # spot 11.5, zone 10–11 → d=0.5, pct ≈ 0.5/11.5 ≈ 5/115
    low_priced = _zone_score(11.5, 10.0, 11.0)
    assert high_priced == low_priced


def test_tradeable_score_absolute_distance_not_comparable_without_normalization():
    """Same dollar distance, different spot → different scores after LM-1."""
    near_zone = _zone_score(500.0, 490.0, 495.0)  # d=5, pct=1%
    far_zone = _zone_score(50.0, 40.0, 45.0)  # d=5, pct=10%
    assert near_zone != far_zone
