"""Tests for base/guest ticker tiers and RTH observability checker."""
from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path







def test_the_tier_skip_predicate_is_gone_not_neutered():
    """UNIVERSAL COLLECTION (operator, 2026-08-25): the panel_auto confluence-only carve-out
    is RETIRED. An always-False shim would repeat RC-474 (dead producer left behind to be
    re-wired), so the predicate is deleted outright — importing it must fail."""
    import money_path_ticker_tiers as tiers

    assert not hasattr(tiers, "should_skip_background_full_snapshot")








def _seed_dense_rth_rows(conn: sqlite3.Connection, ticker: str, start: float) -> None:
    ts = start + 60
    while ts <= start + 300 * 60:
        conn.execute("INSERT INTO snapshots VALUES (?, ?)", (ticker, ts))
        conn.execute("INSERT INTO snapshots_1m_normalized VALUES (?, ?)", (ticker, ts))
        conn.execute("INSERT INTO calibration_decision_log VALUES (?, ?)", (ticker, ts))
        ts += 60


def test_june_17_style_flat_1m_candles_normalize(tmp_path: Path):
    from snapshot_normalizer import fetch_rows_for_normalization, resample_to_1m
    from timeframe_config import CANONICAL_TIMEFRAME as CF

    conn = sqlite3.connect(tmp_path / "flat.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE snapshots (
            ticker TEXT, timeframe TEXT, ts_utc REAL, ts_et TEXT, et_hour INT, et_minute INT,
            market_session TEXT, spot REAL, candle_open REAL, candle_high REAL,
            candle_low REAL, candle_close REAL, candle_volume REAL
        );
        """
    )
    spot = 742.545
    for i in range(5):
        ts = 1_781_700_000.0 + i * 60.0
        conn.execute(
            """
            INSERT INTO snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "SPY",
                CF,
                ts,
                "2026-06-17 14:00:00 ET",
                14,
                i,
                "rth",
                spot,
                spot,
                spot,
                spot,
                spot,
                100.0,
            ),
        )
    conn.commit()
    raw, tf = fetch_rows_for_normalization(conn, "SPY")
    norm = resample_to_1m(raw, "SPY", normalized_from_subminute=0)
    assert tf == CF
    assert len(norm) == 5
















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






