"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, thirteenth extracted phase.

_db_counts_and_crosses_for_state (server.py) is the DB Counts + Crosses phase
(snapshot counts, gamma-wall level-test counts, recent level crosses),
extracted verbatim from _fetch_state's body.

`ed_db` is a parameter, not a module global: it is _fetch_state's own local
`_ed_db = get_db() if _HAS_SIGNALS else None`, computed once per call from
the feature-flag-gated `_HAS_SIGNALS`. A missing ed_db (None) or a DB query
exception both leave every output at its pre-initialized "no data" default
-- never raise out of _fetch_state, exactly as the original inline
if/try/except did.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import server as srv


class _FakeDB:
    def count_snapshots(self, ticker, tf):
        return {"total": 42, "filled": 40}

    def count_level_tests(self, ticker, name, level):
        return {"total": 5 if name == "Call Gamma Wall" else 3}

    def get_recent_crosses(self, ticker, n):
        return [{"level_name": "VWAP", "direction": "up", "ts_utc": time.time() - 120}]


def test_full_pipeline_matches_expected_counts_and_crosses():
    walls = [SimpleNamespace(call_gamma_wall=100.0, put_gamma_wall=95.0)]
    result = srv._db_counts_and_crosses_for_state("ZZZ_DBCC_MATCH", _FakeDB(), walls)

    assert result.db_counts == {"total": 42, "filled": 40}
    assert result.ceil_tests == 5
    assert result.floor_tests == 3
    assert len(result.recent_crosses) == 1
    assert result.recent_crosses[0]["level_name"] == "VWAP"
    assert result.recent_crosses[0]["direction"] == "up"
    assert result.recent_crosses[0]["bars_ago"] == 2


def test_missing_ed_db_yields_no_data_defaults_without_querying():
    walls = [SimpleNamespace(call_gamma_wall=100.0, put_gamma_wall=95.0)]
    result = srv._db_counts_and_crosses_for_state("ZZZ_DBCC_NONE", None, walls)
    # CAPS RC-REHAB-1: no DB -> counts UNKNOWN (None), not a served "0 snapshots".
    assert result.db_counts == {"total": None, "filled": None}
    assert result.ceil_tests == 0
    assert result.floor_tests == 0
    assert result.recent_crosses == []


def test_db_query_exception_fails_closed_to_defaults_never_raises():
    class _BoomDB:
        def count_snapshots(self, *a, **k):
            raise RuntimeError("boom")

    walls = [SimpleNamespace(call_gamma_wall=100.0, put_gamma_wall=95.0)]
    result = srv._db_counts_and_crosses_for_state("ZZZ_DBCC_BOOM", _BoomDB(), walls)
    # CAPS RC-REHAB-1: failed count query -> counts UNKNOWN (None), not a served 0.
    assert result.db_counts == {"total": None, "filled": None}
    assert result.ceil_tests == 0
    assert result.floor_tests == 0
    assert result.recent_crosses == []


def test_missing_gamma_walls_skip_level_test_counts_but_snapshot_count_still_runs():
    result = srv._db_counts_and_crosses_for_state("ZZZ_DBCC_NOWALLS", _FakeDB(), [])
    assert result.db_counts == {"total": 42, "filled": 40}
    assert result.ceil_tests == 0
    assert result.floor_tests == 0


def test_fetch_state_calls_the_extracted_function_exactly_once():
    """AST lock: _fetch_state must call _db_counts_and_crosses_for_state exactly once."""
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
    assert calls_in_fetch_state.count("_db_counts_and_crosses_for_state") == 1
