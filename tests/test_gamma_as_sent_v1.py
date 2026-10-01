"""One gamma source: the regime's gamma at spot is Schwab's gamma as sent, summed over the same
book the walls use (2026-09-27: it was a recomputed gamma, and on Friday's SPY chain the two
disagreed in sign). The chain's rate and dividend travel with each contract as sent; the option
stream keeps IV beside the gamma it overlays."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from math_exposure_core import compute_exposures_by_strike
from schwab_client import flatten_chain_contracts
from terrain_engine import compute_terrain

_FX = json.loads((Path(__file__).parent / "fixtures" / "real_spy_0dte_chain.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _at_capture(pin_clock):
    """real_spy_0dte_chain.json was captured 2026-09-22 12:46 ET."""
    return pin_clock(2026, 9, 22, 12, 46)


def test_gamma_at_spot_is_schwabs_gamma_summed_over_the_book():
    chain, spot = _FX["chain"], float(_FX["spot"])
    snap = compute_terrain("SPY", chain, spot)
    per, _ = compute_exposures_by_strike(chain, spot=spot)
    schwab = sum(b["net_gex_1pct"] for b in per.values() if b.get("has_valid_gamma"))
    assert snap.net_gex_at_spot == pytest.approx(schwab, rel=1e-9)
    assert snap.flip_diag["gamma_at_spot"] == snap.net_gex_at_spot
    assert snap.flip_diag["curve_gamma_at_spot"] is not None, "the flip's own curve is still reported"


def test_each_contract_carries_the_chains_rate_and_dividend_as_sent():
    payload = {"interestRate": 4.07, "dividendYield": 0.979,
               "callExpDateMap": {"2030-01-18:30": {"100.0": [{"symbol": "X", "putCall": "CALL"}]}},
               "putExpDateMap": {}}
    (ct,) = flatten_chain_contracts(payload)
    assert ct["interestRate"] == 4.07 and ct["dividendYield"] == 0.979


def test_the_option_stream_keeps_iv_beside_gamma():
    from app.options.order_flow.state import OrderFlowState
    st = OrderFlowState()
    sym = "SPY   301231C00700000"
    st.push_level_one(sym, {"key": sym, "GAMMA": 0.01, "VOLATILITY": 18.5}, ts_recv=1000.0)
    g = st.get_stream_greeks(sym)
    assert g["gamma"] == 0.01 and g["volatility"] == 18.5 and g["volatility_ts_recv"] == 1000.0


def test_a_flip_whose_curve_disagrees_with_schwab_says_so():
    from terrain_read import FLIP_CURVE_DISAGREES, GAMMA_FLIP_TRUSTED, build_terrain_read
    kw = dict(spot=100.0, flip=99.0, flip_confidence=GAMMA_FLIP_TRUSTED, gamma_at_spot=-5.0)
    assert build_terrain_read(**kw, flip_curve_agrees=False).flip_caveat == FLIP_CURVE_DISAGREES
    assert build_terrain_read(**kw, flip_curve_agrees=True).flip_caveat == ""
