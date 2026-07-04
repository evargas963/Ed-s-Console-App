"""Tests for base/guest ticker tiers and RTH observability checker."""
from __future__ import annotations

import contextlib
import datetime
import sqlite3
import time
from pathlib import Path

from money_path_ticker_tiers import (
    BASE_MONEY_PATH_TICKERS,
    TRUST_BASE,
    TRUST_GUEST_UNPROVEN,
    is_base_money_path_ticker,
    is_guest_ticker,
    load_base_ticker_contract,
    should_skip_background_full_snapshot,
    ticker_trust_class,
)
from verification.base_ticker_observability import (
    FAIL_MISSING_NORMALIZED,
    FAIL_SPARSE_SNAPSHOTS,
    PASS_BASE_OBSERVABILITY,
    RAW_CAPTURE_PASS,
    base_ticker_observability_report,
    evaluate_ticker_observability,
    rth_window_utc,
)


def test_base_tickers_are_spy_qqq_iwm():
    assert BASE_MONEY_PATH_TICKERS == ("SPY", "QQQ", "IWM")
    contract = load_base_ticker_contract()
    assert contract["base_money_path_tickers"] == ["SPY", "QQQ", "IWM"]


def test_guest_ticker_not_universal_proof():
    assert is_guest_ticker("NVDA") is True
    assert is_guest_ticker("SPY") is False
    assert ticker_trust_class("PLTR") == TRUST_GUEST_UNPROVEN
    assert ticker_trust_class("SPY") == TRUST_BASE


def test_observability_passes_dense_spy_like_cadence(tmp_path: Path):
    db = tmp_path / "obs.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE snapshots (ticker TEXT, ts_utc REAL);
        CREATE TABLE snapshots_1m_normalized (ticker TEXT, ts_utc REAL);
        CREATE TABLE calibration_decision_log (ticker TEXT, decision_ts_utc REAL);
        """
    )
    day = datetime.date(2026, 6, 16)
    start, end = rth_window_utc(day)
    ts = start + 60
    while ts < end and ts <= start + 300 * 60:
        conn.execute("INSERT INTO snapshots VALUES ('SPY', ?)", (ts,))
        conn.execute("INSERT INTO snapshots_1m_normalized VALUES ('SPY', ?)", (ts,))
        conn.execute("INSERT INTO calibration_decision_log VALUES ('SPY', ?)", (ts,))
        ts += 60
    conn.commit()
    row = evaluate_ticker_observability(conn, "SPY", start, end)
    conn.close()
    assert row["coverage_status"] == PASS_BASE_OBSERVABILITY
    assert row["snapshot_count_rth"] >= 300


def test_observability_fails_sparse_qqq_like(tmp_path: Path):
    db = tmp_path / "sparse.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE snapshots (ticker TEXT, ts_utc REAL);
        CREATE TABLE snapshots_1m_normalized (ticker TEXT, ts_utc REAL);
        CREATE TABLE calibration_decision_log (ticker TEXT, decision_ts_utc REAL);
        """
    )
    day = datetime.date(2026, 6, 16)
    start, end = rth_window_utc(day)
    for i in range(19):
        ts = start + i * 1287
        conn.execute("INSERT INTO snapshots VALUES ('QQQ', ?)", (ts,))
        conn.execute("INSERT INTO snapshots_1m_normalized VALUES ('QQQ', ?)", (ts,))
        conn.execute("INSERT INTO calibration_decision_log VALUES ('QQQ', ?)", (ts,))
    conn.commit()
    row = evaluate_ticker_observability(conn, "QQQ", start, end)
    conn.close()
    assert row["coverage_status"] == FAIL_SPARSE_SNAPSHOTS


def test_replay_probe_imports_base_tier_helpers():
    from tools.replay_money_path_probe import run_probe  # noqa: F401

    assert is_base_money_path_ticker("IWM")


