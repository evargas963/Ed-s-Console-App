"""RC-REHAB-1 (route-extraction audit fix): regression tests for a systemic bug an
independent audit found (and further investigation widened) in
app/api/routes/logger.py, introduced silently by the original mechanical move of these
routes out of server.py.

Root cause: `get_db` is only bound in server's module namespace when `from db import
get_db` succeeds at server.py's top-level import (see server.py's `try: from db import
get_db; _HAS_SIGNALS = True / except: _HAS_SIGNALS = False`). EVERY route in this file
that referenced `get_db` did so via a blanket `from server import (..., get_db, ...)`
at function entry -- and Python resolves every name in that tuple immediately, so if
`_HAS_SIGNALS` is False (get_db never bound), the IMPORT STATEMENT ITSELF raises
ImportError before any `if not _HAS_SIGNALS: raise HTTPException(503, ...)` guard ever
runs. The audit's own reading only caught logger_unpin, which was missing that guard's
TEXT entirely -- it did not catch that the guard was equally dead code in the other
five functions (logger_status, logger_universe, logger_universe_by_category,
logger_pin, logger_remove) despite the guard text being present in most of them,
because the failure happens one line earlier, at the import itself. Fixed by excluding
`get_db` from every such import tuple and referencing it via `_server.get_db()`
(`import server as _server`) instead, so its resolution is deferred to the point of
use -- which in every case is already inside an `if _HAS_SIGNALS:`-guarded block.

A second, narrower bug (logger_pin and logger_unpin only): both routes did `from
server import _logger_tickers` at function entry, then called
`_hydrate_logger_tickers_from_db()` (which REASSIGNS the module global
`_logger_tickers = merged` rather than mutating it in place), then read
`_logger_tickers` again for the response body. Because the local name was bound to the
pre-hydrate list object before the reassignment, the response's `all_tickers` field
silently reflected stale data -- the ticker just pinned/unpinned would be
missing/present incorrectly in that one response, even though the DB write and
server's own module state were both correct.
"""
from __future__ import annotations

from unittest import mock

import pytest
from fastapi import HTTPException

import server


def _without_get_db():
    """Context manager-ish helper: temporarily remove `get_db` from server's module
    namespace to simulate the real production scenario (the `db` import failed at
    server.py's own top-level load), and restore it afterward."""
    had = hasattr(server, "get_db")
    saved = getattr(server, "get_db", None)
    if had:
        delattr(server, "get_db")
    return had, saved


def _restore_get_db(had, saved):
    if had:
        server.get_db = saved


@pytest.mark.parametrize(
    "fn_name,kwargs,expected_status",
    [
        ("logger_universe", {}, 503),
        ("logger_universe_by_category", {"category": "core"}, 503),
        ("logger_pin", {"ticker": "SPY"}, 503),
        ("logger_unpin", {"ticker": "SPY"}, 503),
    ],
)
def test_gate_checked_logger_routes_return_clean_503_when_signals_unavailable(
    fn_name, kwargs, expected_status
):
    """These four routes are supposed to reject with a clean 503 when the signals/db
    subsystem is unavailable. Before the fix, each one's `from server import (...,
    get_db, ...)` raised an uncaught ImportError before the guard ever ran."""
    import app.api.routes.logger as logger_routes

    fn = getattr(logger_routes, fn_name)
    had, saved = _without_get_db()
    try:
        with mock.patch.object(server, "_HAS_SIGNALS", False):
            with pytest.raises(HTTPException) as exc_info:
                fn(**kwargs)
        assert exc_info.value.status_code == expected_status
    finally:
        _restore_get_db(had, saved)


def test_logger_status_does_not_crash_when_signals_unavailable():
    """logger_status doesn't raise on missing signals -- it just skips the DB-join
    sections. Before the fix, the eager `from server import (..., get_db, ...)` still
    crashed with ImportError regardless of that conditional design."""
    from app.api.routes.logger import logger_status

    had, saved = _without_get_db()
    try:
        with mock.patch.object(server, "_HAS_SIGNALS", False):
            response = logger_status()  # must not raise
        assert response.status_code == 200
    finally:
        _restore_get_db(had, saved)


