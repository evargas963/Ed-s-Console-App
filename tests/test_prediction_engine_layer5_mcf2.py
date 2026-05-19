"""Layer 5 FIND-MCF2: degenerate _norm_triplet_floats fail-closed."""

from __future__ import annotations

import math
from types import SimpleNamespace

from prediction_engine import _fusion_snap_triplet, _norm_triplet_floats


def test_norm_triplet_floats_none_on_all_zero():
    assert _norm_triplet_floats(0.0, 0.0, 0.0) is None


def test_norm_triplet_floats_none_on_nan():
    assert _norm_triplet_floats(float("nan"), 0.5, 0.5) is None


def test_norm_triplet_floats_valid():
    tri = _norm_triplet_floats(0.55, 0.25, 0.20)
    assert tri is not None
    assert math.isclose(sum(tri), 1.0)
    assert math.isclose(tri[0], 0.55)


def test_fusion_snap_triplet_none_when_norm_degenerate():
    snap = SimpleNamespace(fusion_available=True, prob_up=0.0, prob_down=0.0, prob_flat=0.0)
    assert _fusion_snap_triplet(snap) is None


def test_fusion_snap_triplet_valid_when_probs_ok():
    snap = SimpleNamespace(fusion_available=True, prob_up=0.5, prob_down=0.3, prob_flat=0.2)
    tri = _fusion_snap_triplet(snap)
    assert tri is not None
    assert math.isclose(tri[0], 0.5)