def test_base_tickers_never_skipped_for_panel_auto():
    """Base anchors must not be downgraded to confluence-only guest capture."""
    panel = frozenset({"SPY", "QQQ", "IWM", "WMT"})
    for anchor in BASE_MONEY_PATH_TICKERS:
        assert should_skip_background_full_snapshot(anchor, panel) is False
    assert should_skip_background_full_snapshot("WMT", panel) is True
    assert should_skip_background_full_snapshot("NVDA", frozenset()) is False


def test_filter_tickers_for_background_logging_keeps_base_anchors(tmp_path: Path):
    from db import EdDB
    from scheduler_user_tickers import filter_tickers_for_background_logging

    db = EdDB(tmp_path / "filter.db")
    now = time.time()
    db.logging_universe_sync_core(list(BASE_MONEY_PATH_TICKERS) + ["NVDA"], now)
    db.logging_universe_sync_panel_auto(["QQQ", "WMT"], now)
    tickers = filter_tickers_for_background_logging(
        list(BASE_MONEY_PATH_TICKERS) + ["NVDA", "WMT"],
        str(db.db_path),
    )
    for anchor in BASE_MONEY_PATH_TICKERS:
        assert anchor in tickers
    assert "WMT" not in tickers
    assert "NVDA" in tickers


def test_base_money_path_logger_tickers_match_anchors():
    import server as srv

    assert srv.base_money_path_logger_tickers() == BASE_MONEY_PATH_TICKERS
    assert len(srv.base_money_path_logger_tickers()) == 3


def test_start_logger_launches_base_money_path_thread(monkeypatch):
    import threading

    import server as srv

    started: list[str] = []

    class _FakeThread:
        def __init__(self, target=None, daemon=None, name=None):
            self._target = target
            self.name = name

        def start(self):
            started.append(self.name or "")

    monkeypatch.setattr(srv, "_hydrate_logger_tickers_from_db", lambda: None)
    monkeypatch.setattr(threading, "Thread", _FakeThread)
    monkeypatch.setattr(srv, "_logger_running", False)
    monkeypatch.setattr(srv, "_base_money_path_logger_running", False)
    try:
        srv.start_logger()
        assert "ed-ticker-logger" in started
        assert "ed-base-money-path-logger" in started
    finally:
        srv._logger_running = False
        srv._base_money_path_logger_running = False


def _seed_dense_rth_rows(conn: sqlite3.Connection, ticker: str, start: float) -> None:
    ts = start + 60
    while ts <= start + 300 * 60:
        conn.execute("INSERT INTO snapshots VALUES (?, ?)", (ticker, ts))
        conn.execute("INSERT INTO snapshots_1m_normalized VALUES (?, ?)", (ticker, ts))
        conn.execute("INSERT INTO calibration_decision_log VALUES (?, ?)", (ticker, ts))
        ts += 60


