"""overlay_streamed_contract_fields (math_exposure_core.py): a contract Schwab streams takes its
volume from the stream alone, never the chain's (AGENTS.md rule 3: the pushed field is its one
producer); one the stream has not sent is None. Open interest is the chain's for every contract
(the stream does not send it for every contract it streams), and gamma, delta, and volatility are
the sweep's. A contract the stream does not hold keeps the chain's. Pure function: no network, no
cache, no clock."""

from __future__ import annotations

from math_exposure_core import overlay_streamed_contract_fields
from option_contract import read_contract


def _contract(symbol, **fields):
    # institutional-synthetic-ok: overlay_streamed_contract_fields is pure dict-merge
    # mechanics (which fields land where, mutation, which source a field comes from) with no
    # exposure math of its own -- compute_exposures_by_strike's own correctness is proven on real
    # chains elsewhere (test_gamma_surface_projection_v1.py). A synthetic contract with
    # deterministic field values makes the merge assertions exact and readable.
    base = {
        "symbol": symbol,
        "strikePrice": 580.0,
        "putCall": "CALL",
        "gamma": 0.01,
        "delta": 0.40,
        "openInterest": 100,
        "totalVolume": 7,
    }
    base.update(fields)
    return read_contract(base)


def test_empty_contracts_returns_empty():
    out, n = overlay_streamed_contract_fields([], {"X": {"total_volume": 1}}, {"X"})
    assert out == [] and n == 0


def test_no_streamed_contract_passes_contracts_through_unchanged_object_identity():
    contracts = [_contract("A"), _contract("B")]
    out, n = overlay_streamed_contract_fields(contracts, {}, set())
    assert out == contracts
    assert out[0] is contracts[0], "no overlay applies -- must be the SAME object, not a copy"
    assert n == 0


def test_a_contract_the_stream_does_not_hold_is_untouched():
    contracts = [_contract("A"), _contract("B")]
    out, n = overlay_streamed_contract_fields(contracts, {"C": {"total_volume": 9}}, {"C"})
    assert out[0] is contracts[0]
    assert out[1] is contracts[1]
    assert n == 0


def test_volume_is_the_streams_and_open_interest_and_greeks_are_not():
    contracts = [_contract("A", gamma=0.01, delta=0.40, openInterest=100, totalVolume=7)]
    streamed = {"A": {"gamma": 0.05, "delta": 0.55, "open_interest": 250, "total_volume": 900}}
    out, n = overlay_streamed_contract_fields(contracts, streamed, {"A"})
    assert n == 1
    assert out[0].volume == 900
    assert out[0].open_interest == 100, "open interest is the chain's"
    assert out[0].gamma == 0.01
    assert out[0].delta == 0.40
    assert out[0].strike == 580.0, "fields not in the overlay are preserved"


def test_the_input_contract_is_never_mutated():
    original = _contract("A", totalVolume=7)
    contracts = [original]
    out, n = overlay_streamed_contract_fields(contracts, {"A": {"total_volume": 900}}, {"A"})
    assert n == 1
    assert original.volume == 7, "the caller's original record must be untouched"
    assert out[0].volume == 900
    assert out[0] is not original


def test_only_the_streamed_symbol_is_copied_others_stay_the_original_object():
    contracts = [_contract("A"), _contract("B")]
    out, n = overlay_streamed_contract_fields(contracts, {"A": {"total_volume": 250}}, {"A"})
    assert n == 1
    assert out[0] is not contracts[0]
    assert out[1] is contracts[1], "an unmatched contract must never be copied either"


def test_a_streamed_contract_never_shows_the_chains_volume():
    """The chain's volume is never the screen's for a contract Schwab streams: one the stream
    has not sent is unknown (None), and one it sent before the chain is still the stream's (the
    cell stamp says whether it is live)."""
    contracts = [_contract("A", openInterest=100, totalVolume=7)]
    out, n = overlay_streamed_contract_fields(contracts, {}, {"A"})
    assert n == 1
    assert (out[0].open_interest, out[0].volume) == (100, None)
    older = {"A": {"total_volume": 4, "total_volume_ts_recv": 1.0}}
    out, n = overlay_streamed_contract_fields(contracts, older, {"A"})
    assert (out[0].open_interest, out[0].volume) == (100, 4)


def test_a_zero_volume_the_stream_sent_is_zero():
    contracts = [_contract("A", totalVolume=7)]
    out, _n = overlay_streamed_contract_fields(contracts, {"A": {"total_volume": 0}}, {"A"})
    assert out[0].volume == 0


def test_a_contract_with_no_symbol_field_is_untouched_never_raises():
    # institutional-synthetic-ok: exercising the missing-'symbol'-key edge case needs a
    # contract that specifically lacks it -- a real captured chain's own contracts always
    # carry one, so this fail-closed shape cannot be sourced from tests/fixtures/.
    contracts = [read_contract({"strikePrice": 580.0, "putCall": "CALL"})]
    out, n = overlay_streamed_contract_fields(contracts, {"A": {"total_volume": 5}}, {"A"})
    assert n == 0
    assert out[0] is contracts[0]
