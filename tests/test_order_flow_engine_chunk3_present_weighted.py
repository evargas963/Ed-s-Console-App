"""order_flow_engine chunk-3: the composite score/direction/readiness are RETIRED (RC-473/RC-474).

_compute_order_flow_score, _direction and _readiness were deleted (no fitted weights, no OOS
validation). The present-leg re-weighting helpers `_weighted_mean_present` / `_normalize` were deleted
2026-09-24; this file locks that neither they nor the composite producers can be reconstructed.
"""
from __future__ import annotations

import app.options.order_flow.engine as ofe


def test_present_leg_reweighting_helpers_are_deleted():
    # 2026-09-24: _weighted_mean_present renormalised present weights (re-weighting);
    # deleted with _normalize (no production caller).
    assert not hasattr(ofe, "_weighted_mean_present")
    assert not hasattr(ofe, "_normalize")


def test_composite_score_direction_readiness_producers_are_deleted():
    # RC-474: the retired producers must not exist — no executable path can reconstruct the composite.
    for name in ("_compute_order_flow_score", "_direction", "_readiness"):
        assert not hasattr(ofe, name), f"{name} must stay deleted (retired composite producer)"
