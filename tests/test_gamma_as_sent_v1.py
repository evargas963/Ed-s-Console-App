"""One gamma source: the regime's gamma at spot is Schwab's gamma as sent, summed over the same
book the walls use (2026-09-27: it was a recomputed gamma, and on Friday's SPY chain the two
disagreed in sign). The chain's rate and dividend travel with each contract as sent; a streamed
contract takes its IV beside its gamma from the stream.
STAND-IN (named): the streamed GAMMA and VOLATILITY of SPY_0DTE's first contract (no captured
stream of a contract in a captured chain carries its Greeks)."""
from __future__ import annotations

import pytest

from math_exposure_core import bucket_metric, compute_exposures_by_strike
from schwab_client import flatten_chain_contracts
from terrain_engine import compute_terrain
from tests.real_chains import SPY_0DTE


def test_gamma_at_spot_is_schwabs_gamma_summed_over_the_book():
    """SPY's same-day chain of 2026-10-07 12:32 ET, valued at its capture (tests/real_chains.py)."""
    chain, spot, now = SPY_0DTE.chain, SPY_0DTE.spot, SPY_0DTE.now
    snap = compute_terrain("SPY", chain, spot, now=now)
    per, _ = compute_exposures_by_strike(chain, spot=spot, now=now)
    schwab = sum(v for b in per.values() if (v := bucket_metric(b, "net_gex_1pct")) is not None)
    assert snap.net_gex_at_spot == pytest.approx(schwab, rel=1e-9)
    assert snap.flip_diag["gamma_at_spot"] == snap.net_gex_at_spot
    assert snap.flip_diag["curve_gamma_at_spot"] is not None, "the flip's own curve is still reported"


def test_each_contract_carries_the_chains_rate_and_dividend_as_sent():
    payload = {"interestRate": 4.07, "dividendYield": 0.979,
               "callExpDateMap": {"2030-01-18:30": {"100.0": [{"symbol": "X", "putCall": "CALL"}]}},
               "putExpDateMap": {}}
    (ct,) = flatten_chain_contracts(payload)
    assert ct["interestRate"] == 4.07 and ct["dividendYield"] == 0.979


def test_a_streamed_contract_takes_iv_beside_gamma_from_its_stream():
    """The contract's record (option_ledger) opened from the chain, then one LEVELONE_OPTIONS
    message: its gamma and IV are the stream's, each with that message's Schwab time; its terms
    and open interest stay the chain's."""
    import option_ledger
    from stream_spine import MessageBus, current_key
    ct = SPY_0DTE.chain[0]
    bus = MessageBus()
    bus.publish(*option_ledger.posting(ct["symbol"], option_ledger.opening(ct, "SPY"), ct["quoteTimeInLong"]))
    streamed = ct["quoteTimeInLong"] + 1000
    topic, msg = option_ledger.posting(ct["symbol"], option_ledger.from_stream(
        {"key": ct["symbol"], "GAMMA": 0.01, "VOLATILITY": 18.5}, streamed), streamed)
    bus.publish(topic, msg)
    record = bus.current[current_key(topic, msg)][1]
    assert record["fields"]["gamma"] == 0.01 and record["fields"]["volatility"] == 18.5
    assert record["field_ts"]["gamma"][0] == record["field_ts"]["volatility"][0] == streamed
    assert record["fields"]["openInterest"] == ct["openInterest"]
    assert record["fields"]["strikePrice"] == ct["strikePrice"]


def test_a_flip_whose_curve_disagrees_with_schwab_says_so():
    from terrain_read import FLIP_CURVE_DISAGREES, GAMMA_FLIP_TRUSTED, build_terrain_read
    kw = dict(spot=100.0, flip=99.0, flip_confidence=GAMMA_FLIP_TRUSTED, gamma_at_spot=-5.0)
    assert FLIP_CURVE_DISAGREES in build_terrain_read(**kw, flip_curve_agrees=False).lines
    assert FLIP_CURVE_DISAGREES not in build_terrain_read(**kw, flip_curve_agrees=True).lines
