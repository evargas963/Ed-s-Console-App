"""MC-EM-ANCHOR: Monte Carlo IV must follow ``kl_em_anchor``."""

from __future__ import annotations

from math_volatility import (
    iv_percent_from_em_pts,
    resolve_kl_em_anchor,
    resolve_mc_iv_for_kl_em_anchor,
)


def test_straddle_anchor_wins_over_iv_em():
    em_straddle = {"em_pts": 5.0, "upper": 505.0, "lower": 495.0}
    em_iv = {"upper": 510.0, "lower": 490.0}
    assert resolve_kl_em_anchor(em_straddle, em_iv) == "straddle_open"


def test_mc_iv_from_straddle_em_pts_not_chain_atm():
    em_straddle = {"em_pts": 5.0, "upper": 505.0, "lower": 495.0}
    em_iv = {"upper": 510.0, "lower": 490.0}
    anchor = resolve_kl_em_anchor(em_straddle, em_iv)
    iv, src = resolve_mc_iv_for_kl_em_anchor(
        kl_em_anchor=anchor,
        atm_iv=30.0,
        spot=500.0,
        em_straddle=em_straddle,
        hours_remaining=4.0,
    )
    assert src == "mc_iv_kl_anchor_straddle_em_pts"
    assert iv is not None
    assert abs(iv - 30.0) > 0.5


def test_mc_iv_spot_anchor_uses_atm_iv():
    iv, src = resolve_mc_iv_for_kl_em_anchor(
        kl_em_anchor="iv_spot",
        atm_iv=26.1,
        spot=500.0,
        em_straddle={},
        hours_remaining=4.0,
    )
    assert src == "mc_iv_kl_anchor_iv_spot"
    assert iv == 26.1


def test_iv_percent_from_em_pts_roundtrip():
    spot, em_pts, hours = 500.0, 4.2, 3.5
    iv = iv_percent_from_em_pts(spot, em_pts, hours)
    assert iv is not None
    from math_volatility import compute_expected_move_iv

    em = compute_expected_move_iv(spot, iv, hours)
    assert em["em_pts"] is not None
    assert abs(em["em_pts"] - em_pts) < 0.05


def test_server_wires_mc_iv_level_into_build_market_state():
    source = open("server.py", encoding="utf-8").read()
    assert "mc_iv_level=_mc_iv_level" in source
    assert "mc_em_anchor=_kl_em_anchor" in source
    assert 'ms_dict["mc_em_anchor"]' in source
