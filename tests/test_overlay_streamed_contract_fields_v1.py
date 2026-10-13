"""overlay_streamed_contract_fields (math_exposure_core.py): a contract the daemon streams on
LEVELONE_OPTIONS takes its price, bid/ask, last, volume and Greeks from its stream record alone,
as sent, a field the stream has not sent absent, never the chain's; open interest stays the chain's
(Schwab's is the prior day's); a contract that does not stream is the chain's own.

Real data: CRWD's 2026-10-16 chain captured 2026-10-07 10:38:40 ET (tests/real_chains.py) and a
real LEVELONE_OPTIONS record as the daemon holds it (tests/real_option_record.py).
STAND-IN: that record's fields as a CRWD contract's.
"""
from __future__ import annotations

from math_exposure_core import overlay_streamed_contract_fields
from tests.real_chains import CRWD
from tests.real_option_record import RECORD, stream_priced

A, B = dict(CRWD.chain[0]), dict(CRWD.chain[1])


def test_a_streamed_contract_takes_every_field_from_its_record_and_none_from_the_chain():
    """The record carries the six Greeks and IV, not bid, ask, last, mark or volume: those are
    absent, though the chain has them; open interest is the chain's."""
    assert {"GAMMA", "DELTA", "THETA", "VEGA", "RHO", "VOLATILITY"} <= set(RECORD)
    assert "BID_PRICE" not in RECORD and A["bid"] is not None
    out = overlay_streamed_contract_fields([A, B], {A["symbol"]: RECORD})
    assert out == [stream_priced(A), B] and out[0]["bid"] is None and out[0]["gamma"] == RECORD["GAMMA"]
    assert out[0]["openInterest"] == A["openInterest"]


def test_a_held_contract_before_its_record_arrives_shows_none_of_the_chains_values():
    (out,) = overlay_streamed_contract_fields([A], {A["symbol"]: {}})
    assert out == stream_priced(A, {}) and out["gamma"] is None and out["openInterest"] == A["openInterest"]


def test_a_contract_that_does_not_stream_is_the_chains_own_object():
    out = overlay_streamed_contract_fields([A, B], {A["symbol"]: RECORD})
    assert out[1] is B
    out = overlay_streamed_contract_fields([A, B], {})
    assert out[0] is A and out[1] is B


def test_the_chains_contracts_are_never_mutated():
    before = dict(A)
    overlay_streamed_contract_fields([A], {A["symbol"]: RECORD})
    assert A == before