def test_observability_universe_ready_requires_all_three_base(tmp_path: Path):
    db = tmp_path / "universe.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE snapshots (ticker TEXT, ts_utc REAL);
        CREATE TABLE snapshots_1m_normalized (ticker TEXT, ts_utc REAL);
        CREATE TABLE calibration_decision_log (ticker TEXT, decision_ts_utc REAL);
        """
    )
    day = datetime.date(2026, 6, 16)
    start, _end = rth_window_utc(day)
    for anchor in BASE_MONEY_PATH_TICKERS:
        _seed_dense_rth_rows(conn, anchor, start)
    conn.commit()
    conn.close()

    report = base_ticker_observability_report(
        day=day,
        tickers=list(BASE_MONEY_PATH_TICKERS),
        db_path=db,
    )
    assert report["meta"]["base_universe_ready"] is True
    assert report["summary"]["pass_count"] == 3
    assert report["summary"]["fail_count"] == 0
    for row in report["tickers"]:
        assert row["coverage_status"] == PASS_BASE_OBSERVABILITY


def test_observability_universe_not_ready_when_one_base_sparse(tmp_path: Path):
    db = tmp_path / "partial.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE snapshots (ticker TEXT, ts_utc REAL);
        CREATE TABLE snapshots_1m_normalized (ticker TEXT, ts_utc REAL);
        CREATE TABLE calibration_decision_log (ticker TEXT, decision_ts_utc REAL);
        """
    )
    day = datetime.date(2026, 6, 16)
    start, end = rth_window_utc(day)
    _seed_dense_rth_rows(conn, "SPY", start)
    for i in range(19):
        ts = start + i * 1287
        conn.execute("INSERT INTO snapshots VALUES ('QQQ', ?)", (ts,))
        conn.execute("INSERT INTO snapshots_1m_normalized VALUES ('QQQ', ?)", (ts,))
        conn.execute("INSERT INTO calibration_decision_log VALUES ('QQQ', ?)", (ts,))
    _seed_dense_rth_rows(conn, "IWM", start)
    conn.commit()
    conn.close()

    report = base_ticker_observability_report(
        day=day,
        tickers=list(BASE_MONEY_PATH_TICKERS),
        db_path=db,
    )
    assert report["meta"]["base_universe_ready"] is False
    by_t = {r["ticker"]: r for r in report["tickers"]}
    assert by_t["SPY"]["coverage_status"] == PASS_BASE_OBSERVABILITY
    assert by_t["QQQ"]["coverage_status"] == FAIL_SPARSE_SNAPSHOTS
    assert by_t["IWM"]["coverage_status"] == PASS_BASE_OBSERVABILITY


def test_check_base_ticker_observability_cli_passes_on_dense_fixture(tmp_path: Path):
    """CLI gate exit 0 when all three base tickers meet RTH thresholds (deterministic fixture)."""
    import subprocess
    import sys

    db = tmp_path / "cli_pass.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE snapshots (ticker TEXT, ts_utc REAL);
        CREATE TABLE snapshots_1m_normalized (ticker TEXT, ts_utc REAL);
        CREATE TABLE calibration_decision_log (ticker TEXT, decision_ts_utc REAL);
        """
    )
    day = datetime.date(2026, 6, 17)
    start, _end = rth_window_utc(day)
    for anchor in BASE_MONEY_PATH_TICKERS:
        _seed_dense_rth_rows(conn, anchor, start)
    conn.commit()
    conn.close()

    repo = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [
            sys.executable,
            str(repo / "tools" / "check_base_ticker_observability.py"),
            "--date",
            day.isoformat(),
            "--tickers",
            "SPY",
            "QQQ",
            "IWM",
            "--db",
            str(db),
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "universe_ready=True" in proc.stdout
    assert "PASS_BASE_OBSERVABILITY" in proc.stdout


def test_observability_dense_raw_zero_normalized_fails_with_raw_capture_pass(tmp_path: Path):
    db = tmp_path / "raw_only.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE snapshots (ticker TEXT, ts_utc REAL);
        CREATE TABLE snapshots_1m_normalized (ticker TEXT, ts_utc REAL);
        CREATE TABLE calibration_decision_log (ticker TEXT, decision_ts_utc REAL);
        """
    )
    day = datetime.date(2026, 6, 17)
    start, end = rth_window_utc(day)
    ts = start + 60
    while ts < end and ts <= start + 300 * 60:
        conn.execute("INSERT INTO snapshots VALUES ('SPY', ?)", (ts,))
        conn.execute("INSERT INTO calibration_decision_log VALUES ('SPY', ?)", (ts,))
        ts += 60
    conn.commit()
    row = evaluate_ticker_observability(conn, "SPY", start, end)
    conn.close()
    assert row["coverage_status"] == FAIL_MISSING_NORMALIZED
    assert row["raw_capture_pass"] is True
    assert row["normalized_pass"] is False
    assert row["raw_only_status"] == RAW_CAPTURE_PASS


