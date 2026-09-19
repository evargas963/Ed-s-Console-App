"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, sixth extracted phase.

_price_levels_for_state (server.py) is the Price Levels phase, moved out of
_fetch_state's body into a standalone function. Unlike the first five extracted phases,
this one has a real side effect on shared mutable state: it reads AND writes
server.py's module-level `_state_cache` dict (the same cache /api/analytics/state's
stale-while-refresh read path serves from). `_state_cache` is referenced directly as a
module global inside the extracted function -- not passed as a parameter -- matching the
treatment already given to other module-level singletons (_candles_1m) in earlier slices.

These tests prove the four distinct control-flow paths the original inline
try/except/else block had all survived the extraction exactly: a cache hit (no fetch,
no cache write), a successful fetch (cache write with the new generation), a raised
LevelCarrierConflict (re-raised, no cache write), and a generic fetch failure (falls
back to a bare PriceLevels(), and critically does NOT write to the cache -- Python's
try/except/else semantics mean the else clause, which does the cache write, only runs
when the try block raised nothing at all).
"""
from __future__ import annotations

from datetime import datetime
from unittest import mock

import server as srv
from liquidity_value_engine import LevelCarrierConflict


NOW = datetime(2026, 9, 19, 14, 30)
CACHE_KEY = ("TESTPL", None)


def setup_function(_fn):
    srv._state_cache.pop(CACHE_KEY, None)


def teardown_function(_fn):
    srv._state_cache.pop(CACHE_KEY, None)


def test_cache_hit_returns_the_carried_entry_without_fetching():
    srv._state_cache[CACHE_KEY] = {
        "price_levels": "CACHED_OBJ", "pl_date": "2026-09-19", "pl_generation": 5,
    }
    with mock.patch.object(srv, "canonical_price_level_snapshot", return_value="SNAP"), \
         mock.patch.object(srv, "carried_price_levels_match_snapshot", return_value=True), \
         mock.patch.object(srv, "fetch_price_levels") as fetch_mock:
        result = srv._price_levels_for_state("TESTPL", object(), {}, NOW, CACHE_KEY)

    assert result == "CACHED_OBJ"
    assert not fetch_mock.called, "fetch_price_levels must not run on a cache hit"


def test_successful_fetch_writes_the_new_generation_into_state_cache():
    fake_pl = mock.Mock(
        error=None, vwap=450.5, bars_today=30,
        session_rth_positive_volume_bars=10, level_generation=7, today_open=449.0,
    )
    with mock.patch.object(srv, "canonical_price_level_snapshot", return_value=mock.Mock(generation=7)), \
         mock.patch.object(srv, "carried_price_levels_match_snapshot", return_value=False), \
         mock.patch.object(srv, "fetch_price_levels", return_value=fake_pl), \
         mock.patch("liquidity_value_engine.classify_session_vwap_presence", return_value="ok"):
        result = srv._price_levels_for_state("TESTPL", object(), {}, NOW, CACHE_KEY)

    assert result is fake_pl
    assert CACHE_KEY in srv._state_cache
    assert srv._state_cache[CACHE_KEY]["price_levels"] is fake_pl
    assert srv._state_cache[CACHE_KEY]["pl_generation"] == 7
    assert srv._state_cache[CACHE_KEY]["pl_date"] == "2026-09-19"


def test_level_carrier_conflict_is_re_raised_not_swallowed():
    with mock.patch.object(srv, "canonical_price_level_snapshot", return_value="SNAP"), \
         mock.patch.object(srv, "carried_price_levels_match_snapshot", return_value=False), \
         mock.patch.object(srv, "fetch_price_levels", side_effect=LevelCarrierConflict("conflict!")):
        try:
            srv._price_levels_for_state("TESTPL", object(), {}, NOW, CACHE_KEY)
            assert False, "LevelCarrierConflict must propagate, not be swallowed"
        except LevelCarrierConflict:
            pass
    assert CACHE_KEY not in srv._state_cache, "no cache write on a raised conflict"


def test_generic_fetch_failure_falls_back_without_writing_the_cache():
    """The critical try/except/else detail: the cache write lives in the `else` clause,
    which only runs when the try block raised NOTHING. A caught generic exception must
    fall back to a bare PriceLevels() and leave _state_cache untouched for this key --
    writing a stale/empty entry here would let a transient vendor failure poison the
    shared Tier C cache for every other reader."""
    with mock.patch.object(srv, "canonical_price_level_snapshot", return_value="SNAP"), \
         mock.patch.object(srv, "carried_price_levels_match_snapshot", return_value=False), \
         mock.patch.object(srv, "fetch_price_levels", side_effect=RuntimeError("vendor down")):
        result = srv._price_levels_for_state("TESTPL", object(), {}, NOW, CACHE_KEY)

    assert isinstance(result, srv.PriceLevels)
    assert CACHE_KEY not in srv._state_cache, "a swallowed exception must not write to the cache"


def test_fetch_state_calls_the_extracted_function_exactly_once():
    """AST lock: _fetch_state must call _price_levels_for_state exactly once, and must
    not directly call fetch_price_levels/canonical_price_level_snapshot/
    carried_price_levels_match_snapshot itself -- proving no second inline copy of this
    phase survived the extraction."""
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
    assert calls_in_fetch_state.count("_price_levels_for_state") == 1
    for leaked in (
        "fetch_price_levels",
        "canonical_price_level_snapshot",
        "carried_price_levels_match_snapshot",
    ):
        assert leaked not in calls_in_fetch_state, (
            f"_fetch_state still calls {leaked} directly -- the price-levels phase was "
            f"not fully extracted, a second inline computation site survived"
        )
