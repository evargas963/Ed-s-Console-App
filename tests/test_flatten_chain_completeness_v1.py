"""OPTIONS_CHAIN_COMPLETENESS_FIX_V1 — real vendor fractional books survive flatten/persist.

Uses banked complete captures (strike_range=ALL) that match live /api/chain this session:
  CDE 2026-09-04  — $0.50 strikes (10.5 … 26.5)
  CRWD 2026-09-18 — $0.25/$0.75 plus $0.50 (38.75, 41.25, …)
No ticker-specific product branch. Reconstructs the Schwab nested map the same way
/api/chain tests already do, then runs the live flatten_chain_contracts.
"""
from __future__ import annotations

import json
from pathlib import Path

from calibration.complete_chain_capture import (
    latest_complete_chain_capture,
    persist_complete_chain_capture,
)
from server import flatten_chain_contracts
from tests.test_chain_api_v1 import _chain_json_for

_FIXTURES = Path(__file__).parent / "fixtures"
_CDE = json.loads((_FIXTURES / "real_cde_complete_chain_half_dollar.json").read_text(encoding="utf-8"))
_CDE_CONTRACTS = _CDE["chain"]
_CDE_EXPIRY = _CDE["expiry"]


def _symbols(contracts):
    return {c["symbol"] for c in contracts}


def _frac(contracts):
    return [c for c in contracts if abs(float(c["strikePrice"]) - round(float(c["strikePrice"]))) > 1e-9]


def test_flatten_preserves_real_cde_half_dollar_set():
    c_json = _chain_json_for(_CDE_CONTRACTS)
    after = flatten_chain_contracts(c_json)
    assert len(after) == len(_CDE_CONTRACTS)
    assert _symbols(after) == _symbols(_CDE_CONTRACTS)
    assert {float(c["strikePrice"]) for c in after} == {float(c["strikePrice"]) for c in _CDE_CONTRACTS}
    assert len(_frac(after)) == len(_frac(_CDE_CONTRACTS))
    strikes = {float(c["strikePrice"]) for c in after}
    assert 21.0 in strikes and 21.5 in strikes


def test_persist_keeps_exact_cde_contract_set(tmp_path):
    result = persist_complete_chain_capture(
        tmp_path / "cap.db",
        ticker="CDE",
        expiry=_CDE_EXPIRY,
        contracts=_CDE_CONTRACTS,
        spot=21.43,
        completeness_basis="strike_range=ALL",
        ts_utc=1000.0,
    )
    assert result["status"] == "written"
    assert result["n_contracts"] == len(_CDE_CONTRACTS)
    cap = latest_complete_chain_capture(tmp_path / "cap.db", "CDE", _CDE_EXPIRY)
    assert _symbols(cap["contracts"]) == _symbols(_CDE_CONTRACTS)
    assert len(_frac(cap["contracts"])) == len(_frac(_CDE_CONTRACTS))

_CRWD = json.loads((_FIXTURES / "real_crwd_complete_chain_quarter.json").read_text(encoding="utf-8"))
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