def test_canonical_1m_snapshots_materialize_to_normalized(tmp_path: Path):
    from db import EdDB
    from normalized_training_sync import materialize_base_money_path_tickers
    from snapshot_normalizer import load_normalized_rows
    from timeframe_config import CANONICAL_TIMEFRAME as CF

    db = EdDB(tmp_path / "mat.db")
    day = datetime.date(2026, 6, 17)
    start, _end = rth_window_utc(day)
    ts = start + 60
    rows = 0
    while ts <= start + 300 * 60:
        with db._connect() as conn:
            conn.execute(
                """
                INSERT INTO snapshots (
                    ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                    candle_open, candle_high, candle_low, candle_close, candle_volume
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "SPY",
                    CF,
                    ts,
                    "2026-06-17 10:00:00 ET",
                    10,
                    0,
                    "rth",
                    500.0 + rows * 0.01,
                    500.0 + rows * 0.01,
                    500.1 + rows * 0.01,
                    499.9 + rows * 0.01,
                    500.0 + rows * 0.01,
                    1000.0,
                ),
            )
            conn.commit()
        rows += 1
        ts += 60

    mat = materialize_base_money_path_tickers(db.db_path)
    assert not mat.get("errors"), mat.get("errors")
    assert mat["by_ticker"]["SPY"]["normalized"] == rows
    norm = load_normalized_rows(Path(db.db_path), ticker="SPY")
    assert len(norm) == rows
    assert all(r["timeframe"] == "1m" for r in norm)


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


def test_base_materialize_does_not_touch_guest_ticker(tmp_path: Path):
    from db import EdDB
    from normalized_training_sync import materialize_base_money_path_tickers
    from timeframe_config import CANONICAL_TIMEFRAME as CF

    db = EdDB(tmp_path / "guest.db")
    ts = 1_781_700_000.0
    with db._connect() as conn:
        for ticker in ("SPY", "NVDA"):
            conn.execute(
                """
                INSERT INTO snapshots (
                    ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                    candle_open, candle_high, candle_low, candle_close, candle_volume
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker,
                    CF,
                    ts,
                    "2026-06-17 14:00:00 ET",
                    14,
                    0,
                    "rth",
                    100.0,
                    100.0,
                    101.0,
                    99.0,
                    100.0,
                    1.0,
                ),
            )
        conn.execute(
            "INSERT INTO snapshots_1m_normalized (ticker, timeframe, ts_utc, spot) VALUES ('NVDA', ?, ?, 1.0)",
            (CF, ts + 9999.0),
        )
        conn.commit()

    mat = materialize_base_money_path_tickers(db.db_path)
    assert not mat.get("errors")
    assert "SPY" in mat["by_ticker"]
    assert "NVDA" not in mat.get("by_ticker", {})
    with db._connect() as conn:
        nvda_norm = conn.execute(
            "SELECT COUNT(*) FROM snapshots_1m_normalized WHERE ticker='NVDA'"
        ).fetchone()[0]
        spy_norm = conn.execute(
            "SELECT COUNT(*) FROM snapshots_1m_normalized WHERE ticker='SPY'"
        ).fetchone()[0]
    assert nvda_norm == 1
    assert spy_norm == 1


def test_schedule_debounced_base_money_path_refresh_materializes(monkeypatch, tmp_path: Path):
    from normalized_training_sync import schedule_debounced_base_money_path_normalized_refresh

    fired: list[Path] = []

    class _ImmediateTimer:
        def __init__(self, _delay, fn):
            self._fn = fn

        def start(self):
            self._fn()

        def cancel(self):
            pass

        daemon = True

    monkeypatch.setattr("normalized_training_sync.threading.Timer", _ImmediateTimer)
    monkeypatch.setattr(
        "normalized_training_sync.materialize_base_money_path_tickers",
        lambda p: fired.append(Path(p)) or {"errors": [], "normalized_rows": 1, "by_ticker": {}},
    )
    schedule_debounced_base_money_path_normalized_refresh(tmp_path / "x.db")
    assert fired == [tmp_path / "x.db"]