def test_logger_remove_does_not_crash_when_signals_unavailable():
    """logger_remove also doesn't raise on missing signals for the DB-removal step --
    it just skips it and still removes the ticker from the in-memory list. Uses a
    non-core, non-panel-auto ticker so the function reaches the get_db()-guarded block
    rather than returning early on an unrelated guard."""
    from app.api.routes.logger import logger_remove

    had, saved = _without_get_db()
    try:
        with mock.patch.object(server, "_HAS_SIGNALS", False), \
             mock.patch.object(server, "CORE_TICKERS", frozenset()), \
             mock.patch.object(server, "_market_context_panel_auto_candidates", return_value=[]), \
             mock.patch.object(server, "_logger_tickers", ["ZZZNOTCORE"]):
            response = logger_remove(ticker="ZZZNOTCORE")  # must not raise
        assert response.status_code == 200
    finally:
        _restore_get_db(had, saved)


def test_logger_pin_response_reflects_post_hydrate_tickers_not_stale_list():
    """_hydrate_logger_tickers_from_db reassigns server._logger_tickers to a NEW list
    object. The route's response must reflect that new object, not the one captured
    before hydration ran."""
    from app.api.routes.logger import logger_pin

    stale_list = ["AAPL"]
    fresh_list = ["AAPL", "MSFT", "NEWPIN"]

    class _FakeDB:
        def logging_universe_list_rows(self):
            return []

        def logging_universe_pinned_count(self):
            return 0

        def logging_universe_upsert_pinned(self, ticker, source, ts):
            return None

    def _fake_hydrate():
        # Simulate the real reassignment behavior: a NEW list object replaces the old one.
        server._logger_tickers = fresh_list

    with mock.patch.object(server, "_HAS_SIGNALS", True), \
         mock.patch.object(server, "_logger_tickers", stale_list), \
         mock.patch.object(server, "get_db", return_value=_FakeDB()), \
         mock.patch.object(server, "_hydrate_logger_tickers_from_db", side_effect=_fake_hydrate), \
         mock.patch.object(server, "CORE_TICKERS", frozenset()), \
         mock.patch.object(server, "MAX_PINNED_LOGGING_TICKERS", 100):
        try:
            response = logger_pin(ticker="NEWPIN")
        finally:
            server._logger_tickers = stale_list  # restore module state for other tests

    import json
    body = json.loads(response.body)
    assert body["all_tickers"] == fresh_list, (
        "response must reflect the freshly-hydrated ticker list, not the one captured "
        "before _hydrate_logger_tickers_from_db() reassigned the module global"
    )


def test_logger_unpin_response_reflects_post_hydrate_tickers_not_stale_list():
    from app.api.routes.logger import logger_unpin

    stale_list = ["AAPL", "OLDPIN"]
    fresh_list = ["AAPL"]

    class _FakeDB:
        def logging_universe_unpin_to_user_persisted(self, ticker, ts):
            return True

    def _fake_hydrate():
        server._logger_tickers = fresh_list

    with mock.patch.object(server, "_HAS_SIGNALS", True), \
         mock.patch.object(server, "_logger_tickers", stale_list), \
         mock.patch.object(server, "get_db", return_value=_FakeDB()), \
         mock.patch.object(server, "_hydrate_logger_tickers_from_db", side_effect=_fake_hydrate):
        try:
            response = logger_unpin(ticker="OLDPIN")
        finally:
            server._logger_tickers = stale_list

    import json
    body = json.loads(response.body)
    assert body["all_tickers"] == fresh_list, (
        "response must reflect the freshly-hydrated ticker list, not the one captured "
        "before _hydrate_logger_tickers_from_db() reassigned the module global"
    )
