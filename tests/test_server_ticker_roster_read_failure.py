"""
No-fallback lock repair (2026-09-17): server.py's three background-loop ticker-roster
readers (_terrain_loop, _bars_loop, _seed_strike_geometry_from_storage) used to silently
process CORE_TICKERS as the enrolled roster on any _logger_lock/_logger_tickers read
failure -- running that cycle's work against a roster the operator never enrolled,
indistinguishable from a genuine enrolled board. A roster-read failure must not be
treated as though CORE_TICKERS were the requested set:
- _terrain_loop / _bars_loop: skip this cycle's enrolled-board work (tickers stays []),
  the same degrade-safely behavior a genuinely empty enrolled board already has.
- _seed_strike_geometry_from_storage: the roster-read exception is left to propagate to
  its caller (_terrain_prewarm_worker), which already has a documented, accepted degrade
  path for this whole seed failing outright ("first cycle uses cold-start width").
"""
from __future__ import annotations

import inspect

import server


class _RaisingLock:
    def __enter__(self):
        raise RuntimeError("simulated logger-lock failure")

    def __exit__(self, *exc):
        return False


def _code_only(src: str) -> str:
    return "\n".join(line for line in src.splitlines() if not line.strip().startswith("#"))


def test_core_tickers_no_longer_substituted_in_terrain_loop_source():
    src = _code_only(inspect.getsource(server._terrain_loop))
    assert "CORE_TICKERS" not in src


def test_core_tickers_no_longer_substituted_in_bars_loop_source():
    src = _code_only(inspect.getsource(server._bars_loop))
    assert "CORE_TICKERS" not in src


def test_core_tickers_no_longer_substituted_in_seed_strike_geometry_source():
    src = _code_only(inspect.getsource(server._seed_strike_geometry_from_storage))
    assert "CORE_TICKERS" not in src


def test_seed_strike_geometry_propagates_roster_read_failure(monkeypatch):
    monkeypatch.setattr(server, "_logger_lock", _RaisingLock())
    try:
        server._seed_strike_geometry_from_storage()
        raised = False
    except RuntimeError as e:
        raised = True
        assert "simulated logger-lock failure" in str(e)
    assert raised, (
        "a roster-read failure must propagate to _terrain_prewarm_worker's own "
        "documented degrade path, not be silently narrowed to CORE_TICKERS inside "
        "_seed_strike_geometry_from_storage"
    )


def test_terrain_prewarm_worker_already_degrades_a_whole_seed_failure(monkeypatch):
    """The caller-side safety net this repair now relies on."""
    src = inspect.getsource(server._terrain_prewarm_worker)
    assert "_seed_strike_geometry_from_storage()" in src
    assert "except Exception" in src
