"""
Persistent ticker enrollment: selected symbols stay in logging_universe and logger cycle
(default: no FIFO eviction). Survives _hydrate_logger_tickers_from_db (restart simulation).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import EdDB


def test_hydrate_merges_all_user_persisted_into_logger_cycle(monkeypatch, tmp_path):
    """After DB load, every user_persisted symbol is in _logger_tickers (restart simulation)."""
    import db as dbmod
    import server as srv

    edb = EdDB(tmp_path / "persist.db")
    now = 1_700_000_000.0
    monkeypatch.setattr("db._db_instance", edb)
    assert dbmod.get_db() is edb
    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    monkeypatch.setattr(srv, "_run_legacy_logger_json_migration", lambda _db: None)
    prev = list(srv.CORE_TICKERS)
    try:
        srv.CORE_TICKERS[:] = ["SPY"]
        edb.logging_universe_sync_core(["SPY"], now)
        edb.logging_universe_upsert_user_persisted("ALFA", "test_ui", now + 1)
        edb.logging_universe_upsert_user_persisted("BETA", "test_ui", now + 2)
        srv._hydrate_logger_tickers_from_db()
        tickers = list(srv._logger_tickers)
        assert "SPY" in tickers
        assert "ALFA" in tickers
        assert "BETA" in tickers
    finally:
        srv.CORE_TICKERS[:] = prev


def test_second_registration_does_not_remove_first_ticker(monkeypatch, tmp_path):
    """Registering ticker B after A leaves A in the in-memory logger list."""
    import db as dbmod
    import server as srv

    edb = EdDB(tmp_path / "two.db")
    monkeypatch.setattr("db._db_instance", edb)
    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    monkeypatch.setattr(srv, "_run_legacy_logger_json_migration", lambda _db: None)
    monkeypatch.delenv("ED_LOGGING_UNIVERSE_FIFO_EVICTION", raising=False)
    prev = list(srv.CORE_TICKERS)
    try:
        srv.CORE_TICKERS[:] = ["SPY"]
        edb.logging_universe_sync_core(["SPY"], 1.0)
        with srv._logger_lock:
            srv._logger_tickers[:] = list(srv.CORE_TICKERS)
        srv._register_tracked_ticker("ALFA")
        srv._register_tracked_ticker("BETA")
        merged = list(srv._logger_tickers)
        assert "ALFA" in merged
        assert "BETA" in merged
    finally:
        srv.CORE_TICKERS[:] = prev


def test_logger_status_includes_enrollment_policy(monkeypatch, tmp_path):
    import db as dbmod
    import server as srv

    edb = EdDB(tmp_path / "st.db")
    now = 1.0
    edb.logging_universe_sync_core(["SPY"], now)
    monkeypatch.setattr("db._db_instance", edb)
    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    monkeypatch.setattr(srv, "_run_legacy_logger_json_migration", lambda _db: None)
    monkeypatch.delenv("ED_LOGGING_UNIVERSE_FIFO_EVICTION", raising=False)
    prev = list(srv.CORE_TICKERS)
    try:
        srv.CORE_TICKERS[:] = ["SPY"]
        with srv._logger_lock:
            srv._logger_tickers[:] = ["SPY"]
        from starlette.testclient import TestClient

        with TestClient(srv.app) as client:
            r = client.get("/api/logger/status")
            assert r.status_code == 200
            pol = r.json().get("user_persisted_enrollment_policy")
            assert pol is not None
            assert pol.get("fifo_eviction_enabled") is False
            assert pol.get("unlimited_user_persisted") is True
    finally:
        srv.CORE_TICKERS[:] = prev
