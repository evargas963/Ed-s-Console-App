"""calibration/writer fail-closed: ticker, canonical_timeframe, and JSON encoding."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from calibration.schema import ensure_calibration_schema
from db import _sqlite_busy_or_locked
from db import EdDB, configure_sqlite_connection
from timeframe_config import CANONICAL_TIMEFRAME


class _SqliteConnExecuteHook:
    """Delegate sqlite3.Connection; override execute (read-only on Connection in Py 3.13)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql, params=(), /):
        return self._conn.execute(sql, params)

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


def _call_args(db_path, *, ticker: str = "SPY", canonical_timeframe: str = CANONICAL_TIMEFRAME):
    inp = SimpleNamespace(
        zone=None,
        vwap_side=None,
        nearest_above_dist=None,
        nearest_below_dist=None,
        nearest_above_name=None,
        nearest_below_name=None,
        nearest_above_val=None,
        nearest_below_val=None,
        expiry=None,
        vix_bucket=None,
        session_bucket=None,
    )
    call = SimpleNamespace(
        signal=None,
        conviction=None,
        entry=None,
        stop=None,
        target=None,
        target2=None,
        validation_summary=None,
    )
    return dict(
        decision_ts_utc=1_900_000_000.0,
        ticker=ticker,
        canonical_timeframe=canonical_timeframe,
        inp=inp,
        regime=None,
        vol_regime=None,
        fusion=None,
        canonical=None,
        pred=SimpleNamespace(),
        call=call,
        xgb_out=None,
        lstm_out=None,
        transformer_out=None,
        mc_out=None,
        ml_bundle={},
        mh_bundle=None,
        db_path=db_path,
    )


@pytest.fixture
def calib_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ED_CALIBRATION_LOG", "1")
    db_path = tmp_path / "writer_fail_closed.db"
    EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    conn.commit()
    conn.close()
    return db_path












def test_resolve_build_generation_env_wins(monkeypatch):
    import calibration.writer as w

    monkeypatch.setenv("ED_BUILD_GENERATION", "custom-gen-7")
    assert w.resolve_build_generation() == "custom-gen-7"


def test_resolve_build_generation_defaults_to_repo_git_sha(monkeypatch):
    """115k rows had build_generation NULL (env never set). Default = repo tip sha,
    so every logged decision carries a serve-stack fingerprint the temperature
    fitter / era filters can key on."""
    import calibration.writer as w

    monkeypatch.delenv("ED_BUILD_GENERATION", raising=False)
    w._build_generation_cache.clear()
    sha = w.resolve_build_generation()
    assert sha is not None and len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)
    # Cached: second call returns identity without re-invoking git.
    assert w.resolve_build_generation() is sha












def test_sqlite_busy_or_locked_uses_errorcode_not_message():
    e = sqlite3.OperationalError("unrelated message")
    e.sqlite_errorcode = sqlite3.SQLITE_BUSY
    assert _sqlite_busy_or_locked(e) is True
    e.sqlite_errorcode = sqlite3.SQLITE_LOCKED
    assert _sqlite_busy_or_locked(e) is True
    e.sqlite_errorcode = 999
    assert _sqlite_busy_or_locked(e) is False








@pytest.mark.parametrize("env_value,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("YES", True),
    ("on", True), ("On", True),
    ("0", False), ("false", False), ("no", False), ("off", False), ("", False),
])
def test_calibration_logging_enabled_env_var_semantics(monkeypatch, env_value, expected):
    """ED_CALIBRATION_LOG env gate semantics — case-insensitive, default-OFF.

    Root cause of the 2026-04-12 → 2026-05-05 calibration gap was the writer
    being env-gated with no operator visibility. Lock the exact env values that
    enable / disable so deployment configs don't silently flip the writer off
    via case-variation or whitespace mistakes.
    """
    from calibration.writer import calibration_logging_enabled

    if env_value is None:
        monkeypatch.delenv("ED_CALIBRATION_LOG", raising=False)
    else:
        monkeypatch.setenv("ED_CALIBRATION_LOG", env_value)
    assert calibration_logging_enabled() is expected


def test_calibration_logging_enabled_unset_returns_false(monkeypatch):
    """Env var absent → False (default-OFF). This is the production failure mode
    that caused the silent gap; the boot-time WARNING in server.py is what
    surfaces it to the operator."""
    from calibration.writer import calibration_logging_enabled

    monkeypatch.delenv("ED_CALIBRATION_LOG", raising=False)
    assert calibration_logging_enabled() is False


def test_calibration_logging_enabled_docstring_names_root_cause():
    """Lock the docstring so the env-var name + default-OFF semantic + the
    historical gap stay discoverable. If a future refactor moves the gate, this
    test fires so the documentation moves with it."""
    from calibration.writer import calibration_logging_enabled

    doc = calibration_logging_enabled.__doc__ or ""
    assert "ED_CALIBRATION_LOG" in doc
    assert "Default is OFF" in doc or "default-OFF" in doc.lower() or "default is off" in doc.lower()
    assert "calibration_decision_log" in doc
    assert "silent" in doc.lower()


def test_server_logs_calibration_state_at_boot():
    """server.py must call _log_calibration_logging_state_at_boot at module
    import so the operator sees ENABLED/DISABLED on every server restart."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
    assert "def _log_calibration_logging_state_at_boot" in src, "boot diagnostic function missing"
    assert "_log_calibration_logging_state_at_boot()" in src, "boot diagnostic call site missing"
    # Function must emit WARNING when disabled (not INFO — WARN gets the visual marker).
    fn_start = src.index("def _log_calibration_logging_state_at_boot")
    fn_end = src.index("\n_log_calibration_logging_state_at_boot()", fn_start)
    body = src[fn_start:fn_end]
    assert "log.warning" in body, "disabled path must use log.warning (gets [WARN] visual marker)"
    assert "ED_CALIBRATION_LOG" in body, "WARNING must name the env var so the operator knows the fix"
    assert "DISABLED" in body, "WARNING must announce DISABLED state explicitly"
