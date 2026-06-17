"""
Production-path proof for calibration_decision_log (same stack as server → market_state → compute_signals).

Uses a temp SQLite DB, ED_CALIBRATION_LOG=1, and real compute_signals (no alternate code path).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

import db as db_mod
from calibration.schema import ensure_calibration_schema
from calibration.validate_logging_e2e import _inp
from db import EdDB, configure_sqlite_connection
from instrument_identity import ticker_storage_key
from calibration.v2_live_logging import append_live_v2_calibration_decision
from signals import compute_signals
from v2_decision import build_module_a_a1_decision

_SPY_KEY = ticker_storage_key("SPY")


def _v2_for_output(out, ticker: str = "SPY") -> dict:
    canonical = out.canonical_forecast
    prob = max(
        float(canonical.probability_up),
        float(canonical.probability_down),
        float(canonical.probability_flat),
    )
    return build_module_a_a1_decision(
        {
            "ticker": ticker,
            "fusion_available": True,
            "fusion_dominant_direction": canonical.direction,
            "fusion_dominant_prob": prob,
            "execution_mode": getattr(out.call, "execution_mode", None),
        }
    )


def _compute_then_log(inp, *, db_path: Path, edb: EdDB):
    out = compute_signals(inp, db=edb)
    append_live_v2_calibration_decision(
        db_path=db_path,
        calibration_payload=out.calibration_payload,
        v2_decision=_v2_for_output(out, getattr(inp, "ticker", "SPY")),
    )
    return out


def _fake_run_unified_stack_ml_once(
    snap,
    ticker,
    db,
    direction_hint: str = "wait",
    *,
    inference_snapshot_v1=None,
    **kwargs: object,
):
    """Deterministic parallel-stack output without on-disk models or snapshot history (CI-safe)."""
    from ml_predict import PARALLEL_STACK_SCHEMA_VERSION, stack_probs_bundle_key
    from features.parallel_stack_schema import build_unified_stack_layer_output

    probs = {"up": 0.34, "down": 0.33, "flat": 0.33}

    def _fusion_block():
        return {
            "available": True,
            "prob_up": 0.34,
            "prob_down": 0.33,
            "prob_flat": 0.33,
            "dominant_class": "up",
            "confidence_label": "low",
            "continuation_support": 0.34,
            "reversal_support": 0.33,
        }

    fusion_pack = {"xgb": _fusion_block(), "lstm": _fusion_block(), "transformer": _fusion_block()}

    def _mo():
        r = build_unified_stack_layer_output(probs=probs, approved=True)
        r["up"] = r["prob_up"]
        r["down"] = r["prob_down"]
        r["flat"] = r["prob_flat"]
        r["confidence"] = r["confidence_score"]
        return r

    model_outputs = {"xgb": _mo(), "lstm": _mo(), "transformer": _mo()}
    return {
        "fusion": fusion_pack,
        "model_outputs": model_outputs,
        stack_probs_bundle_key(): probs,
        "parallel_runtime": True,
        "stack_schema_version": PARALLEL_STACK_SCHEMA_VERSION,
    }


@pytest.fixture
def stub_parallel_stack_for_calibration_proofs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real `compute_signals` path; stub only `run_unified_stack_ml_once` so empty DB + no artifacts still complete."""
    monkeypatch.setenv("ED_XGB_STRICT_ACTIVE_ONLY", "0")
    monkeypatch.setattr("ml_predict.run_unified_stack_ml_once", _fake_run_unified_stack_ml_once)


