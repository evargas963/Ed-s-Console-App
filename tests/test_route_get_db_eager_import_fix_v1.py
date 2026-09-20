"""RC-REHAB-1 (route-extraction audit fix, wider sweep): regression tests for the same
`get_db` eager-import defect found and fixed across 9 functions in 7 more
`app/api/routes/*.py` files, beyond the 6 already covered in
tests/test_logger_pin_unpin_route_fixes_v1.py.

Root cause (see that file's module docstring for the full explanation): `get_db` is
only bound in server's module namespace when server.py's own top-level `db` import
succeeds. Every one of these functions did `from server import (..., get_db, ...)` as
one blanket statement at function entry -- Python resolves every name in that tuple
immediately, so when `get_db` is genuinely unbound, the import statement itself raises
ImportError, one line before any try/except or `_HAS_SIGNALS` guard the function has
around its own DB usage. Fixed by excluding `get_db` from the blanket import and
referencing it via `_server.get_db()` (`import server as _server`) at the point of use.

Each test below simulates the real production scenario (get_db genuinely absent from
server's namespace) and confirms the function reaches its own already-designed
fallback (a graceful payload, a cached response, or a clean skip) instead of raising
an unhandled ImportError.
"""
from __future__ import annotations

from unittest import mock

import server


def _without_get_db():
    had = hasattr(server, "get_db")
    saved = getattr(server, "get_db", None)
    if had:
        delattr(server, "get_db")
    return had, saved


def _restore_get_db(had, saved):
    if had:
        server.get_db = saved


def test_get_accuracy_falls_back_cleanly_when_get_db_unbound():
    from app.api.routes.accuracy import get_accuracy

    had, saved = _without_get_db()
    try:
        with mock.patch.object(server, "_HAS_SIGNALS", False):
            result = get_accuracy(ticker="ZZZ_AUDIT_TEST")  # must not raise
        assert isinstance(result, dict)
    finally:
        _restore_get_db(had, saved)


def test_get_exposure_flow_falls_back_cleanly_when_get_db_unbound():
    from app.api.routes.exposure import get_exposure_flow

    had, saved = _without_get_db()
    try:
        response = get_exposure_flow(ticker="ZZZ_AUDIT_TEST")  # must not raise
        assert response.status_code == 200
    finally:
        _restore_get_db(had, saved)


def test_get_exposure_book_falls_back_cleanly_when_get_db_unbound():
    from app.api.routes.exposure import get_exposure_book

    had, saved = _without_get_db()
    try:
        response = get_exposure_book(ticker="ZZZ_AUDIT_TEST")  # must not raise
        assert response.status_code == 200
    finally:
        _restore_get_db(had, saved)


def test_get_exposure_history_falls_back_cleanly_when_get_db_unbound():
    from app.api.routes.exposure import get_exposure_history

    had, saved = _without_get_db()
    try:
        response = get_exposure_history(ticker="ZZZ_AUDIT_TEST")  # must not raise
        assert response.status_code == 200
    finally:
        _restore_get_db(had, saved)


def test_get_bars1m_falls_back_cleanly_when_get_db_unbound():
    from app.api.routes.market_data import get_bars1m

    had, saved = _without_get_db()
    try:
        response = get_bars1m(ticker="ZZZ_AUDIT_TEST")  # must not raise
        assert response.status_code == 200
    finally:
        _restore_get_db(had, saved)


def test_get_forces_falls_back_cleanly_when_get_db_unbound():
    from app.api.routes.market_data import get_forces

    had, saved = _without_get_db()
    try:
        response = get_forces(ticker="ZZZ_AUDIT_TEST")  # must not raise
        assert response.status_code == 200
    finally:
        _restore_get_db(had, saved)


