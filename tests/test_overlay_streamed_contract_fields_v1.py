"""overlay_streamed_contract_fields (math_exposure_core.py) merges freshly-streamed
GAMMA/DELTA/OPEN_INTEREST onto a base REST chain contract list -- the bridge that lets
project_gamma_surface's ONE canonical projection (RC-UI-1) use fresher-than-REST inputs for
an actively-streamed contract, without becoming a second exposure computation. Pure function:
no network, no cache, no clock dependency unless staleness is asked for."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from math_exposure_core import overlay_streamed_contract_fields


def _contract(symbol, **fields):
    base = {"symbol": symbol, "strikePrice": 580.0, "putCall": "CALL",
            "gamma": 0.01, "delta": 0.40, "openInterest": 100}
    base.update(fields)
    return base


def test_empty_contracts_returns_empty():
    out, n = overlay_streamed_contract_fields([], {"X": {"gamma": 1.0}})
    assert out == [] and n == 0


def test_no_streamed_data_passes_contracts_through_unchanged_object_identity():
    contracts = [_contract("A"), _contract("B")]
    out, n = overlay_streamed_contract_fields(contracts, {})
    assert out == contracts
    assert out[0] is contracts[0], "no overlay applies -- must be the SAME object, not a copy"
    assert n == 0


def test_a_contract_not_named_in_streamed_by_symbol_is_untouched():
    contracts = [_contract("A"), _contract("B")]
    out, n = overlay_streamed_contract_fields(contracts, {"C": {"gamma": 9.9}})
    assert out[0] is contracts[0]
    assert out[1] is contracts[1]
    assert n == 0


def test_gamma_delta_open_interest_are_overlaid_for_the_matching_contract():
    contracts = [_contract("A", gamma=0.01, delta=0.40, openInterest=100)]
    streamed = {"A": {"gamma": 0.05, "delta": 0.55, "open_interest": 250}}
    out, n = overlay_streamed_contract_fields(contracts, streamed)
    assert n == 1
    assert out[0]["gamma"] == 0.05
    assert out[0]["delta"] == 0.55
    assert out[0]["openInterest"] == 250
    assert out[0]["strikePrice"] == 580.0, "fields not in the overlay are preserved"


def test_the_input_contract_dict_is_never_mutated():
    original = _contract("A", gamma=0.01)
    contracts = [original]
    out, n = overlay_streamed_contract_fields(contracts, {"A": {"gamma": 0.99}})
    assert original["gamma"] == 0.01, "the caller's original dict must be untouched"
    assert out[0]["gamma"] == 0.99
    assert out[0] is not original


def test_a_partial_streamed_entry_overlays_only_the_fields_it_carries():
    """A streamed entry missing 'delta' (e.g. only gamma has ticked recently) must leave
    the chain's own delta value in place, not null it out."""
    contracts = [_contract("A", gamma=0.01, delta=0.40, openInterest=100)]
    out, n = overlay_streamed_contract_fields(contracts, {"A": {"gamma": 0.07}})
    assert n == 1
    assert out[0]["gamma"] == 0.07
    assert out[0]["delta"] == 0.40, "delta was not in the streamed entry -- chain value survives"
    assert out[0]["openInterest"] == 100


def test_only_the_matching_symbol_is_copied_others_stay_the_original_object():
    contracts = [_contract("A", gamma=0.01), _contract("B", gamma=0.02)]
    out, n = overlay_streamed_contract_fields(contracts, {"A": {"gamma": 0.5}})
    assert n == 1
    assert out[0] is not contracts[0]
    assert out[1] is contracts[1], "an unmatched contract must never be copied either"


def test_a_stale_streamed_value_beyond_max_staleness_is_not_applied():
    contracts = [_contract("A", gamma=0.01)]
    streamed = {"A": {"gamma": 0.99, "gamma_ts_recv": 100.0}}
    out, n = overlay_streamed_contract_fields(
        contracts, streamed, max_staleness_sec=5.0, now=200.0)
    assert n == 0, "a value 100s old must not override a same-cycle REST read under a 5s bound"
    assert out[0]["gamma"] == 0.01
    assert out[0] is contracts[0]


def test_a_fresh_streamed_value_within_max_staleness_is_applied():
    contracts = [_contract("A", gamma=0.01)]
    streamed = {"A": {"gamma": 0.99, "gamma_ts_recv": 198.0}}
    out, n = overlay_streamed_contract_fields(
        contracts, streamed, max_staleness_sec=5.0, now=200.0)
    assert n == 1
    assert out[0]["gamma"] == 0.99


def test_a_field_with_no_ts_recv_is_never_applied_under_a_staleness_bound():
    """A missing freshness stamp is treated as unknown-age, never as 'fresh enough'."""
    contracts = [_contract("A", gamma=0.01)]
    streamed = {"A": {"gamma": 0.99}}  # no gamma_ts_recv at all
    out, n = overlay_streamed_contract_fields(
        contracts, streamed, max_staleness_sec=5.0, now=200.0)
    assert n == 0
    assert out[0]["gamma"] == 0.01


def test_no_staleness_bound_applies_regardless_of_age():
    contracts = [_contract("A", gamma=0.01)]
    streamed = {"A": {"gamma": 0.99, "gamma_ts_recv": 0.0}}
    out, n = overlay_streamed_contract_fields(contracts, streamed, now=1_000_000.0)
    assert n == 1
    assert out[0]["gamma"] == 0.99


def test_a_contract_with_no_symbol_field_is_untouched_never_raises():
    contracts = [{"strikePrice": 580.0, "putCall": "CALL"}]
    out, n = overlay_streamed_contract_fields(contracts, {"A": {"gamma": 0.5}})
    assert n == 0
    assert out[0] is contracts[0]
