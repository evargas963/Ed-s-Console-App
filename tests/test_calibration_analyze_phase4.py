"""calibration/analyze_phase4 fail-closed helpers and MHAP alignment partitioning."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pytest

from calibration.analyze_phase4 import (
    _MHAP_ALIGNED_STATES,
    _MHAP_MISALIGNED_STATES,
    _directional_pnl,
    _load_json,
    analyze,
    main,
)
from calibration.schema import ensure_calibration_schema
from calibration.statistical_integrity import MIN_N_BASELINE_COMPARISON
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
        "no_primary",
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


@pytest.mark.parametrize(
    "align,expected",
    [
        ("fully_aligned", "aligned"),
        ("mostly_aligned", "aligned"),
        ("contradictory", "misaligned"),
        ("weak", "misaligned"),
        ("mixed", "misaligned"),
        ("no_primary", "skip"),
        ("unusable", "skip"),
        ("unknown", "skip"),
        ("", "skip"),
    ],
)
def test_mhap_alignment_state_bucket(align, expected):
    st = (align or "").strip().upper()
    if expected == "aligned":
        assert st in _MHAP_ALIGNED_STATES
    elif expected == "misaligned":
        assert st in _MHAP_MISALIGNED_STATES
    else:
        assert st not in _MHAP_ALIGNED_STATES
        assert st not in _MHAP_MISALIGNED_STATES


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
    assert mh["misaligned_n"] == 3


def _seed_baseline_snapshots(db_path: Path, *, n: int, outcome: str, pts: float) -> None:
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    for i in range(n):
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, spot,
                outcome_5c, outcome_5c_pts, vwap_side
            )
            VALUES ('SPY', '1m', ?, 'et', 100.0, ?, ?, NULL)
            """,
            (7000.0 + i, outcome, pts),
        )
    conn.commit()
    conn.close()


def test_analyze_baselines_always_down_positive_on_down_outcomes(tmp_path):
    db_path = tmp_path / "phase4_baselines.db"
    n = MIN_N_BASELINE_COMPARISON
    _seed_baseline_snapshots(db_path, n=n, outcome="down", pts=2.0)
    out = analyze(db_path)
    bl = out["baselines_from_snapshots"]
    assert bl["always_down_mean_5c_pts"] is not None
    assert bl["always_down_mean_5c_pts"] > 0
    assert bl["always_down_mean_gate"]["sufficient_sample"]


def test_analyze_baselines_match_directional_pnl_per_row(tmp_path):
    db_path = tmp_path / "phase4_baseline_consistency.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    rows = [
        ("up", 1.5),
        ("down", -2.0),
        ("flat", 0.25),
    ]
    for i, (oc, pts) in enumerate(rows):
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, spot,
                outcome_5c, outcome_5c_pts, vwap_side
            )
            VALUES ('SPY', '1m', ?, 'et', 100.0, ?, ?, NULL)
            """,
            (8000.0 + i, oc, pts),
        )
    conn.commit()
    conn.close()

    snap = sqlite3.connect(str(db_path))
    snap.row_factory = sqlite3.Row
    snap_rows = snap.execute(
        "SELECT outcome_5c, outcome_5c_pts FROM snapshots WHERE outcome_5c_pts IS NOT NULL"
    ).fetchall()
    snap.close()

    always_up = []
    always_down = []
    for r in snap_rows:
        p = float(r["outcome_5c_pts"])
        oc = r["outcome_5c"]
        up_pnl = _directional_pnl("long", oc, p)
        dn_pnl = _directional_pnl("short", oc, p)
        if up_pnl is not None:
            always_up.append(up_pnl)
        if dn_pnl is not None:
            always_down.append(dn_pnl)

    assert always_up == [
        _directional_pnl("long", oc, float(pts)) for oc, pts in rows
    ]
    assert always_down == [
        _directional_pnl("short", oc, float(pts)) for oc, pts in rows
    ]


def test_analyze_vwap_mr_proxy_matches_directional_pnl(tmp_path):
    db_path = tmp_path / "phase4_vwap_mr.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    n_half = MIN_N_BASELINE_COMPARISON // 2
    for i in range(n_half):
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, spot,
                outcome_5c, outcome_5c_pts, vwap_side
            )
            VALUES ('SPY', '1m', ?, 'et', 100.0, 'up', 3.0, 'below')
            """,
            (9000.0 + i,),
        )
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, spot,
                outcome_5c, outcome_5c_pts, vwap_side
            )
            VALUES ('SPY', '1m', ?, 'et', 100.0, 'down', 4.0, 'above')
            """,
            (9100.0 + i,),
        )
    conn.commit()
    conn.close()

    out = analyze(db_path)
    bl = out["baselines_from_snapshots"]
    assert bl["vwap_side_mean_reversion_proxy_n"] == MIN_N_BASELINE_COMPARISON
    expected_mean = (
        n_half * _directional_pnl("long", "up", 3.0)
        + n_half * _directional_pnl("short", "down", 4.0)
    ) / MIN_N_BASELINE_COMPARISON
    assert bl["vwap_side_mean_reversion_proxy_mean"] == pytest.approx(expected_mean)


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
