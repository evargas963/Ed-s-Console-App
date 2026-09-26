"""calibration.v2_advisory_backfill must write the V2 advisory decision log into the
live calibration sqlite schema with the correct adapter/schema version columns --
a mismatch here corrupts calibration training data silently."""
from __future__ import annotations

import sqlite3

from calibration.schema import ensure_calibration_schema
from calibration.v2_advisory_backfill import (
    ADVISORY_V2_DECISION_LOG_COLUMNS,
)
from calibration.v2_live_logging import (
    LIVE_ADVISORY_V2_DECISION_LOG_COLUMNS,
    LIVE_ADVISORY_V2_SKIP_NO_PAYLOAD,
    append_live_v2_calibration_decision,
)
from db import configure_sqlite_connection
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


def test_live_v2_writer_uses_same_columns_as_backfill_writer():
    assert LIVE_ADVISORY_V2_DECISION_LOG_COLUMNS == ADVISORY_V2_DECISION_LOG_COLUMNS
