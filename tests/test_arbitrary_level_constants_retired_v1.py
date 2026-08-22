"""RC-473: unvalidated wall/pin/approach constants are retired, not replaced."""
from __future__ import annotations

import math_levels as ML


def test_wall_min_mult_and_approach_pts_are_gone():
    assert not hasattr(ML, "WALL_MIN_MULT")
    assert not hasattr(ML, "APPROACH_PTS")


def test_pin_strength_does_not_emit_high_med_low_buckets():
    exposures = {
        100.0: {"net_gex_1pct": 300.0, "net_gamma": 3.0},
        101.0: {"net_gex_1pct": 10.0, "net_gamma": 0.1},
        102.0: {"net_gex_1pct": 10.0, "net_gamma": 0.1},
    }
    label = ML._pin_strength(exposures, 100.0, [100.0, 101.0, 102.0])
    assert label == ML.PIN_STRENGTH_WITHHELD
    assert label not in {"High", "Med", "Low", "Very Low"}
    ratio = ML._pin_peak_to_median_ratio(exposures, 100.0, [100.0, 101.0, 102.0])
    assert ratio is None or ratio > 1.0


def test_bias_from_net_does_not_mint_replacement_scores():
    assert ML._bias_from_net(1.0, 1.0, "High") == ML.BIAS_SIGNAL_WITHHELD
    assert ML._bias_from_net(-1.0, -1.0, "Very Low") == ML.BIAS_SIGNAL_WITHHELD


def test_pin_color_does_not_paint_retired_buckets_as_confidence():
    from market_state import pin_color

    assert pin_color("High") == pin_color("WITHHELD") == "#1a1a1a"
    assert pin_color("Med") == "#1a1a1a"


def test_derive_zone_does_not_launder_withheld_bias_into_pin_neutral():
    from market_state import derive_zone

    assert derive_zone("WITHHELD", 1.0) == "unclassified"
    assert derive_zone("unknown-label", None) == "unclassified"
