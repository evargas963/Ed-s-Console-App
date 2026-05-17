"""calibration/writer fail-closed: ticker, canonical_timeframe, and JSON encoding."""

from __future__ import annotations

import json
import logging
import sqlite3
from types import SimpleNamespace

import pytest

from calibration.schema import ensure_calibration_schema
from calibration.writer import append_calibration_decision, sqlite_busy_retry_sleep_seconds
from db import EdDB, configure_sqlite_connection
from instrument_identity import ticker_storage_key
from timeframe_config import CANONICAL_TIMEFRAME


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
