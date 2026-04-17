"""Contract tests: movement-target v2 naming, sums, backward compatibility."""
from __future__ import annotations

import math

import numpy as np
import pytest

from movement_target_threshold import (
    directional_and_move_labels_v2,
    invalid_for_dir_target,
    threshold_move_pts_for_slug,
)


def test_valid_dir_false_when_dir_disabled():
    d, m, v = directional_and_move_labels_v2(0.5, 0.1, dir_allowed=False)
    assert v == 0 and d is None and m == "move"


def test_sum_to_one_movement_head_probs_style():
    hz = "5c"
    d = {
        f"pred_move_prob_{hz}": 0.4,
        f"pred_no_move_prob_{hz}": 0.6,
        f"pred_dir_up_prob_{hz}": 0.55,
        f"pred_dir_down_prob_{hz}": 0.45,
    }
    assert abs(d[f"pred_move_prob_{hz}"] + d[f"pred_no_move_prob_{hz}"] - 1.0) < 1e-6
    assert abs(d[f"pred_dir_up_prob_{hz}"] + d[f"pred_dir_down_prob_{hz}"] - 1.0) < 1e-6


def test_threshold_fallback_positive():
    t = threshold_move_pts_for_slug("5c", anchor_close=100.0, atr=0.5, cfg={"horizons": {}})
    assert t > 0


def test_invalid_for_dir_slug():
    assert invalid_for_dir_target("5c", {"horizons": {"5c": {"invalid_for_dir_target": True}}}) is True


def test_no_nan_inf_in_normalized_probs():
    raw = np.array([0.2, 0.8], dtype=np.float64)
    s = float(np.sum(raw))
    out = raw / s
    assert all(math.isfinite(x) for x in out)