@pytest.fixture
def calib_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated DB; patch db.DB_PATH so calibration.writer targets this file."""
    p = tmp_path / "calib_prod.db"
    p.touch()
    monkeypatch.setattr(db_mod, "DB_PATH", p)
    monkeypatch.setenv("ED_CALIBRATION_LOG", "1")
    conn = sqlite3.connect(str(p))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    conn.close()
    return p


def test_single_phase_orchestrator_writes_one_calibration_row_per_successful_decision(
    calib_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_parallel_stack_for_calibration_proofs: None,
) -> None:
    """Event parity: N successful server-orchestrated decisions → N new calibration rows."""
    monkeypatch.setenv("ED_CALIBRATION_LOG", "1")
    edb = EdDB(calib_db)
    conn = sqlite3.connect(str(calib_db))
    before = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    conn.close()

    n = 5
    ts_list: list[float] = []
    base = time.time()
    for i in range(n):
        rts = base + float(i) * 0.05
        ts_list.append(rts)
        out = _compute_then_log(_inp(refresh_ts_utc=rts), db_path=calib_db, edb=edb)
        assert out.call is not None

    conn = sqlite3.connect(str(calib_db))
    after = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    rows = conn.execute(
        "SELECT ticker, decision_ts_utc FROM calibration_decision_log ORDER BY id"
    ).fetchall()
    conn.close()

    assert after - before == n
    assert len(rows) >= after
    # Last n rows should match our tickers and timestamps (strict refresh_ts alignment)
    tail = rows[-n:]
    for i, rts in enumerate(ts_list):
        assert tail[i][0] == _SPY_KEY
        assert abs(float(tail[i][1]) - rts) < 1e-6


def test_compute_signals_returns_calibration_payload_without_writing(
    calib_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_parallel_stack_for_calibration_proofs: None,
) -> None:
    """Lifecycle boundary: compute_signals prepares data; server owns the calibration INSERT."""
    monkeypatch.setenv("ED_CALIBRATION_LOG", "1")
    edb = EdDB(calib_db)

    out = compute_signals(_inp(refresh_ts_utc=1_700_000_001.0), db=edb)

    conn = sqlite3.connect(str(calib_db))
    n = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    conn.close()

    assert n == 0
    assert out.calibration_payload is not None


def test_decision_ts_utc_matches_refresh_ts_utc(
    calib_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_parallel_stack_for_calibration_proofs: None,
) -> None:
    """Timestamp authority: calibration decision_ts_utc == SignalInput.refresh_ts_utc."""
    monkeypatch.setenv("ED_CALIBRATION_LOG", "1")
    edb = EdDB(calib_db)
    rts = 1_700_000_000.0 + 123.456
    _compute_then_log(_inp(refresh_ts_utc=rts), db_path=calib_db, edb=edb)

    conn = sqlite3.connect(str(calib_db))
    d = conn.execute(
        "SELECT decision_ts_utc, calibration_trust FROM calibration_decision_log WHERE ticker=? ORDER BY id DESC LIMIT 1",
        (_SPY_KEY,),
    ).fetchone()
    conn.close()
    assert d is not None
    assert abs(float(d[0]) - rts) < 1e-9
    assert d[1] == "trusted"


def test_no_duplicate_ticker_decision_ts_pairs_for_distinct_refreshes(
    calib_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_parallel_stack_for_calibration_proofs: None,
) -> None:
    """Duplicate check: unique refresh_ts per call → at most one row per (ticker, decision_ts_utc)."""
    monkeypatch.setenv("ED_CALIBRATION_LOG", "1")
    edb = EdDB(calib_db)
    base = time.time()
    for i in range(8):
        _compute_then_log(_inp(refresh_ts_utc=base + i * 0.1), db_path=calib_db, edb=edb)

    conn = sqlite3.connect(str(calib_db))
    dup = conn.execute(
        """
        SELECT ticker, decision_ts_utc, COUNT(*) AS c
        FROM calibration_decision_log
        GROUP BY ticker, decision_ts_utc
        HAVING c > 1
        """
    ).fetchall()
    conn.close()
    assert dup == []


def test_rapid_multithreaded_writes_no_skipped_inserts(
    calib_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_parallel_stack_for_calibration_proofs: None,
) -> None:
    """Load / contention: concurrent compute_signals on different tickers — all rows present, no dup keys."""
    monkeypatch.setenv("ED_CALIBRATION_LOG", "1")
    edb = EdDB(calib_db)
    conn = sqlite3.connect(str(calib_db))
    before = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    conn.close()

    tickers = ["SPY", "QQQ", "IWM", "DIA"]
    base = time.time()
    errors: list[BaseException] = []

    def run_one(idx: int) -> None:
        try:
            tkr = tickers[idx % len(tickers)]
            inp = replace(_inp(refresh_ts_utc=base + idx * 0.02), ticker=tkr)
            _compute_then_log(inp, db_path=calib_db, edb=edb)
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=run_one, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120.0)

    assert errors == []

    conn = sqlite3.connect(str(calib_db))
    after = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    dup = conn.execute(
        """
        SELECT ticker, decision_ts_utc, COUNT(*) AS c
        FROM calibration_decision_log
        GROUP BY ticker, decision_ts_utc
        HAVING c > 1
        """
    ).fetchall()
    conn.close()

    assert after - before == 12
    assert dup == []


def test_repeated_identical_refresh_ts_inserts_at_most_one_row(
    calib_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_parallel_stack_for_calibration_proofs: None,
) -> None:
    """UNIQUE + ON CONFLICT DO NOTHING: two identical decision keys → one row in DB."""
    monkeypatch.setenv("ED_CALIBRATION_LOG", "1")
    edb = EdDB(calib_db)
    conn = sqlite3.connect(str(calib_db))
    before = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    conn.close()

    rts = 1_701_234_567.89
    _compute_then_log(_inp(refresh_ts_utc=rts), db_path=calib_db, edb=edb)
    _compute_then_log(_inp(refresh_ts_utc=rts), db_path=calib_db, edb=edb)

    conn = sqlite3.connect(str(calib_db))
    after = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    n = conn.execute(
        "SELECT COUNT(*) FROM calibration_decision_log WHERE ticker=? AND decision_ts_utc=?",
        (_SPY_KEY, rts),
    ).fetchone()[0]
    conn.close()

    assert after - before == 1
    assert n == 1


def test_concurrent_identical_decision_key_single_row(
    calib_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_parallel_stack_for_calibration_proofs: None,
) -> None:
    """Threads racing on the same (ticker, decision_ts_utc) cannot insert duplicate rows."""
    monkeypatch.setenv("ED_CALIBRATION_LOG", "1")
    edb = EdDB(calib_db)
    conn = sqlite3.connect(str(calib_db))
    before = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    conn.close()

    shared_ts = 1_702_000_000.0 + 0.001
    errors: list[BaseException] = []

    def run_same() -> None:
        try:
            _compute_then_log(_inp(refresh_ts_utc=shared_ts), db_path=calib_db, edb=edb)
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=run_same) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120.0)

    assert errors == []

    conn = sqlite3.connect(str(calib_db))
    after = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    n = conn.execute(
        "SELECT COUNT(*) FROM calibration_decision_log WHERE ticker=? AND decision_ts_utc=?",
        (_SPY_KEY, shared_ts),
    ).fetchone()[0]
    dup = conn.execute(
        """
        SELECT ticker, decision_ts_utc, COUNT(*) AS c
        FROM calibration_decision_log
        GROUP BY ticker, decision_ts_utc
        HAVING c > 1
        """
    ).fetchall()
    conn.close()

    assert after - before == 1
    assert n == 1
    assert dup == []


# ───────────────────── Pass 3 — calibration rate health (forward-only) ─────────────────────


def _seed_calibration_health_fixture(
    db_path: Path,
    *,
    rows_last_24h: int,
    rows_prior_24h: int,
    enrolled_tickers: int,
    now_ts: float,
) -> None:
    """Populate calibration_decision_log + logging_universe for deterministic counter tests."""
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    try:
        ensure_calibration_schema(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS logging_universe ("
            "ticker TEXT PRIMARY KEY, active INTEGER NOT NULL DEFAULT 1)"
        )
        conn.executemany(
            "INSERT OR REPLACE INTO logging_universe (ticker, active) VALUES (?, 1)",
            [(f"FIX{i:02d}",) for i in range(enrolled_tickers)],
        )
        lo_24 = now_ts - 86400.0
        lo_48 = now_ts - 2 * 86400.0
        # Distribute rows across the windows so the COUNT filter matches.
        for i in range(rows_last_24h):
            conn.execute(
                "INSERT INTO calibration_decision_log "
                "(ticker, canonical_timeframe, decision_ts_utc) "
                "VALUES (?, '1m', ?)",
                (f"FIX{i % max(1, enrolled_tickers):02d}", lo_24 + 1.0 + i * 0.1),
            )
        for i in range(rows_prior_24h):
            conn.execute(
                "INSERT INTO calibration_decision_log "
                "(ticker, canonical_timeframe, decision_ts_utc) "
                "VALUES (?, '1m', ?)",
                (f"FIX{i % max(1, enrolled_tickers):02d}", lo_48 + 1.0 + i * 0.1),
            )
        conn.commit()
    finally:
        conn.close()


def test_calibration_rate_health_warn_fires_when_below_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env on + rate < 0.5 * expected => warn=True (the silent-gap regression alarm)."""
    from calibration.writer import (
        EXPECTED_DECISIONS_PER_MINUTE_PER_TICKER,
        SESSION_MINUTES_RTH,
        CALIBRATION_RATE_WARN_RATIO,
        compute_calibration_rate_health,
    )

    monkeypatch.setenv("ED_CALIBRATION_LOG", "1")
    now_ts = 1_800_000_000.0
    enrolled = 14
    expected = enrolled * SESSION_MINUTES_RTH * EXPECTED_DECISIONS_PER_MINUTE_PER_TICKER
    # Seed with 0.2x expected — clearly below 0.5x threshold.
    below = max(1, int(expected * 0.2))
    db_path = tmp_path / "cal_health_warn.db"
    _seed_calibration_health_fixture(
        db_path,
        rows_last_24h=below,
        rows_prior_24h=int(expected * 0.95),  # prior 24h was healthy
        enrolled_tickers=enrolled,
        now_ts=now_ts,
    )

    health = compute_calibration_rate_health(db_path, now_ts=now_ts)
    assert health["table_present"] is True
    assert health["env_enabled"] is True
    assert health["enrolled_tickers"] == enrolled
    assert health["expected_per_24h"] == pytest.approx(expected)
    assert health["last_24h_count"] == below
    assert health["ratio"] is not None and health["ratio"] < CALIBRATION_RATE_WARN_RATIO
    assert health["warn"] is True


