"""One gamma source: the regime's gamma at spot is Schwab's gamma as sent.

It is summed over the same book the walls use (2026-09-27: it was a recomputed gamma, and on
Friday's SPY chain the two disagreed in sign). The chain's rate and dividend travel with each
contract as sent; the option stream keeps IV beside the gamma it overlays.
"""

from __future__ import annotations

import pytest

from app.options.order_flow.state import OrderFlowState
from math_exposure_core import bucket_metric, compute_exposures_by_strike
from option_contract import read_chain
from schwab_client import flatten_chain_contracts
from terrain_engine import compute_terrain
from terrain_read import FLIP_CURVE_DISAGREES
from tests.real_chains import CRWD, SPY_0DTE, SPY_FULL


def test_gamma_at_spot_is_schwabs_gamma_summed_over_the_book():
    """SPY's same-day chain of 2026-10-07 12:32 ET, valued at its capture (tests/real_chains.py)."""
    chain, spot, now = read_chain(SPY_0DTE.chain), SPY_0DTE.spot, SPY_0DTE.now
    snap = compute_terrain("SPY", chain, spot, now=now)
    per, _ = compute_exposures_by_strike(chain, spot=spot, now=now)
    schwab = sum(v for b in per.values() if (v := bucket_metric(b, "net_gex_1pct")) is not None)
    assert snap.net_gex_at_spot == pytest.approx(schwab, rel=1e-9)


def test_each_contract_carries_the_chains_rate_and_dividend_as_sent():
    payload = {
        "interestRate": 4.07,
        "dividendYield": 0.979,
        "callExpDateMap": {"2030-01-18:30": {"100.0": [{"symbol": "X", "putCall": "CALL"}]}},
        "putExpDateMap": {},
    }
    (ct,) = flatten_chain_contracts(payload)
    assert ct["interestRate"] == 4.07 and ct["dividendYield"] == 0.979


def test_the_option_stream_keeps_iv_beside_gamma():
    st = OrderFlowState()
    sym = "SPY   301231C00700000"
    st.push_level_one(sym, {"key": sym, "GAMMA": 0.01, "VOLATILITY": 18.5}, ts_recv=1000.0)
    g = st.get_stream_greeks(sym)
    assert g["gamma"] == 0.01 and g["volatility"] == 18.5 and g["volatility_ts_recv"] == 1000.0


def test_a_flip_whose_curve_disagrees_with_schwab_says_so():
    """The flip's note is served with the levels, where a page draws it beside the flip.

    Failure this catches (2026-11-13): the note was added only to sentences no page read, so
    it never reached a screen. SPY's full chain (tests/real_chains.py): the curve's sign at
    its price differs from Schwab's gamma, so the note is served; CRWD's agree, so none is.
    """
    spy = compute_terrain("SPY", read_chain(SPY_FULL.chain), SPY_FULL.spot, now=SPY_FULL.now)
    assert spy.flip_note == spy.to_dict()["flip_note"] == FLIP_CURVE_DISAGREES
    crwd = compute_terrain("CRWD", read_chain(CRWD.chain), CRWD.spot, now=CRWD.now)
    assert crwd.flip_note is None
