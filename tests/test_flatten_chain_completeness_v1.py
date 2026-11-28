"""OPTIONS_CHAIN_COMPLETENESS_FIX_V1 — real vendor fractional books survive flatten/persist.

Uses banked complete captures (strike_range=ALL) that match the live chain panel this session:
  CDE 2026-09-04  — $0.50 strikes (10.5 … 26.5)
  CRWD 2026-09-18 — $0.25/$0.75 plus $0.50 (38.75, 41.25, …)
No ticker-specific product branch. Rebuilds the Schwab nested map from the flat capture, then runs
the live flatten_chain_contracts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from feed.schwab_client import flatten_chain_contracts

_FIXTURES = Path(__file__).parent / "fixtures"
_CDE = json.loads(
    (_FIXTURES / "real_cde_complete_chain_half_dollar.json").read_text(encoding="utf-8")
)
_CDE_CONTRACTS = _CDE["chain"]


def _chain_json_for(contracts):
    """Return the Schwab callExpDateMap/putExpDateMap payload a flat contract list came from."""
    out = {"callExpDateMap": {}, "putExpDateMap": {}}
    for c in contracts:
        side = "callExpDateMap" if c.get("putCall") == "CALL" else "putExpDateMap"
        out[side].setdefault(f"{c['expirationDate'][:10]}:1", {}).setdefault(
            str(c["strikePrice"]), []
        ).append(c)
    return out


def _symbols(contracts):
    return {c["symbol"] for c in contracts}


def _frac(contracts):
    return [
        c for c in contracts if abs(float(c["strikePrice"]) - round(float(c["strikePrice"]))) > 1e-9
    ]


def test_flatten_preserves_real_cde_half_dollar_set():
    c_json = _chain_json_for(_CDE_CONTRACTS)
    after = flatten_chain_contracts(c_json)
    assert len(after) == len(_CDE_CONTRACTS)
    assert _symbols(after) == _symbols(_CDE_CONTRACTS)
    assert {float(c["strikePrice"]) for c in after} == {
        float(c["strikePrice"]) for c in _CDE_CONTRACTS
    }
    assert len(_frac(after)) == len(_frac(_CDE_CONTRACTS))
    strikes = {float(c["strikePrice"]) for c in after}
    assert 21.0 in strikes and 21.5 in strikes


_CRWD = json.loads(
    (_FIXTURES / "real_crwd_complete_chain_quarter.json").read_text(encoding="utf-8")
)
_CRWD_CONTRACTS = _CRWD["chain"]


def test_flatten_preserves_real_crwd_quarter_and_half_dollar_set():
    c_json = _chain_json_for(_CRWD_CONTRACTS)
    after = flatten_chain_contracts(c_json)
    assert len(after) == len(_CRWD_CONTRACTS)
    assert _symbols(after) == _symbols(_CRWD_CONTRACTS)
    strikes = {float(c["strikePrice"]) for c in after}
    assert {38.75, 41.25, 43.75, 46.25, 48.75}.issubset(strikes)
    assert 42.5 in strikes
    assert {c["putCall"] for c in after} == {"CALL", "PUT"}


def test_a_side_schwab_did_not_send_holds_no_contract():
    """CRWD's calls as Schwab sent them, its putExpDateMap left out: every call, no put."""
    calls = [c for c in _CRWD_CONTRACTS if c["putCall"] == "CALL"]
    c_json = _chain_json_for(calls)
    del c_json["putExpDateMap"]
    assert _symbols(flatten_chain_contracts(c_json)) == _symbols(calls)


@pytest.mark.parametrize(
    "broken",
    [
        lambda c_json: c_json.update(callExpDateMap=[]),
        lambda c_json: next(iter(c_json["callExpDateMap"].values())).update({"21.0": None}),
        lambda c_json: next(iter(c_json["callExpDateMap"].values())).update({"21.0": [None]}),
    ],
    ids=["expiries not a map", "a strike with no list", "a contract that is no object"],
)
def test_an_answer_not_in_schwabs_shape_raises_and_leaves_no_contract_out(broken):
    """INDUCED: CDE's answer rebuilt as Schwab sends it, one part of it out of Schwab's shape.

    It raises (the sweep fails that ticker with the error, ChainSweep.fetch_chain), never a chain
    with that part's contracts left out.
    """
    c_json = _chain_json_for(_CDE_CONTRACTS)
    broken(c_json)
    with pytest.raises((AttributeError, TypeError)):
        flatten_chain_contracts(c_json)
