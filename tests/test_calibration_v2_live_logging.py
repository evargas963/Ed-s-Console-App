from __future__ import annotations

import json
import sqlite3

from calibration.schema import ensure_calibration_schema
from calibration.v2_advisory_backfill import (
    ADVISORY_V2_ADAPTER_VERSION,
    ADVISORY_V2_DECISION_LOG_COLUMNS,
    ADVISORY_V2_SNAPSHOT_SCHEMA_VERSION,
)
from calibration.v2_live_logging import (
    LIVE_ADVISORY_V2_DECISION_LOG_COLUMNS,
    LIVE_ADVISORY_V2_SKIP_MISSING_DECISION_TS,
    LIVE_ADVISORY_V2_SKIP_NO_PAYLOAD,
    append_live_v2_calibration_decision,
)
from db import configure_sqlite_connection
from signal_types import SignalInput
from v2_decision import build_module_a_a1_decision


DECISION_TS = 1_778_100_000.25


def _seed_db(tmp_path):
    db_path = tmp_path / "v2_live_logging.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    return db_path, conn


def _v2_decision() -> dict:
    return build_module_a_a1_decision(
        {
            "ticker": "SPY",
            "fusion_available": True,
            "fusion_dominant_direction": "up",
            "fusion_dominant_prob": 0.64,
            "execution_mode": "STANDARD",
            "decision_generation_id": "test-live-v2",
        }
    )


def _signal_input() -> SignalInput:
    from calibration.validate_logging_e2e import _inp

    return _inp(refresh_ts_utc=DECISION_TS)


def _signal_output():
    from signals import compute_signals

    return compute_signals(_signal_input())


def test_live_v2_logging_inserts_single_row_with_v1_and_v2_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("ED_CALIBRATION_LOG", "1")
    db_path, conn = _seed_db(tmp_path)
    conn.close()
    signal_output = _signal_output()

    # execution_identity_v1: a live write WITHOUT identity is refused (fail closed)
    refused = append_live_v2_calibration_decision(
        db_path=db_path,
        calibration_payload=signal_output.calibration_payload,
        v2_decision=_v2_decision(),
    )
    assert refused == {
        "status": "refused",
        "reason": "v2_live_log_refused_missing_execution_identity",
    }

    result = append_live_v2_calibration_decision(
        db_path=db_path,
        calibration_payload=signal_output.calibration_payload,
        v2_decision=_v2_decision(),
        decision_id="d-live-test",
        execution_identity_sha256="e" * 64,
    )

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM calibration_decision_log").fetchone()
    conn.close()
    payload = json.loads(row["advisory_v2_decision_snapshot_json"])

    assert result == {"status": "ok", "row_id": 1}
    assert row["ticker"] == "SPY"
    assert row["decision_ts_utc"] == DECISION_TS
    assert row["calibration_trust"] == "trusted"
    assert row["final_signal"] is not None
    assert row["advisory_v2_snapshot_schema_version"] == ADVISORY_V2_SNAPSHOT_SCHEMA_VERSION
    assert row["advisory_v2_adapter_version"] == ADVISORY_V2_ADAPTER_VERSION
    assert row["advisory_v2_backfill_status"] == "ok"
    assert row["advisory_v2_backfill_reason"] is None
    assert payload["source"] == "live_tier_c_advisory"
    assert payload["adapter_version"] == ADVISORY_V2_ADAPTER_VERSION
    assert payload["v2_decision"]["authority"]["mode"] == "advisory_non_authoritative"
    assert row["decision_id"] == "d-live-test"
    assert row["execution_identity_sha256"] == "e" * 64


def test_live_v2_logging_skips_when_refresh_ts_utc_missing(tmp_path, monkeypatch):
    from dataclasses import replace

    monkeypatch.setenv("ED_CALIBRATION_LOG", "1")
    db_path, conn = _seed_db(tmp_path)
    conn.close()
    signal_output = _signal_output()
    payload = dict(signal_output.calibration_payload)
    payload["inp"] = replace(payload["inp"], refresh_ts_utc=None)

    result = append_live_v2_calibration_decision(
        db_path=db_path,
        calibration_payload=payload,
        v2_decision=_v2_decision(),
    )

    conn = sqlite3.connect(str(db_path))
    n = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    conn.close()

    assert result == {
        "status": "skipped",
        "reason": LIVE_ADVISORY_V2_SKIP_MISSING_DECISION_TS,
    }
    assert n == 0


def test_live_v2_logging_skips_gracefully_without_signal_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("ED_CALIBRATION_LOG", "1")
    db_path, conn = _seed_db(tmp_path)
    conn.close()

    result = append_live_v2_calibration_decision(
        db_path=db_path,
        calibration_payload=None,
        v2_decision=_v2_decision(),
    )

    assert result == {
        "status": "skipped",
        "reason": LIVE_ADVISORY_V2_SKIP_NO_PAYLOAD,
    }


def test_live_v2_logging_is_noop_when_calibration_logging_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("ED_CALIBRATION_LOG", raising=False)
    db_path, conn = _seed_db(tmp_path)
    conn.close()
    signal_output = _signal_output()

    result = append_live_v2_calibration_decision(
        db_path=db_path,
        calibration_payload=signal_output.calibration_payload,
        v2_decision=_v2_decision(),
    )

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    n = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    conn.close()

    assert result is None
    assert n == 0


def test_live_v2_writer_uses_same_columns_as_backfill_writer():
    assert LIVE_ADVISORY_V2_DECISION_LOG_COLUMNS == ADVISORY_V2_DECISION_LOG_COLUMNS
