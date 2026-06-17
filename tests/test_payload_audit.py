"""payload_audit CLI, JSON parsing, and exit codes."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from calibration.payload_audit import main, run_payload_audit
from calibration.schema import ensure_calibration_schema
from db import EdDB, configure_sqlite_connection


@pytest.fixture
def audit_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "payload_audit.db"
    EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    conn.execute(
        """
        INSERT INTO calibration_decision_log (
            decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
            fusion_json, canonical_json, model_outputs_json, final_signal
        ) VALUES (?, ?, '1m', 'trusted', ?, ?, ?, 'wait')
        """,
        (
            1_900_000_000.0,
            "SPY",
            "{not valid json",
            '{"a":1}',
            '{"xgb":{},"lstm":{},"transformer":{}}',
        ),
    )
    conn.commit()
    conn.close()
    return db_path


def test_run_payload_audit_warns_on_corrupt_json(audit_db: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    run_payload_audit(audit_db)
    assert any("fusion_json" in r.message and "unparseable" in r.message for r in caplog.records)


def test_main_exit_3_when_numeric_leak(audit_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with patch(
        "calibration.payload_audit.verify_payload_audit_no_numeric_leak",
        return_value=False,
    ):
        with patch(
            "sys.argv",
            ["payload_audit", "--db", str(audit_db), "--allow-noncanonical-db"],
        ):
            rc = main()
    assert rc == 3
    out = json.loads(capsys.readouterr().out)
    assert out["binary_pass"] is False


def test_main_exit_0_when_pass(audit_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with patch(
        "sys.argv",
        ["payload_audit", "--db", str(audit_db), "--allow-noncanonical-db"],
    ):
        rc = main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "trusted_rows" in out