def test_base_normalize_debounce_default_below_capture_interval():
    from normalized_training_sync import base_money_path_normalize_debounce_sec

    delay = base_money_path_normalize_debounce_sec(capture_interval_sec=60.0)
    assert delay < 60.0
    assert delay >= 15.0


def test_base_normalize_schedule_does_not_starve_when_cycles_reschedule(monkeypatch, tmp_path: Path):
    """Repeated capture cycles must not cancel a pending debounce timer (PR8 norm freeze)."""
    import normalized_training_sync as nts

    fired: list[int] = []
    pending: list[float] = []

    class _RecordingTimer:
        def __init__(self, delay, fn):
            pending.append(float(delay))
            self._fn = fn
            self._delay = float(delay)

        def start(self):
            pass

        def cancel(self):
            pass

        daemon = True

    def _fake_materialize(_path):
        fired.append(1)
        return {"errors": [], "normalized_rows": 1, "by_ticker": {}}

    monkeypatch.setattr(nts.threading, "Timer", _RecordingTimer)
    monkeypatch.setattr(nts, "materialize_base_money_path_tickers", _fake_materialize)
    monkeypatch.setattr(
        nts,
        "cross_process_materialize_lock",
        lambda *_a, **_k: contextlib.nullcontext(),
    )

    nts._base_debounce_timer = None
    nts.schedule_debounced_base_money_path_normalized_refresh(tmp_path / "a.db", delay_s=0.01)
    assert len(pending) == 1
    first_timer = nts._base_debounce_timer
    assert first_timer is not None

    # Second schedule while timer pending — must NOT replace timer (old bug cancelled it).
    nts.schedule_debounced_base_money_path_normalized_refresh(tmp_path / "a.db", delay_s=0.01)
    assert len(pending) == 1
    assert nts._base_debounce_timer is first_timer

    first_timer._fn()
    assert len(fired) == 1


def test_resolve_logger_source_from_update_source():
    from base_money_path_capture import (
        LOGGER_SOURCE_BACKGROUND,
        LOGGER_SOURCE_BASE_MONEY_PATH,
        LOGGER_SOURCE_UI_REST,
        LOGGER_SOURCE_UI_SSE,
        resolve_logger_source_from_update_source,
    )

    assert resolve_logger_source_from_update_source("sse_loop") == LOGGER_SOURCE_UI_SSE
    assert resolve_logger_source_from_update_source("rest_analytics") == LOGGER_SOURCE_UI_REST
    assert resolve_logger_source_from_update_source("base_money_path") == LOGGER_SOURCE_BASE_MONEY_PATH
    assert resolve_logger_source_from_update_source("background_logger") == LOGGER_SOURCE_BACKGROUND
    assert resolve_logger_source_from_update_source(None) is None


def test_build_lightweight_snapshot_row_sets_logger_source():
    import datetime

    from base_money_path_capture import (
        LOGGER_SOURCE_BASE_MONEY_PATH,
        build_lightweight_snapshot_row_from_quote,
    )

    et = datetime.datetime(2026, 6, 18, 10, 15, tzinfo=datetime.timezone(datetime.timedelta(hours=-4)))
    row = build_lightweight_snapshot_row_from_quote(
        "QQQ",
        {"spot_f": 450.25, "bid": 450.2, "ask": 450.3},
        ts_utc=1_781_800_000.0,
        now_et=et,
    )
    assert row.ticker == "QQQ"
    assert row.logger_source == LOGGER_SOURCE_BASE_MONEY_PATH
    assert row.spot == 450.25


