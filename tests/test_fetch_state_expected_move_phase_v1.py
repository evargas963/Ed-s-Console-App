"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, seventh extracted phase.

_expected_move_for_state (server.py) is the Expected Move phase (ATM straddle + IV-based
EM, EM progress, and the KL/MC anchor resolution), moved out of _fetch_state's body into a
standalone function returning a _ExpectedMoveForState NamedTuple.

These tests prove behavior parity with the original inline chain across the phase's real
decision branches: STRADDLE_IMPLIED taking priority when available, falling back to
IV_MODEL when the straddle cannot be computed, both unavailable, and the phase's own
exception handling (an error anywhere in the try block must be swallowed to the
pre-initialized "unavailable" defaults, never raised into _fetch_state).
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import server as srv
from time_et import ET
from math_exposure import compute_expected_move_straddle, compute_expected_move_iv

NOW = datetime(2026, 9, 21, 14, 0, tzinfo=ET)  # Monday RTH, hours remain until close


def test_straddle_takes_priority_and_matches_the_original_computation_chain():
    price_levels = SimpleNamespace(today_open=448.0)
    # institutional-synthetic-ok: this test verifies _expected_move_for_state's own
    # ATM-strike-matching and straddle arithmetic in isolation against a minimal,
    # deterministic two-contract fixture -- a real captured chain would obscure which
    # specific contract drives the ATM pick and make the expected straddle value opaque.
    contracts = [
        {"strikePrice": 450.0, "putCall": "CALL", "mark": 3.5},
        {"strikePrice": 450.0, "putCall": "PUT", "mark": 3.2},
    ]
    result = srv._expected_move_for_state(NOW, price_levels, contracts, 450.0, 18.5)

    expected_straddle = compute_expected_move_straddle(3.5, 3.2, 448.0)
    assert result.em_straddle == expected_straddle
    assert result.em_band_source == "STRADDLE_IMPLIED"
    assert result.em_up == expected_straddle["upper"]
    assert result.em_lo == expected_straddle["lower"]
    # kl_em_anchor/mc_iv_* are downstream of the resolved band -- must be real, non-default
    assert result.kl_em_anchor != "unavailable"
    assert result.mc_iv_level is not None


def test_falls_back_to_iv_model_when_no_contracts_available():
    from time_et import hours_until_session_close_et

    price_levels = SimpleNamespace(today_open=448.0)
    result = srv._expected_move_for_state(NOW, price_levels, [], 450.0, 18.5)

    assert result.em_straddle == {"straddle": None, "em_pts": None, "upper": None, "lower": None}
    assert result.em_band_source == "IV_MODEL"
    hours_rem = hours_until_session_close_et(NOW) or 0.0
    expected_iv = compute_expected_move_iv(450.0, 18.5, hours_rem)
    assert result.em_iv == expected_iv
    assert result.em_up == result.em_iv["upper"]


def test_both_unavailable_when_no_contracts_and_no_atm_iv():
    price_levels = SimpleNamespace(today_open=448.0)
    result = srv._expected_move_for_state(NOW, price_levels, [], 450.0, None)

    assert result.em_band_source == "unavailable"
    assert result.em_up is None and result.em_lo is None
    assert result.kl_em_anchor == "unavailable"
    assert result.mc_iv_level is None


def test_an_exception_anywhere_in_the_phase_is_swallowed_to_defaults():
    class _BoomPriceLevels:
        @property
        def today_open(self):
            raise ZeroDivisionError("synthetic")

    result = srv._expected_move_for_state(NOW, _BoomPriceLevels(), [], 450.0, 18.5)

    assert result.em_band_source == "unavailable"
    assert result.kl_em_anchor == "unavailable"
    assert result.em_up is None and result.em_lo is None


def test_fetch_state_calls_the_extracted_function_exactly_once():
    """AST lock: _fetch_state must call _expected_move_for_state exactly once, and must
    not directly call compute_expected_move_straddle/compute_expected_move_iv/
    compute_em_progress/resolve_kl_em_anchor/resolve_mc_iv_for_kl_em_anchor itself."""
    import ast
    from pathlib import Path

    src = Path(srv.__file__).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    fetch_state_fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_fetch_state"
    )
    calls_in_fetch_state = [
        n.func.id for n in ast.walk(fetch_state_fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert calls_in_fetch_state.count("_expected_move_for_state") == 1
    for leaked in (
        "compute_expected_move_straddle",
        "compute_expected_move_iv",
        "compute_em_progress",
        "resolve_kl_em_anchor",
        "resolve_mc_iv_for_kl_em_anchor",
    ):
        assert leaked not in calls_in_fetch_state, (
            f"_fetch_state still calls {leaked} directly -- the expected-move phase was "
            f"not fully extracted, a second inline computation site survived"
        )
