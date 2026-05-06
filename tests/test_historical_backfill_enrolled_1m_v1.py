"""historical_backfill_enrolled_1m_v1: persistence vs fetch semantics and DB lock handling."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from db import EdDB
from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
from timeframe_config import CANONICAL_TIMEFRAME as CF
from tools import historical_backfill_enrolled_1m_v1 as bf


def _seed_aapl_enrolled(tmp_db: Path) -> None:
    db = EdDB(tmp_db)
    ts = 1_800_000_000.0
    db.logging_universe_sync_core(["AAPL"], ts)
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            ("AAPL", CF, ts, "test", 10, 30, "rth", 100.0, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
        )


def test_probe_exclusive_sqlite_write_fails_when_write_lock_held(tmp_path: Path) -> None:
    db_path = tmp_path / "contended.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS t(x INTEGER)")
    conn.execute("BEGIN IMMEDIATE")
    try:
        ok, err = bf.probe_exclusive_sqlite_write(db_path, timeout_s=0.25)
        assert ok is False
        assert err
        assert "locked" in err.lower() or "busy" in err.lower()
    finally:
        conn.rollback()
        conn.close()


def test_apply_summary_fetch_ok_zero_upsert_is_fail() -> None:
    audit = {
        "dry_run": False,
        "windows": [
            {
                "ticker": "AAPL",
                "window_start_utc": "2026-01-01T00:00:00+00:00",
                "http_status": 200,
                "n_candles": 3,
                "n_bars_parsed": 3,
                "bars_upsert_count": 0,
                "error": None,
                "db_locked": False,
            }
        ],
    }
    bf._apply_backfill_outcome_summary(audit)
    assert audit["candles_fetched"] == 3
    assert audit["bars_upsert_count"] == 0
    assert audit["persistence_success"] is False
    assert audit["final_status"] == "FAILED_PERSISTENCE_ZERO_UPSERT"
    assert audit["window_errors"]


def test_apply_summary_db_locked_preflight() -> None:
    audit = {
        "dry_run": False,
        "error": "probe failed",
        "db_locked_preflight": True,
        "windows": [],
    }
    bf._apply_backfill_outcome_summary(audit)
    assert audit["db_locked"] is True
    assert audit["persistence_success"] is False
    assert audit["final_status"] == "FAILED_DB_LOCKED_PREFLIGHT"


def test_run_preflight_aborts_before_schwab_when_db_locked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "pre.db"
    _seed_aapl_enrolled(db_path)

    hold = sqlite3.connect(str(db_path), timeout=1.0)
    hold.execute("BEGIN IMMEDIATE")
    try:

        def boom(*_a, **_k):
            raise AssertionError("Schwab client must not be created when preflight fails")

        monkeypatch.setitem(sys.modules, "server", MagicMock(get_client=boom))

        out = bf.run(
            db_path,
            lookback_days=1,
            window_days=7,
            dry_run=False,
            only_under_covered=False,
            under_covered_max_bars=4000,
            tickers_filter=["AAPL"],
            skip_governed_outcome_refresh=True,
        )
    finally:
        hold.rollback()
        hold.close()

    assert out.get("aborted_before_schwab") is True
    assert out.get("db_locked_preflight") is True
    assert out.get("candles_fetched") == 0
    assert out.get("persistence_success") is False
    assert out.get("final_status") == "FAILED_DB_LOCKED_PREFLIGHT"
    assert out.get("db_locked") is True


def test_run_upsert_operational_locked_surfaces_db_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "up.db"
    _seed_aapl_enrolled(db_path)

    class Resp:
        status_code = 200

        def json(self):
            ts_ms = 1_704_000_000_000  # ms; adapter converts to seconds
            return {"candles": [{"datetime": ts_ms, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10}]}

    def _fake_fetch(_client, _sym, _start, _end):
        return Resp()

    def _locked_upsert(_self, _ticker, _bars):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(bf, "_fetch_minute_window", _fake_fetch)
    monkeypatch.setattr(EdDB, "upsert_1m_bars", _locked_upsert)

    fake_mod = MagicMock()

    def _gc():
        return object()

    fake_mod.get_client = _gc
    monkeypatch.setitem(sys.modules, "server", fake_mod)

    out = bf.run(
        db_path,
        lookback_days=1,
        window_days=7,
        dry_run=False,
        only_under_covered=False,
        under_covered_max_bars=4000,
        tickers_filter=["AAPL"],
        skip_governed_outcome_refresh=True,
    )

    assert out.get("aborted_after_db_lock") is True
    assert out.get("candles_fetched", 0) >= 1
    assert out.get("bars_upsert_count") == 0
    assert out.get("db_locked") is True
    assert out.get("persistence_success") is False
    assert out.get("final_status") == "FAILED_DB_LOCKED_RUNTIME"
    assert out.get("window_errors")


def test_main_nonzero_when_fetch_ok_but_persistence_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(*_a, **_k):
        return {
            "schema": "historical_backfill_enrolled_1m_v1",
            "dry_run": False,
            "window_errors": [{"ticker": "AAPL", "window_start": "x", "error": "database is locked", "db_locked": True}],
            "persistence_success": False,
            "final_status": "FAILED_DB_LOCKED_RUNTIME",
            "windows": [],
        }

    monkeypatch.setattr(bf, "run", _fake_run)
    monkeypatch.setattr(bf, "require_canonical_db_target", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["historical_backfill_enrolled_1m_v1.py", "--allow-noncanonical-db", "--db", "nope.db"])
    assert bf.main() == 1
