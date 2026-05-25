"""calibration/writer fail-closed: ticker, canonical_timeframe, and JSON encoding."""

from __future__ import annotations

import json
import logging
import sqlite3
from types import SimpleNamespace

import pytest

from calibration.schema import ensure_calibration_schema
from calibration.writer import (
    _json_excerpt,
    _sqlite_busy_or_locked,
    append_calibration_decision,
    sqlite_busy_retry_sleep_seconds,
)
from db import EdDB, configure_sqlite_connection
from instrument_identity import ticker_storage_key
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


def test_append_calibration_decision_rejects_empty_ticker(calib_db):
    row_id = append_calibration_decision(**_call_args(calib_db, ticker=""))

    assert row_id is None
    conn = sqlite3.connect(str(calib_db))
    configure_sqlite_connection(conn)
    n_empty = int(
        conn.execute(
            "SELECT COUNT(*) FROM calibration_decision_log WHERE ticker = ?",
            ("",),
        ).fetchone()[0]
    )
    conn.close()
    assert n_empty == 0


def test_append_calibration_decision_rejects_none_ticker(calib_db):
    row_id = append_calibration_decision(**_call_args(calib_db, ticker=None))  # type: ignore[arg-type]

    assert row_id is None


def test_append_calibration_decision_rejects_missing_canonical_timeframe(calib_db):
    row_id = append_calibration_decision(**_call_args(calib_db, canonical_timeframe=""))

    assert row_id is None


