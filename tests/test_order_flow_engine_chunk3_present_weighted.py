"""order_flow_engine chunk-3: the composite score/direction/readiness are RETIRED (RC-473/RC-474).

_compute_order_flow_score, _direction and _readiness were deleted (no fitted weights, no OOS
validation). The generic `_weighted_mean_present` / `_normalize` helpers survive (used by the
institutional-flow proxy) and are still tested; this file also locks that the composite producers
cannot be reconstructed.
"""
from __future__ import annotations

import order_flow_engine as ofe
from order_flow_engine import _normalize, _weighted_mean_present


def test_weighted_mean_present_helper_respects_min_present():
    terms = [(0.05, 0.5, -0.5, 0.5)]
    assert _weighted_mean_present(terms, min_present=2) is None
    assert _weighted_mean_present(terms, min_present=1) is not None


def test_normalize_clips_to_unit_range():
    assert _normalize(5.0) == 1.0
    assert _normalize(-5.0) == -1.0
    assert _normalize(0.3) == 0.3


def test_weighted_mean_present_excludes_absent_legs_instead_of_zero_filling():
    # RC-318: an absent (None) leg must be DROPPED from both numerator and denominator —
    # never coerced to a neutral 0.0 reading. Zero-filling the None leg here would yield
    # 0.25; exclusion yields the present leg's value.
    terms = [(1.0, None, -1.0, 1.0), (1.0, 0.5, -1.0, 1.0)]
    assert _weighted_mean_present(terms, min_present=1) == 0.5


def test_composite_score_direction_readiness_producers_are_deleted():
    # RC-474: the retired producers must not exist — no executable path can reconstruct the composite.
    for name in ("_compute_order_flow_score", "_direction", "_readiness"):
        assert not hasattr(ofe, name), f"{name} must stay deleted (retired composite producer)"
