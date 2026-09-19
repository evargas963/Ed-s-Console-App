"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, eleventh extracted phase.

_charm_for_state (server.py) is the Charm phase (dealer net charm + direction,
via math_exposure.compute_net_charm), extracted verbatim from _fetch_state's
body. All five outputs are pre-initialized to their "unavailable" defaults
BEFORE the try block, and the whole computation is wrapped in a
try/except Exception that logs and swallows -- an exception anywhere inside
(compute_net_charm itself, or the unavailable-log-level branch) must never
escape, leaving every field safely at its pre-initialized default, exactly
as the original inline code's own try/except did.
"""
from __future__ import annotations

from unittest import mock

import math_exposure
import server as srv


def _fixture_contracts(expiry="2026-10-16"):
    # institutional-synthetic-ok: verifies this phase's own charm-direction wiring in
    # isolation against a minimal, deterministic two-contract fixture with a matching
    # expirationDate -- a real captured chain would obscure which contract drives the
    # expected net_charm_daily value.
    return [
        {"strikePrice": 100.0, "putCall": "CALL", "openInterest": 500, "delta": 0.5, "gamma": 0.05, "vega": 0.1, "volatility": 0.2, "multiplier": 100, "totalVolume": 200, "mark": 2.0, "bid": 1.9, "ask": 2.1, "expirationDate": expiry},
        {"strikePrice": 100.0, "putCall": "PUT", "openInterest": 300, "delta": -0.5, "gamma": 0.05, "vega": 0.1, "volatility": 0.2, "multiplier": 100, "totalVolume": 150, "mark": 1.8, "bid": 1.7, "ask": 1.9, "expirationDate": expiry},
    ]


def test_real_computation_matches_compute_net_charm_directly():
    contracts = _fixture_contracts()
    result = srv._charm_for_state("ZZZ_CHARM_MATCH", contracts, 100.5, "2026-10-16")

    raw = math_exposure.compute_net_charm(contracts, 100.5, "2026-10-16", drift_toward_strike=None)
    assert raw.get("contracts_used", 0) > 0, "fixture must produce real, non-degenerate charm data"
    assert result.charm_net == raw["net_charm_daily"]
    assert result.charm_dir == raw["charm_direction"]
    assert result.charm_toward == raw.get("drift_toward")
    assert result.charm_mag == raw.get("charm_magnitude")
    assert result.charm_drivers == []


def test_zero_contracts_matched_yields_unavailable_defaults_not_a_raise():
    """No contract matches the requested expiry -> contracts_used stays 0 -> the
    original inline code's `if _charm_used > 0` branch is never taken, leaving the
    pre-initialized defaults -- not an error."""
    contracts = _fixture_contracts(expiry="2026-11-20")
    result = srv._charm_for_state("ZZZ_CHARM_ZERO", contracts, 100.5, "2026-10-16")
    assert result.charm_net is None
    assert result.charm_dir is None
    assert result.charm_toward is None
    assert result.charm_mag is None
    assert result.charm_drivers == []


def test_an_exception_anywhere_in_the_phase_is_swallowed_to_defaults():
    contracts = _fixture_contracts()
    with mock.patch.object(math_exposure, "compute_net_charm", side_effect=RuntimeError("boom")):
        result = srv._charm_for_state("ZZZ_CHARM_FAIL", contracts, 100.5, "2026-10-16")
    assert result.charm_net is None
    assert result.charm_dir is None
    assert result.charm_toward is None
    assert result.charm_mag is None
    assert result.charm_drivers == []


def test_fetch_state_calls_the_extracted_function_exactly_once():
    """AST lock: _fetch_state must call _charm_for_state exactly once, and must not
    directly call compute_net_charm itself."""
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
    assert calls_in_fetch_state.count("_charm_for_state") == 1
    assert "compute_net_charm" not in calls_in_fetch_state, (
        "_fetch_state still calls compute_net_charm directly -- the charm phase was "
        "not fully extracted, a second inline computation site survived"
    )