def test_append_calibration_decision_inserts_with_valid_ticker(calib_db):
    row_id = append_calibration_decision(**_call_args(calib_db, ticker="SPY"))

    assert row_id is not None and row_id > 0
    conn = sqlite3.connect(str(calib_db))
    configure_sqlite_connection(conn)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT ticker FROM calibration_decision_log WHERE id = ?",
        (row_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["ticker"] == ticker_storage_key("SPY")


def test_model_outputs_json_single_encodes_null_models(calib_db):
    xgb = {"prob_up": 0.6, "dominant_class": "up"}
    args = _call_args(calib_db, ticker="SPY")
    args.update(
        xgb_out=xgb,
        lstm_out=None,
        transformer_out=None,
        ml_bundle={"stack_probs_5m": {"up": 0.5}},
    )
    row_id = append_calibration_decision(**args)

    assert row_id is not None and row_id > 0
    conn = sqlite3.connect(str(calib_db))
    configure_sqlite_connection(conn)
    conn.row_factory = sqlite3.Row
    mo_json = conn.execute(
        "SELECT model_outputs_json FROM calibration_decision_log WHERE id = ?",
        (row_id,),
    ).fetchone()["model_outputs_json"]
    conn.close()

    mo = json.loads(mo_json)
    assert mo["xgb"] == xgb
    assert mo["lstm"] is None
    assert mo["transformer"] is None
    assert mo["stack_probs_bundle"] == {"stack_probs_5m": {"up": 0.5}}
    assert not isinstance(mo["xgb"], str)


def test_sqlite_busy_retry_backoff_exponential_not_linear():
    sleeps = [sqlite_busy_retry_sleep_seconds(a) for a in range(11)]
    assert sleeps[0] == pytest.approx(0.01)
    assert sleeps[5] == pytest.approx(0.32)
    assert sleeps[6] == pytest.approx(0.5)
    assert all(s == pytest.approx(0.5) for s in sleeps[6:])
    linear_worst = sum(0.05 * (a + 1) for a in range(11))
    assert sum(sleeps) == pytest.approx(3.13, abs=0.01)
    assert sum(sleeps) < linear_worst


def test_append_calibration_decision_warns_when_db_missing(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("ED_CALIBRATION_LOG", "1")
    missing = tmp_path / "no_such.db"
    caplog.set_level(logging.WARNING)

    row_id = append_calibration_decision(**_call_args(missing, ticker="SPY"))

    assert row_id is None
    assert any("DB not found" in r.message for r in caplog.records)


def test_append_calibration_decision_integrity_error_returns_none(calib_db, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    real_connect = sqlite3.connect

    def connect_wrapper(path, timeout=60.0):
        conn = _SqliteConnExecuteHook(real_connect(path, timeout=timeout))

        def execute(sql, params=(), /):
            if "INSERT INTO calibration_decision_log" in str(sql):
                raise sqlite3.IntegrityError("simulated fk violation")
            return conn._conn.execute(sql, params)

        conn.execute = execute  # type: ignore[method-assign]
        return conn

    monkeypatch.setattr("calibration.writer.sqlite3.connect", connect_wrapper)
    row_id = append_calibration_decision(**_call_args(calib_db, ticker="SPY"))

    assert row_id is None
    assert any("insert failed" in r.message for r in caplog.records)


def test_append_calibration_decision_type_error_propagates(calib_db, monkeypatch):
    def boom(*_a, **_k):
        raise TypeError("simulated non-sqlite failure")

    monkeypatch.setattr("calibration.writer.dumps_compact", boom)
    with pytest.raises(TypeError, match="simulated non-sqlite failure"):
        append_calibration_decision(**_call_args(calib_db, ticker="SPY"))


def test_sqlite_busy_or_locked_uses_errorcode_not_message():
    e = sqlite3.OperationalError("unrelated message")
    e.sqlite_errorcode = sqlite3.SQLITE_BUSY
    assert _sqlite_busy_or_locked(e) is True
    e.sqlite_errorcode = sqlite3.SQLITE_LOCKED
    assert _sqlite_busy_or_locked(e) is True
    e.sqlite_errorcode = 999
    assert _sqlite_busy_or_locked(e) is False


def test_append_calibration_decision_retries_on_sqlite_busy_errorcode(calib_db, monkeypatch):
    real_connect = sqlite3.connect
    insert_attempts: list[int] = []

    def connect_wrapper(path, timeout=60.0):
        conn = _SqliteConnExecuteHook(real_connect(path, timeout=timeout))
        real_execute = conn._conn.execute

        def execute(sql, params=(), /):
            if "INSERT INTO calibration_decision_log" in str(sql):
                insert_attempts.append(1)
                if len(insert_attempts) == 1:
                    err = sqlite3.OperationalError("opaque")
                    err.sqlite_errorcode = sqlite3.SQLITE_BUSY
                    raise err
            return real_execute(sql, params)

        conn.execute = execute  # type: ignore[method-assign]
        return conn

    sleeps: list[float] = []
    monkeypatch.setattr("calibration.writer.sqlite3.connect", connect_wrapper)
    monkeypatch.setattr(
        "calibration.writer.time.sleep",
        lambda s: sleeps.append(s),
    )
    row_id = append_calibration_decision(**_call_args(calib_db, ticker="SPY"))

    assert row_id is not None and row_id > 0
    assert len(insert_attempts) == 2
    assert len(sleeps) == 1


def test_validation_summary_truncation_logs_info(calib_db, caplog):
    caplog.set_level(logging.INFO)
    args = _call_args(calib_db, ticker="SPY")
    args["call"] = SimpleNamespace(
        signal=None,
        conviction=None,
        entry=None,
        stop=None,
        target=None,
        target2=None,
        validation_summary="x" * 2500,
    )
    row_id = append_calibration_decision(**args)

    assert row_id is not None and row_id > 0
    assert any("validation_summary truncated" in r.message for r in caplog.records)
    conn = sqlite3.connect(str(calib_db))
    configure_sqlite_connection(conn)
    summary = conn.execute(
        "SELECT validation_summary FROM calibration_decision_log WHERE id = ?",
        (row_id,),
    ).fetchone()[0]
    conn.close()
    assert len(summary) == 2000


def test_json_excerpt_truncation_sentinel():
    big = {"k": "v" * 5000}
    out = _json_excerpt(big, limit=100)
    assert out is not None
    assert out.endswith('..."[TRUNCATED]"')
    assert len(out) <= 100


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
