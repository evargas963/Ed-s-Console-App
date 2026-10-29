"""overlay_streamed_contract_fields (math_exposure_core.py) merges a newer streamed open interest
or volume onto a chain contract. Gamma, delta, and volatility stay the chain's. Receive time
decides which open interest or volume is newer. Pure function: no network, no cache, no clock."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from math_exposure_core import overlay_streamed_contract_fields

#: the chain's receive time in these tests; a streamed field after it is newer
CHAIN_RX = 1_000.0


def _contract(symbol, **fields):
    # institutional-synthetic-ok: overlay_streamed_contract_fields is pure dict-merge
    # mechanics (which fields land where, mutation, which value is newer) with no exposure math
    # of its own -- compute_exposures_by_strike's own correctness is proven on real chains
    # elsewhere (test_gamma_surface_projection_v1.py). A synthetic contract with deterministic
    # field values makes the merge assertions exact and readable.
    base = {"symbol": symbol, "strikePrice": 580.0, "putCall": "CALL",
            "gamma": 0.01, "delta": 0.40, "openInterest": 100}
    base.update(fields)
    return base


def _newer(**fields):
    """A streamed entry whose every field was received after the chain."""
    out = dict(fields)
    for k in fields:
        out[f"{k}_ts_recv"] = CHAIN_RX + 1.0
    return out


def test_empty_contracts_returns_empty():
    out, n = overlay_streamed_contract_fields([], {"X": _newer(gamma=1.0)}, CHAIN_RX)
    assert out == [] and n == 0


def test_no_streamed_data_passes_contracts_through_unchanged_object_identity():
    contracts = [_contract("A"), _contract("B")]
    out, n = overlay_streamed_contract_fields(contracts, {}, CHAIN_RX)
    assert out == contracts
    assert out[0] is contracts[0], "no overlay applies -- must be the SAME object, not a copy"
    assert n == 0


def test_a_contract_not_named_in_streamed_by_symbol_is_untouched():
    contracts = [_contract("A"), _contract("B")]
    out, n = overlay_streamed_contract_fields(contracts, {"C": _newer(gamma=9.9)}, CHAIN_RX)
    assert out[0] is contracts[0]
    assert out[1] is contracts[1]
    assert n == 0


def test_open_interest_is_overlaid_and_a_greek_is_not():
    contracts = [_contract("A", gamma=0.01, delta=0.40, openInterest=100)]
    streamed = {"A": _newer(gamma=0.05, delta=0.55, open_interest=250)}
    out, n = overlay_streamed_contract_fields(contracts, streamed, CHAIN_RX)
    assert n == 1
    assert out[0]["gamma"] == 0.01
    assert out[0]["delta"] == 0.40
    assert out[0]["openInterest"] == 250
    assert out[0]["strikePrice"] == 580.0, "fields not in the overlay are preserved"


def test_the_input_contract_dict_is_never_mutated():
    original = _contract("A", openInterest=100)
    contracts = [original]
    out, n = overlay_streamed_contract_fields(contracts, {"A": _newer(open_interest=250)}, CHAIN_RX)
    assert n == 1
    assert original["openInterest"] == 100, "the caller's original dict must be untouched"
    assert out[0]["openInterest"] == 250
    assert out[0] is not original


def test_a_streamed_gamma_leaves_the_chain_and_a_volume_replaces_it():
    """A gamma tick is not a second gamma. A volume tick replaces the chain's volume."""
    contracts = [_contract("A", gamma=0.01, delta=0.40, openInterest=100, totalVolume=7)]
    out, n = overlay_streamed_contract_fields(contracts, {"A": _newer(gamma=0.07)}, CHAIN_RX)
    assert n == 0
    assert out[0] is contracts[0]
    assert out[0]["gamma"] == 0.01
    out, n = overlay_streamed_contract_fields(contracts, {"A": _newer(total_volume=900)}, CHAIN_RX)
    assert n == 1
    assert out[0]["totalVolume"] == 900
    assert out[0]["gamma"] == 0.01
    assert out[0]["openInterest"] == 100


def test_only_the_matching_symbol_is_copied_others_stay_the_original_object():
    contracts = [_contract("A", openInterest=100), _contract("B", openInterest=200)]
    out, n = overlay_streamed_contract_fields(contracts, {"A": _newer(open_interest=250)}, CHAIN_RX)
    assert n == 1
    assert out[0] is not contracts[0]
    assert out[1] is contracts[1], "an unmatched contract must never be copied either"


def test_a_streamed_value_from_before_the_chain_never_overrides_it():
    """Yesterday's streamed open interest does not replace a chain fetched today. A gamma
    received after the chain does not replace it either."""
    day = 86_400.0
    contracts = [_contract("A", gamma=0.01, openInterest=100, totalVolume=7)]
    streamed = {"A": {"gamma": 0.03, "gamma_ts_recv": CHAIN_RX + 5.0,
                      "open_interest": 90, "open_interest_ts_recv": CHAIN_RX - day,
                      "total_volume": 4_000, "total_volume_ts_recv": CHAIN_RX - day}}
    out, n = overlay_streamed_contract_fields(contracts, streamed, CHAIN_RX)
    assert n == 0
    assert out[0] is contracts[0]
    assert (out[0]["gamma"], out[0]["openInterest"], out[0]["totalVolume"]) == (0.01, 100, 7)
    old = {"A": {"open_interest": 90, "open_interest_ts_recv": CHAIN_RX - day}}
    out, n = overlay_streamed_contract_fields(contracts, old, CHAIN_RX)
    assert n == 0 and out[0] is contracts[0]


def test_a_contract_with_no_symbol_field_is_untouched_never_raises():
    # institutional-synthetic-ok: exercising the missing-'symbol'-key edge case needs a
    # contract that specifically lacks it -- a real captured chain's own contracts always
    # carry one, so this fail-closed shape cannot be sourced from tests/fixtures/.
    contracts = [{"strikePrice": 580.0, "putCall": "CALL"}]
    out, n = overlay_streamed_contract_fields(contracts, {"A": _newer(gamma=0.5)}, CHAIN_RX)
    assert n == 0
    assert out[0] is contracts[0]
