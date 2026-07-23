"""Registered test 2 study — substitution and sign helpers (pure-function contracts)."""
from __future__ import annotations

from tools.study_volume_vs_oi_terrain_v1 import _sign, volume_substituted


def test_volume_substituted_replaces_oi_and_fails_closed():
    src = [
        {"totalVolume": 250, "openInterest": 9000},   # kept, weight becomes 250
        {"totalVolume": 0, "openInterest": 9000},     # zero volume -> weight 0 (dropped later)
        {"totalVolume": None, "openInterest": 9000},  # absent -> 0, never fabricated
        {"openInterest": 9000},                        # missing key -> 0
        {"totalVolume": "garbage", "openInterest": 9000},  # unparseable -> 0
    ]
    out, kept = volume_substituted(src)
    assert kept == 1
    assert [c["openInterest"] for c in out] == [250, 0, 0, 0, 0]
    # deep copy: the stored chain is never mutated by the study
    assert src[0]["openInterest"] == 9000


def test_sign_maps_zero_and_none_to_no_regime():
    assert _sign(3.2e9) == "LONG"
    assert _sign(-1.0) == "SHORT"
    assert _sign(0.0) is None
    assert _sign(None) is None
