"""calibration/analyze_phase4 fail-closed helpers and MHAP alignment partitioning."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from calibration.analyze_phase4 import (
    _directional_pnl,
    _load_json,
    analyze,
    main,
)
from calibration.schema import ensure_calibration_schema
from calibration.trust import CALIBRATION_TRUST_TRUSTED
from db import EdDB, configure_sqlite_connection

_CANONICAL_JSON = json.dumps(
    {
        "probability_up": 0.34,
        "probability_down": 0.33,
        "probability_flat": 0.33,
        "confidence": "low",
    }
)


def test_directional_pnl_long_short_wait():
    assert _directional_pnl("long", "up", 2.0) == 2.0
    assert _directional_pnl("long", "down", 2.0) == -2.0
    assert _directional_pnl("short", "down", 3.0) == 3.0
    assert _directional_pnl("wait", "up", 1.0) is None


def test_load_json_malformed_logs_warning(caplog):
    caplog.set_level(logging.WARNING)
    assert _load_json("{not-json") == {}
    assert any("could not parse JSON column" in r.message for r in caplog.records)


def _seed_mhap_alignment_db(db_path: Path) -> None:
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    states = [
        "fully_aligned",
        "mostly_aligned",
        "contradictory",
        "weak",
        "mixed",
        "unusable",
        "",
    ]
    for idx, align in enumerate(states):
        mh = json.dumps({"alignment_state": align})
        conn.execute(
            """
            INSERT INTO calibration_decision_log (
                decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
                outcome_5c, outcome_1c, outcome_15c, outcome_60c,
                outcome_1c_pts, outcome_5c_pts, outcome_15c_pts, outcome_60c_pts,
                canonical_json, multi_horizon_json, final_signal
            )
            VALUES (?, 'SPY', '1m', ?, 'up', 'up', 'up', 'up',
                    0.1, 1.0, 0.3, 0.4, ?, ?, 'long')
            """,
            (5000.0 + idx, CALIBRATION_TRUST_TRUSTED, _CANONICAL_JSON, mh),
        )
    conn.commit()
    conn.close()


def test_analyze_mhap_skips_unusable_and_partitions_alignment_states(tmp_path, monkeypatch):
    db_path = tmp_path / "phase4_mhap.db"
    _seed_mhap_alignment_db(db_path)
    monkeypatch.setattr(
        "calibration.analyze_phase4.snapshot_has_bar_anchor",
        lambda _c, _t, _ts: True,
    )
    out = analyze(db_path)
    mh = out["mhap_alignment"]
    assert mh["aligned_n"] == 2
    assert mh["misaligned_n"] == 1


@pytest.mark.parametrize("binary_pass,expected_code", [(True, 0), (False, 3)])
def test_main_exit_code_reflects_binary_pass(binary_pass, expected_code, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "calibration.analyze_phase4.analyze",
        lambda _db: {"statistical_integrity": {"binary_pass": binary_pass}},
    )
    monkeypatch.setattr(
        "calibration.analyze_phase4.require_canonical_db_target",
        lambda *a, **k: None,
    )
    monkeypatch.setattr("calibration.analyze_phase4.ensure_artifacts_dir", lambda: None)
    monkeypatch.setattr(
        "calibration.analyze_phase4.write_json_file_atomically",
        lambda path, payload, **kw: None,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["analyze_phase4", "--db", str(tmp_path / "unused.db")],
    )
    assert main() == expected_code


def test_main_uses_atomic_json_write(monkeypatch, tmp_path):
    written: list[tuple] = []

    def _capture(path, payload, **kw):
        written.append((path, payload, kw))

    monkeypatch.setattr(
        "calibration.analyze_phase4.analyze",
        lambda _db: {"statistical_integrity": {"binary_pass": True}},
    )
    monkeypatch.setattr(
        "calibration.analyze_phase4.require_canonical_db_target",
        lambda *a, **k: None,
    )
    monkeypatch.setattr("calibration.analyze_phase4.ensure_artifacts_dir", lambda: None)
    monkeypatch.setattr("calibration.analyze_phase4.write_json_file_atomically", _capture)
    monkeypatch.setattr(
        "sys.argv",
        ["analyze_phase4", "--db", str(tmp_path / "unused.db")],
    )
    assert main() == 0
    assert len(written) == 1