def test_calibration_rate_health_warn_clears_when_above_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env on + rate >= 0.5 * expected => warn=False (healthy fixture, no false positive)."""
    from calibration.writer import (
        EXPECTED_DECISIONS_PER_MINUTE_PER_TICKER,
        SESSION_MINUTES_RTH,
        CALIBRATION_RATE_WARN_RATIO,
        compute_calibration_rate_health,
    )

    monkeypatch.setenv("ED_CALIBRATION_LOG", "1")
    now_ts = 1_800_000_000.0
    enrolled = 14
    expected = enrolled * SESSION_MINUTES_RTH * EXPECTED_DECISIONS_PER_MINUTE_PER_TICKER
    above = int(expected * 0.95)
    db_path = tmp_path / "cal_health_ok.db"
    _seed_calibration_health_fixture(
        db_path,
        rows_last_24h=above,
        rows_prior_24h=above,
        enrolled_tickers=enrolled,
        now_ts=now_ts,
    )

    health = compute_calibration_rate_health(db_path, now_ts=now_ts)
    assert health["ratio"] is not None and health["ratio"] >= CALIBRATION_RATE_WARN_RATIO
    assert health["warn"] is False


def test_calibration_rate_health_warn_off_when_env_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env off => warn=False even when rate is zero. Boot WARN @ 79caa11 already covers
    the env-off case; Pass 3 must not double-alarm."""
    from calibration.writer import compute_calibration_rate_health

    monkeypatch.delenv("ED_CALIBRATION_LOG", raising=False)
    now_ts = 1_800_000_000.0
    db_path = tmp_path / "cal_health_envoff.db"
    _seed_calibration_health_fixture(
        db_path,
        rows_last_24h=0,
        rows_prior_24h=0,
        enrolled_tickers=14,
        now_ts=now_ts,
    )

    health = compute_calibration_rate_health(db_path, now_ts=now_ts)
    assert health["env_enabled"] is False
    assert health["last_24h_count"] == 0
    assert health["warn"] is False


