"""Tests for base/guest ticker tiers and RTH observability checker."""
from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path















def _seed_dense_rth_rows(conn: sqlite3.Connection, ticker: str, start: float) -> None:
    ts = start + 60
    while ts <= start + 300 * 60:
        conn.execute("INSERT INTO snapshots VALUES (?, ?)", (ticker, ts))
        conn.execute("INSERT INTO snapshots_1m_normalized VALUES (?, ?)", (ticker, ts))
        conn.execute("INSERT INTO calibration_decision_log VALUES (?, ?)", (ticker, ts))
        ts += 60


















def test_insert_snapshot_persists_logger_source(tmp_path: Path):
    from db import EdDB, SnapshotRow
    from timeframe_config import CANONICAL_TIMEFRAME

    db = EdDB(tmp_path / "src.db")
    row = SnapshotRow(
        ticker="IWM",
        timeframe=CANONICAL_TIMEFRAME,
        ts_utc=1_781_800_000.0,
        ts_et="2026-06-18 10:00:00 ET",
        et_hour=10,
        et_minute=0,
        market_session="rth",
        spot=200.0,
        logger_source="base_money_path",
    )
    db.insert_snapshot(row)
    with db._connect() as conn:
        src = conn.execute(
            "SELECT logger_source FROM snapshots WHERE ticker='IWM'"
        ).fetchone()[0]
    assert src == "base_money_path"


# ── LIVE_OPERATOR_MODE_RESET_V1 Step 1 — RTH viewer gate on the background logger ──


def _fixed_et(year: int, month: int, day: int, hour: int, minute: int):
    """Naive stand-in for time_et.now_et — the gate only reads hour/minute/weekday."""
    return datetime.datetime(year, month, day, hour, minute)




def _run_logger_fetch(monkeypatch, ticker: str, *, live_mode: bool):
    """Drive _logger_fetch_and_log with the gate forced and _fetch_state recorded."""
    import server as srv

    calls: list[tuple[str, bool]] = []

    def _fake_fetch_state(t, expiry=None, log_only=False, **kwargs):
        calls.append((t, log_only))
        return {}

    def _no_db():
        raise RuntimeError("no db in this unit test")

    monkeypatch.setattr(srv, "_is_loggable_session", lambda: True)
    monkeypatch.setattr(srv, "_live_operator_mode_active", lambda: live_mode)
    monkeypatch.setattr(srv, "_fetch_state", _fake_fetch_state)
    # Keep panel_auto skip check + touch_background_log off the real DB (both wrap
    # get_db() in try/except and degrade gracefully).
    monkeypatch.setattr(srv, "get_db", _no_db)
    status = srv._logger_fetch_and_log(ticker)
    return status, calls










# ── LIVE_OPERATOR_MODE_RESET_V1 Step 3 — live-path DB write gating ──