def test_run_base_money_path_capture_cycle_attempts_all_three_concurrently():
    import time

    from base_money_path_capture import BaseCaptureAttempt, run_base_money_path_capture_cycle

    attempted: list[str] = []

    def _capture(ticker: str) -> BaseCaptureAttempt:
        attempted.append(ticker)
        if ticker == "SPY":
            time.sleep(0.25)
        return BaseCaptureAttempt(ticker, "ok:insert", 0.05)

    results = run_base_money_path_capture_cycle(
        ("SPY", "QQQ", "IWM"),
        capture_one=_capture,
        max_workers=3,
        per_ticker_timeout_sec=5.0,
    )
    assert len(results) == 3
    assert {r.ticker for r in results} == {"SPY", "QQQ", "IWM"}
    assert set(attempted) == {"SPY", "QQQ", "IWM"}


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


def test_observability_reports_base_money_path_counts(tmp_path: Path):
    db = tmp_path / "base_src.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE snapshots (ticker TEXT, ts_utc REAL, logger_source TEXT);
        CREATE TABLE snapshots_1m_normalized (ticker TEXT, ts_utc REAL);
        CREATE TABLE calibration_decision_log (ticker TEXT, decision_ts_utc REAL);
        """
    )
    day = datetime.date(2026, 6, 18)
    start, end = rth_window_utc(day)
    ts = start + 60
    while ts <= start + 120 * 60:
        for t in BASE_MONEY_PATH_TICKERS:
            conn.execute(
                "INSERT INTO snapshots VALUES (?, ?, 'base_money_path')",
                (t, ts),
            )
            conn.execute("INSERT INTO snapshots_1m_normalized VALUES (?, ?)", (t, ts))
            conn.execute("INSERT INTO calibration_decision_log VALUES (?, ?)", (t, ts))
        ts += 60
    conn.commit()
    conn.close()

    report = base_ticker_observability_report(
        day=day,
        tickers=list(BASE_MONEY_PATH_TICKERS),
        db_path=db,
    )
    assert report["meta"]["base_capture_parity"]["parity_ok"] is True
    for row in report["tickers"]:
        assert row["base_money_path_snapshot_count_rth"] == row["snapshot_count_rth"]


# ── LIVE_OPERATOR_MODE_RESET_V1 Step 1 — RTH viewer gate on the background logger ──


def _fixed_et(year: int, month: int, day: int, hour: int, minute: int):
    """Naive stand-in for time_et.now_et — the gate only reads hour/minute/weekday."""
    return datetime.datetime(year, month, day, hour, minute)


def test_live_operator_mode_requires_rth_and_viewer(monkeypatch):
    import server as srv

    tier_c_viewer = {("SPY", None): 1}

    # Tuesday 2026-06-16 10:30 ET (RTH) + Tier C SSE subscriber → active.
    monkeypatch.setattr(srv, "now_et", lambda: _fixed_et(2026, 6, 16, 10, 30))
    monkeypatch.setattr(srv, "_sse_subscribers", dict(tier_c_viewer))
    monkeypatch.setattr(srv, "_l1_light_sse_clients", [])
    assert srv._live_operator_mode_active() is True

    # RTH clock but no viewer transport connected → inactive.
    monkeypatch.setattr(srv, "_sse_subscribers", {})
    assert srv._live_operator_mode_active() is False

    # L1 light SSE client alone (Tier C stream down/reconnecting) → active.
    monkeypatch.setattr(srv, "_l1_light_sse_clients", [(object(), ("SPY", "__auto__"))])
    assert srv._live_operator_mode_active() is True

    # Viewer connected but pre-market (08:00 ET) → inactive.
    monkeypatch.setattr(srv, "_sse_subscribers", dict(tier_c_viewer))
    monkeypatch.setattr(srv, "now_et", lambda: _fixed_et(2026, 6, 16, 8, 0))
    assert srv._live_operator_mode_active() is False

    # Viewer connected at RTH wall-clock on Saturday 2026-06-20 → inactive.
    monkeypatch.setattr(srv, "now_et", lambda: _fixed_et(2026, 6, 20, 10, 30))
    assert srv._live_operator_mode_active() is False

    # 16:00 ET close boundary is outside RTH → inactive.
    monkeypatch.setattr(srv, "now_et", lambda: _fixed_et(2026, 6, 16, 16, 0))
    assert srv._live_operator_mode_active() is False


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


def test_logger_skips_non_trio_full_fetch_in_live_operator_mode(monkeypatch):
    status, calls = _run_logger_fetch(monkeypatch, "NVDA", live_mode=True)
    assert status == "skipped:live_operator_mode"
    assert calls == []


def test_logger_trio_full_fetch_unchanged_in_live_operator_mode(monkeypatch):
    for anchor in BASE_MONEY_PATH_TICKERS:
        status, calls = _run_logger_fetch(monkeypatch, anchor, live_mode=True)
        assert status == "ok:fetch"
        assert calls == [(anchor, True)]


def test_logger_full_fetch_when_no_live_operator_mode(monkeypatch):
    status, calls = _run_logger_fetch(monkeypatch, "NVDA", live_mode=False)
    assert status == "ok:fetch"
    assert calls == [("NVDA", True)]


# ── LIVE_OPERATOR_MODE_RESET_V1 Step 3 — live-path DB write gating ──


def test_step3_bars_and_outcomes_ride_snapshot_throttle():
    """upsert_1m_bars + fill_outcomes submit must sit inside the _do_insert throttle."""
    import inspect

    import server as srv

    src = inspect.getsource(srv._fetch_state)
    marker = src.find("bars persist + outcome backfill ride")
    assert marker != -1, "Step 3 throttle block missing from _fetch_state"
    block = src[marker : marker + 1400]
    assert "if _do_insert:" in block
    guard = block[block.find("if _do_insert:") :]
    assert "upsert_1m_bars" in guard
    assert "_get_db_fill_outcomes_executor().submit" in guard
    # No unthrottled duplicate CALL SITES outside the guard ("(" excludes the
    # warning-log format string "upsert_1m_bars %s" on the except path).
    assert src.count("upsert_1m_bars(") == 1
    assert src.count("_get_db_fill_outcomes_executor().submit") == 1


def test_step3_base_normalized_refresh_skipped_in_live_operator_mode(monkeypatch):
    import server as srv

    calls: list[str] = []
    import normalized_training_sync as nts

    monkeypatch.setattr(
        nts,
        "schedule_debounced_base_money_path_normalized_refresh",
        lambda p, logger=None: calls.append(str(p)),
    )

    monkeypatch.setattr(srv, "_live_operator_mode_active", lambda: True)
    srv._maybe_schedule_base_normalized_refresh()
    assert calls == [], "live operator mode must skip base normalized scheduling"

    monkeypatch.setattr(srv, "_live_operator_mode_active", lambda: False)
    srv._maybe_schedule_base_normalized_refresh()
    assert len(calls) == 1, "non-live cycle must schedule the debounced refresh as before"


def test_console_ml_scheduler_is_opt_in():
    """Console usability slice 2026-07-03: the operator console must NOT self-start the
    nightly ML scheduler — the unconditional start made every open console an ungoverned
    models/active writer (operator ruling: BLESS_RUN=NO, MODELS_ACTIVE_AS_OUTPUT_LANE=
    NOT_APPROVED), spawned multiprocess workers that outlive console crashes, and
    contended with the live DB. Training hosts opt in via ED_ENABLE_BACKGROUND_SCHEDULER=1."""
    from pathlib import Path as _P

    src = (_P(__file__).resolve().parent.parent / "server.py").read_text(
        encoding="utf-8", errors="replace"
    )
    gate = src.find('os.environ.get("ED_ENABLE_BACKGROUND_SCHEDULER", "0")')
    assert gate != -1, "scheduler opt-in gate missing (default must be OFF)"
    start = src.find("start_background_scheduler()")
    assert start != -1
    assert gate < start, "the env gate must guard the scheduler start call"
    assert src.count("start_background_scheduler()") == 1, (
        "no unconditional scheduler start path may remain"
    )