def test_calibration_rate_health_handles_missing_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Brand-new DB without calibration_decision_log => table_present=False, no crash, no warn."""
    from calibration.writer import compute_calibration_rate_health

    monkeypatch.setenv("ED_CALIBRATION_LOG", "1")
    db_path = tmp_path / "cal_health_empty.db"
    # Touch DB but don't create the table.
    sqlite3.connect(str(db_path)).close()

    health = compute_calibration_rate_health(db_path, now_ts=1_800_000_000.0)
    assert health["table_present"] is False
    assert health["last_24h_count"] == 0
    assert health["warn"] is False  # can't distinguish probe failure from true zero-write


def test_calibration_rate_health_enrolled_override_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """enrolled_tickers_override pins the universe size; fixture test stays deterministic
    regardless of whether logging_universe is seeded."""
    from calibration.writer import (
        EXPECTED_DECISIONS_PER_MINUTE_PER_TICKER,
        SESSION_MINUTES_RTH,
        compute_calibration_rate_health,
    )

    monkeypatch.setenv("ED_CALIBRATION_LOG", "1")
    db_path = tmp_path / "cal_health_override.db"
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_calibration_schema(conn)
    finally:
        conn.close()

    health = compute_calibration_rate_health(
        db_path, now_ts=1_800_000_000.0, enrolled_tickers_override=20
    )
    assert health["enrolled_tickers"] == 20
    assert health["expected_per_24h"] == pytest.approx(
        20 * SESSION_MINUTES_RTH * EXPECTED_DECISIONS_PER_MINUTE_PER_TICKER
    )
