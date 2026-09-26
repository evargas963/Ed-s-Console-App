"""MC-EM-ANCHOR: Monte Carlo IV must follow ``kl_em_anchor``."""

from __future__ import annotations











def test_server_wires_mc_iv_level_into_build_market_state():
    source = open("server.py", encoding="utf-8").read()
    assert "mc_iv_level=_mc_iv_level" in source
    assert "mc_em_anchor=_kl_em_anchor" in source
    assert 'ms_dict["mc_em_anchor"]' in source
