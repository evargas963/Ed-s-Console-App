"""validate_outcome_join fail-closed: outcomes, exit codes, mismatch detail."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from calibration.schema import ensure_calibration_schema
from calibration.validate_outcome_join import _outcome_field_equal, analyze, main
from db import EdDB, configure_sqlite_connection


def test_outcome_field_equal_none_vs_empty_string_is_mismatch() -> None:
    assert _outcome_field_equal(None, "", numeric=False) is False
    assert _outcome_field_equal("", None, numeric=False) is False


def test_outcome_field_equal_both_none() -> None:
    assert _outcome_field_equal(None, None, numeric=False) is True


def test_outcome_field_equal_same_label() -> None:
    assert _outcome_field_equal("up", "up", numeric=False) is True


@pytest.fixture
def pending_only_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "join_pending.db"
    EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    conn.execute(
        """
        INSERT INTO calibration_decision_log (
            decision_ts_utc, ticker, canonical_timeframe, calibration_trust
        ) VALUES (?, ?, '1m', 'trusted')
        """,
        (1_900_000_000.0, "SPY"),
    )
    conn.commit()
    conn.close()
    return db_path


def test_binary_pass_false_when_no_attached_outcomes(pending_only_db: Path) -> None:
    rep = analyze(pending_only_db)
    assert rep["rows_with_outcomes"] == 0
    assert rep["verification_pass"] == 0
    assert rep["binary_pass"] is False
    assert rep["binary_pass_strict_production"] is False


def test_main_exit_2_on_vacuous_no_outcomes(pending_only_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with patch(
        "sys.argv",
        ["validate_outcome_join", "--db", str(pending_only_db), "--allow-noncanonical-db"],
    ):
        rc = main()
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["binary_pass"] is False


def test_verification_fail_includes_mismatch_field(tmp_path: Path) -> None:
    db_path = tmp_path / "mismatch.db"
    EdDB(db_path)
    ts = 1_900_000_100.0
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    conn.execute(
        """
        INSERT INTO snapshots (
            ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
            horizon_outcome_schema_version, outcome_filled,
            outcome_1c, outcome_5c, outcome_15c, outcome_60c,
            outcome_1c_pts, outcome_5c_pts, outcome_15c_pts, outcome_60c_pts
        ) VALUES (?, '1m', ?, 't', 10, 0, 'rth', 100.0, 3, 1,
                  'up', 'up', 'flat', 'down', 0.1, 0.2, 0.3, 0.4)
        """,
        ("SPY", ts),
    )
    conn.execute(
        """
        INSERT INTO calibration_decision_log (
            decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
            outcome_1c, outcome_5c, outcome_15c, outcome_60c,
            outcome_1c_pts, outcome_5c_pts, outcome_15c_pts, outcome_60c_pts,
            matched_snapshot_ts_utc, outcome_join_method
        ) VALUES (?, ?, '1m', 'trusted', 'up', 'down', 'flat', 'down', 0.1, 0.2, 0.3, 0.4, ?, 'exact')
        """,
        (ts, "SPY", ts),
    )
    conn.commit()
    conn.close()

    rep = analyze(db_path)
    assert rep["verification_fail"] == 1
    ex = rep["verification_fail_examples"][0]
    assert ex["reason"] == "outcome_mismatch_vs_snapshot"
    assert ex["mismatch_field"] == "outcome_5c"
    assert ex["calib_value"] == "down"
    assert ex["snap_value"] == "up"
