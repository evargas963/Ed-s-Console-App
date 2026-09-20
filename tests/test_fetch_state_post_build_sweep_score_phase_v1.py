"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, seventeenth extracted phase.

_post_build_sweep_score_for_state (server.py) is the Sweep Score phase, extracted
verbatim from _fetch_state's body. Must run AFTER build_market_state --
ms.nearest_above_dist / ms.nearest_below_dist are populated by build_market_state from
walls + price_levels, and are not available any earlier. This is the fix for
FIND-SERVER-SWEEP-DEAD-FEED: a defunct `'ms' in dir()` guard used to run this
computation before ms existed at all, always evaluating False and silently degrading
sweep_score to empty on every tick (see
tests/test_server_sweep_score_post_build_market_state.py, which locks the "must run
after build_market_state" shape independently of this file).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import server as srv


def test_full_pipeline_matches_the_original_computation_chain():
    ms = SimpleNamespace(nearest_above_dist=5.0, nearest_below_dist=8.0)
    result = srv._post_build_sweep_score_for_state(ms, 2.0, 1.5, 0.3)

    expected_momentum = min(1.0, abs(1.5) / 2.0)
    expected = srv.compute_sweep_score(5.0, 0.3, expected_momentum) or {}
    assert result == expected
    assert result, "fixture must produce a real, non-degenerate sweep score"


def test_nearest_wall_dist_picks_the_smaller_of_the_two_distances():
    ms = SimpleNamespace(nearest_above_dist=12.0, nearest_below_dist=3.0)
    result = srv._post_build_sweep_score_for_state(ms, 2.0, 1.5, 0.3)
    expected_momentum = min(1.0, abs(1.5) / 2.0)
    expected = srv.compute_sweep_score(3.0, 0.3, expected_momentum) or {}
    assert result == expected


def test_missing_ms_attrs_yield_none_wall_dist_but_still_computes():
    ms = SimpleNamespace()
    result = srv._post_build_sweep_score_for_state(ms, 2.0, 1.5, 0.3)
    expected_momentum = min(1.0, abs(1.5) / 2.0)
    expected = srv.compute_sweep_score(None, 0.3, expected_momentum) or {}
    assert result == expected


def test_zero_or_none_atr_yields_zero_momentum():
    ms = SimpleNamespace(nearest_above_dist=5.0, nearest_below_dist=8.0)
    result = srv._post_build_sweep_score_for_state(ms, 0.0, 1.5, 0.3)
    expected = srv.compute_sweep_score(5.0, 0.3, 0.0) or {}
    assert result == expected

    result2 = srv._post_build_sweep_score_for_state(ms, None, 1.5, 0.3)
    assert result2 == expected


def test_exception_anywhere_in_the_phase_fails_closed_to_empty_dict():
    ms = SimpleNamespace(nearest_above_dist=5.0, nearest_below_dist=8.0)
    with mock.patch.object(srv, "compute_sweep_score", side_effect=RuntimeError("boom")):
        result = srv._post_build_sweep_score_for_state(ms, 2.0, 1.5, 0.3)
    assert result == {}


def test_fetch_state_calls_the_extracted_function_exactly_once():
    """AST lock: _fetch_state must call _post_build_sweep_score_for_state exactly
    once, and must not directly call compute_sweep_score itself. This complements (not
    replaces) tests/test_server_sweep_score_post_build_market_state.py's own
    build_market_state-ordering lock, which now targets this extracted function
    (verified in that file directly)."""
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
    assert calls_in_fetch_state.count("_post_build_sweep_score_for_state") == 1
    assert "compute_sweep_score" not in calls_in_fetch_state, (
        "_fetch_state still calls compute_sweep_score directly -- the sweep-score "
        "phase was not fully extracted, a second inline computation site survived"
    )
