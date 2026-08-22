"""order_flow_engine chunk-3: composite score/direction/readiness RETIRED (RC-454)."""
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
    assert _normalize(None) == 0.0
    assert _normalize(0.3) == 0.3


def test_composite_score_direction_readiness_producers_are_deleted():
    for name in ("_compute_order_flow_score", "_direction", "_readiness"):
        assert not hasattr(ofe, name), f"{name} must stay deleted (retired composite producer)"
