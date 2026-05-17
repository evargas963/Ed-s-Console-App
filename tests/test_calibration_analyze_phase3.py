"""calibration/analyze_phase3 helpers and fail-closed canonical probability handling."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from calibration.analyze_phase3 import (
    _canonical_prob_triplet,
    _load_json_col,
    analyze,
    main,
)
from calibration.edge_validation import _effective_directional_signal
from calibration.schema import ensure_calibration_schema
from calibration.trust import CALIBRATION_TRUST_TRUSTED
from calibration.v2_a1_calibration import axis_reliability_bucket_value
from db import EdDB, configure_sqlite_connection

_VALID = json.dumps(
    {
        "probability_up": 0.6,
        "probability_down": 0.2,
        "probability_flat": 0.2,
        "confidence": "low",
    }
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("", None),
        ("{}", None),
        ('{"foo": 1}', None),
        ('{"probability_up": 0.6}', None),
        ('{"probability_up": "x", "probability_down": 0.2, "probability_flat": 0.2}', None),
        (_VALID, (0.6, 0.2, 0.2)),
    ],
)
def test_canonical_prob_triplet(raw, expected):
    out = _canonical_prob_triplet(raw)
    if expected is None:
        assert out is None
    else:
        assert out == pytest.approx(expected)


def test_load_json_col_malformed_logs_warning(caplog):
    caplog.set_level(logging.WARNING)
    assert _load_json_col("{not-json") == {}
    assert any("could not parse JSON column" in r.message for r in caplog.records)


def test_effective_directional_signal_wait_when_canonical_missing():
    row = {"final_signal": "wait", "canonical_json": ""}
    assert _effective_directional_signal(row) == "wait"


def test_analyze_skips_brier_when_all_canonical_json_invalid(tmp_path, monkeypatch):
    db_path = tmp_path / "phase3_bad_canonical.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    for ts in (3000.0, 3001.0):
        conn.execute(
            """
            INSERT INTO calibration_decision_log (
                decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
                outcome_5c, outcome_1c, outcome_15c, outcome_60c,
                outcome_1c_pts, outcome_5c_pts, outcome_15c_pts, outcome_60c_pts,
                canonical_json
            )
            VALUES (?, 'SPY', '1m', ?, 'up', 'up', 'up', 'up',
                    0.1, 0.2, 0.3, 0.4, ?)
            """,
            (ts, CALIBRATION_TRUST_TRUSTED, "{}"),
        )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "calibration.analyze_phase3.snapshot_has_bar_anchor",
        lambda _c, _t, _ts: True,
    )
    out = analyze(db_path)
    assert out.get("calibration_with_outcome") == 0
    assert out.get("brier_n") == 0
    assert out.get("brier_canonical_vs_outcome_5c") is None


def _seed_regime_model_bucket_db(db_path: Path) -> None:
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    regimes: list[str | None] = [None, "", "unknown", "compression"]
    for idx, regime in enumerate(regimes):
        conn.execute(
            """
            INSERT INTO calibration_decision_log (
                decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
                outcome_5c, outcome_1c, outcome_15c, outcome_60c,
                outcome_1c_pts, outcome_5c_pts, outcome_15c_pts, outcome_60c_pts,
                canonical_json, regime_primary, vol_regime
            )
            VALUES (?, 'SPY', '1m', ?, 'up', 'up', 'up', 'up',
                    0.1, 0.2, 0.3, 0.4, ?, ?, NULL)
            """,
            (4000.0 + idx, CALIBRATION_TRUST_TRUSTED, _VALID, regime),
        )
    conn.commit()
    conn.close()


def test_analyze_model_by_regime_buckets_separates_missing_from_unknown(tmp_path, monkeypatch):
    db_path = tmp_path / "phase3_regime_sentinel.db"
    _seed_regime_model_bucket_db(db_path)
    monkeypatch.setattr(
        "calibration.analyze_phase3.snapshot_has_bar_anchor",
        lambda _c, _t, _ts: True,
    )
    out = analyze(db_path)
    keys = set(out.get("model_by_regime_buckets", {}).keys())
    assert f"{axis_reliability_bucket_value(None)}|{axis_reliability_bucket_value(None)}" in keys
    assert f"unknown|{axis_reliability_bucket_value(None)}" in keys
    assert f"compression|{axis_reliability_bucket_value(None)}" in keys
    missing_key = f"__missing__|__missing__"
    assert missing_key in keys
    assert out["model_by_regime_buckets"][missing_key]["n"] == 2


def test_analyze_regime_buckets_separates_missing_from_unknown(tmp_path, monkeypatch):
    db_path = tmp_path / "phase3_regime_buckets_sentinel.db"
    _seed_regime_model_bucket_db(db_path)
    monkeypatch.setattr(
        "calibration.analyze_phase3.snapshot_has_bar_anchor",
        lambda _c, _t, _ts: True,
    )
    out = analyze(db_path)
    rb = out.get("regime_buckets", {})
    missing = axis_reliability_bucket_value(None)
    assert missing in rb
    assert rb[missing]["n"] == 2
    assert "unknown" in rb
    assert "compression" in rb


@pytest.mark.parametrize("binary_pass,expected_code", [(True, 0), (False, 3)])
def test_main_exit_code_reflects_binary_pass(binary_pass, expected_code, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "calibration.analyze_phase3.analyze",
        lambda _db: {"statistical_integrity": {"binary_pass": binary_pass}},
    )
    monkeypatch.setattr(
        "calibration.analyze_phase3.require_canonical_db_target",
        lambda *a, **k: None,
    )
    monkeypatch.setattr("calibration.analyze_phase3.ensure_artifacts_dir", lambda: None)
    monkeypatch.setattr(
        "calibration.analyze_phase3.write_json_file_atomically",
        lambda path, payload, **kw: None,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["analyze_phase3", "--db", str(tmp_path / "unused.db")],
    )
    assert main() == expected_code


def test_main_uses_atomic_json_write(monkeypatch, tmp_path):
    written: list[tuple] = []

    def _capture(path, payload, **kw):
        written.append((path, payload, kw))

    monkeypatch.setattr(
        "calibration.analyze_phase3.analyze",
        lambda _db: {"statistical_integrity": {"binary_pass": True}},
    )
    monkeypatch.setattr(
        "calibration.analyze_phase3.require_canonical_db_target",
        lambda *a, **k: None,
    )
    monkeypatch.setattr("calibration.analyze_phase3.ensure_artifacts_dir", lambda: None)
    monkeypatch.setattr("calibration.analyze_phase3.write_json_file_atomically", _capture)
    monkeypatch.setattr(
        "sys.argv",
        ["analyze_phase3", "--db", str(tmp_path / "unused.db")],
    )
    assert main() == 0
    assert len(written) == 1
