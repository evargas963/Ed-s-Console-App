"""FIND-MCSI-3: _spot_for_mc_fusion_adjustment uses float_positive_or_none on both read paths."""

from __future__ import annotations

import math

from signals import _spot_for_mc_fusion_adjustment


def test_spot_for_mc_fusion_adjustment_rejects_inf_from_mc_spot_ctx():
    snap = {"features": {"price.spot": 100.0}}
    assert _spot_for_mc_fusion_adjustment({"spot": math.inf}, snap) is None


def test_spot_for_mc_fusion_adjustment_rejects_inf_from_mvp_features():
    snap = {"features": {"price.spot": math.inf}}
    assert _spot_for_mc_fusion_adjustment(None, snap) is None


def test_spot_for_mc_fusion_adjustment_prefers_finite_mc_ctx_spot():
    snap = {"features": {"price.spot": 200.0}}
    assert _spot_for_mc_fusion_adjustment({"spot": 100.0}, snap) == 100.0
