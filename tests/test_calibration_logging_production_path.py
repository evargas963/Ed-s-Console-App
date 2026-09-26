"""
Production-path proof for calibration_decision_log (same stack as server → market_state → compute_signals).

Uses a temp SQLite DB, ED_CALIBRATION_LOG=1, and real compute_signals (no alternate code path).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import db as db_mod
from calibration.schema import ensure_calibration_schema
from db import EdDB, configure_sqlite_connection
from instrument_identity import ticker_storage_key
from calibration.v2_live_logging import append_live_v2_calibration_decision
from signals import compute_signals
from v2_decision import build_module_a_a1_decision

_SPY_KEY = ticker_storage_key("SPY")


def _v2_for_output(out, ticker: str = "SPY") -> dict:
    canonical = out.canonical_forecast
    prob = canonical.dominant_probability()   # None when there is no forecast (audit C-01)
    return build_module_a_a1_decision(
        {
            "ticker": ticker,
            "fusion_available": prob is not None,
            "fusion_dominant_direction": canonical.direction,
            "fusion_dominant_prob": prob,
            "execution_mode": getattr(out.call, "execution_mode", None),
        }
    )


def _register_execution_identity_for_test(db_path, decision_id: str) -> str:
    """Register a minimal REAL execution identity + ledger binding so the
    linkage triggers accept the calibration row (execution_identity_v1)."""
    import sqlite3 as _sq

    import execution_identity as _xi

    env = _xi.build_execution_envelope(
        release={"release_id": "rel-test", "git_sha": "a" * 40,
                 "config_hash": "c" * 64, "build_generation": "g"},
        requested_ticker="SPY",
        bundle_ticker="SPY",
        guest_anchor=False,
        guest_anchor_ticker=None,
        horizons_attempted=["1c"],
        bundles_by_horizon={},
        calibration_by_horizon=None,
        calibration_logging_enabled=True,
        stack_pins={"test": decision_id},
        runtime_class="TEST",
        degradation=None,
        tradeable_policy=None,
        executed_at_utc=1.0,
    )
    conn = _sq.connect(str(db_path), timeout=30.0)
    try:
        _xi.ensure_execution_identity_schema(conn)
        return _xi.insert_execution_identity(
            conn, env, decision_id=decision_id, expected_surfaces=["calibration"]
        )
    finally:
        conn.close()


def _compute_then_log(inp, *, db_path: Path, edb: EdDB):
    out = compute_signals(inp, db=edb)
    # execution_identity_v1: the live path always carries the governed
    # per-decision identity, REGISTERED so the linkage triggers accept the row
    # (deterministic per refresh_ts so idempotent duplicate-key semantics stay
    # observable across threads/retries — same decision -> same identity).
    _ts = getattr(inp, "refresh_ts_utc", 0.0)
    _did = f"testdid-{getattr(inp, 'ticker', 'SPY')}-{_ts}"
    _sha = _register_execution_identity_for_test(db_path, _did)

    append_live_v2_calibration_decision(
        db_path=db_path,
        calibration_payload=out.calibration_payload,
        v2_decision=_v2_for_output(out, getattr(inp, "ticker", "SPY")),
        decision_id=_did,
        execution_identity_sha256=_sha,
        colocated_snapshot_ts_utc=float(_ts) if _ts else None,
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
