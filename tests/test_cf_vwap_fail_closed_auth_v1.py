"""Fail-closed authorization + historical pa_vwap_zscore contamination repair.

# universal-scope-ok: authorization gate applies to every enrolled cf_vwap consumer.
# next-rth-ok: 2026-08-31 Monday.
# chart-intent-ok: ML authorization / research semantics only; Chart not claimed Done.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ml_train import (
    canonical_session_vwap_present,
    feature_list_requires_cf_vwap_distance,
    should_abstain_missing_session_vwap_for_cf,
)
from snapshot_normalizer import null_pa_vwap_zscore_roll_contamination


def test_gate_on_raw_session_vwap_not_on_engineered_zero() -> None:
    # Genuine spot==VWAP: session VWAP present → do not abstain (0.0 is legitimate).
    assert canonical_session_vwap_present(500.0) is True
    assert should_abstain_missing_session_vwap_for_cf(
        session_vwap=500.0,
        feature_names=["cf_vwap_distance_pct", "vwap_dist_pct"],
    ) is False

    # Absent session VWAP + dependent feature list → abstain.
    assert canonical_session_vwap_present(None) is False
    assert canonical_session_vwap_present(0) is False
    assert should_abstain_missing_session_vwap_for_cf(
        session_vwap=None,
        feature_names=["cf_vwap_distance_pct", "vwap_dist_pct"],
    ) is True

    # Nonzero distance still requires present VWAP — presence alone clears the gate.
    assert should_abstain_missing_session_vwap_for_cf(
        session_vwap=501.25,
        feature_names=["cf_vwap_distance_pct"],
    ) is False


def test_gate_does_not_disable_artifacts_without_cf_vwap() -> None:
    feats = ["vwap_dist_pct", "vwap_dist_pts", "cat_vwap_side", "spot"]
    assert feature_list_requires_cf_vwap_distance(feats) is False
    assert should_abstain_missing_session_vwap_for_cf(
        session_vwap=None,
        feature_names=feats,
    ) is False


def test_lstm_consumes_flag_path() -> None:
    assert should_abstain_missing_session_vwap_for_cf(
        session_vwap=None,
        consumes_cf_vwap=True,
    ) is True
    assert should_abstain_missing_session_vwap_for_cf(
        session_vwap=None,
        consumes_cf_vwap=False,
    ) is False
    assert should_abstain_missing_session_vwap_for_cf(
        session_vwap=100.0,
        consumes_cf_vwap=True,
    ) is False


def test_predict_paths_wire_session_vwap_abstain() -> None:
    src = Path("ml_predict.py").read_text(encoding="utf-8")
    assert "should_abstain_missing_session_vwap_for_cf" in src
    assert src.count("session VWAP absent while") >= 2


def test_null_pa_vwap_roll_contamination_only_null_vwap_rows(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE snapshots (
            snapshot_id INTEGER PRIMARY KEY,
            ticker TEXT, ts_utc REAL, vwap REAL, pa_vwap_zscore REAL
        );
        CREATE TABLE snapshots_1m_normalized (
            ticker TEXT, ts_utc REAL, vwap REAL, pa_vwap_zscore REAL
        );
        INSERT INTO snapshots VALUES
            (1, 'SPY', 1.0, 500.0, 0.5),
            (2, 'SPY', 2.0, NULL, 0.7),
            (3, 'QQQ', 3.0, NULL, NULL);
        INSERT INTO snapshots_1m_normalized VALUES
            ('SPY', 1.0, 500.0, 0.5),
            ('SPY', 2.0, NULL, 0.7),
            ('QQQ', 3.0, NULL, NULL);
        """
    )
    con.commit()
    con.close()

    out = null_pa_vwap_zscore_roll_contamination(db)
    assert out["snapshots_nulled"] == 1
    assert out["normalized_nulled"] == 1

    con = sqlite3.connect(db)
    rows = list(con.execute(
        "SELECT snapshot_id, vwap, pa_vwap_zscore FROM snapshots ORDER BY snapshot_id"
    ))
    con.close()
    assert rows[0] == (1, 500.0, 0.5)  # session-present kept
    assert rows[1] == (2, None, None)  # contamination nulled
    assert rows[2] == (3, None, None)


def test_research_runners_exclude_null_session_vwap() -> None:
    pa = Path("research/pa_returns_eval_v1/runner.py").read_text(encoding="utf-8")
    zone = Path("research/zone_vwap_eval_v1/runner.py").read_text(encoding="utf-8")
    assert "AND vwap IS NOT NULL" in pa
    assert "AND vwap IS NOT NULL" in zone