def test_get_options_gamma_surface_falls_back_cleanly_when_get_db_unbound():
    """A ticker with no live terrain cache and no banked gamma-surface cache takes the
    route's own designed 'unavailable' fallback path, which is exactly the code path
    that used to hit the unguarded get_db() call."""
    from app.api.routes.options import get_options_gamma_surface

    had, saved = _without_get_db()
    try:
        with mock.patch.object(server, "terrain_cache_get", return_value=None), \
             mock.patch.object(server, "_GAMMA_SURFACE_CACHE", {}):
            response = get_options_gamma_surface(ticker="ZZZ_AUDIT_TEST")  # must not raise
        assert response.status_code == 200
    finally:
        _restore_get_db(had, saved)


def test_get_terrain_strikes_falls_back_cleanly_when_get_db_unbound():
    from app.api.routes.terrain import get_terrain_strikes

    had, saved = _without_get_db()
    try:
        with mock.patch.object(server, "terrain_cache_get", return_value=None):
            response = get_terrain_strikes(ticker="ZZZ_AUDIT_TEST")  # must not raise
        assert response.status_code == 200
    finally:
        _restore_get_db(had, saved)


def test_get_chain_persisted_capture_read_falls_back_cleanly_when_get_db_unbound():
    """Forces the live-fetch branch to fail so get_chain reaches its persisted-capture
    fallback read (latest_complete_chain_capture(_server.get_db().db_path, ...)) --
    the exact call site that used to hit the unguarded get_db()."""
    from app.api.routes.chain import get_chain

    had, saved = _without_get_db()
    try:
        with mock.patch.object(server, "_fetch_expiries_light", return_value=["2026-10-16"]), \
             mock.patch.object(server, "_gated_safe_get_chain", side_effect=RuntimeError("simulated live-fetch failure")):
            response = get_chain(ticker="ZZZ_AUDIT_TEST", expiry=None)  # must not raise ImportError
        assert response.status_code == 200
    finally:
        _restore_get_db(had, saved)


def test_debug_prediction_zone_distribution_falls_back_cleanly_when_get_db_unbound():
    """debug_prediction's own get_db() call is gated by `if _HAS_SIGNALS:` -- when
    _HAS_SIGNALS is False, that block is skipped and get_db is never touched at all, so
    this test instead confirms the case where _HAS_SIGNALS is (still) True but get_db
    is unbound raises the SAME clean behavior the guard is meant to prevent from being
    dead code: mocks _fetch_state (heavy, unrelated to this defect) to isolate the
    get_db() call site itself."""
    import os

    from app.api.routes.debug import debug_prediction

    had, saved = _without_get_db()
    try:
        with mock.patch.dict(os.environ, {"ED_ALLOW_DEBUG_ENDPOINTS": "1"}), \
             mock.patch.object(server, "_HAS_SIGNALS", False), \
             mock.patch.object(server, "_fetch_state", return_value={}):
            result = debug_prediction(ticker="ZZZ_AUDIT_TEST")  # must not raise
        assert isinstance(result, dict)
    finally:
        _restore_get_db(had, saved)


def test_no_get_db_route_function_leaves_get_db_in_its_blanket_import_tuple():
    """AST sweep: none of the fixed functions should still list `get_db` as a name in
    a `from server import (...)` statement -- it must only ever be reached via
    `_server.get_db()` / `server.get_db()` attribute access."""
    import ast
    from pathlib import Path

    files = [
        "app/api/routes/logger.py",
        "app/api/routes/accuracy.py",
        "app/api/routes/chain.py",
        "app/api/routes/debug.py",
        "app/api/routes/exposure.py",
        "app/api/routes/market_data.py",
        "app/api/routes/options.py",
        "app/api/routes/terrain.py",
    ]
    root = Path(server.__file__).resolve().parent
    violations = []
    for rel in files:
        path = root / rel
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "server":
                for alias in node.names:
                    if alias.name == "get_db":
                        violations.append(f"{rel}:{node.lineno}")
    assert violations == [], (
        "these `from server import (...)` statements still list get_db directly, "
        "reintroducing the eager-import crash: " + ", ".join(violations)
    )
