"""Action 12.14: signal_layer_discrimination fail-closed fusion + final_signal handling."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from calibration.schema import ensure_calibration_schema
from calibration.signal_layer_discrimination import run_discrimination
from db import EdDB, configure_sqlite_connection

BASE_TS = 2_000_000.0
TICKER = "SPY"


def _seed_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "discrimination.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    for i in range(30):
        be = BASE_TS - float(29 - i) * 60.0
        bs = be - 60.0
        c = 100.0 + float(i) * 0.01
        conn.execute(
            """
            INSERT INTO price_bars_1m (
                ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'test')
            """,
            (TICKER, bs, be, c, c + 0.05, c - 0.05, c, 1e6),
        )
    conn.commit()
    conn.close()
    return db_path


def _insert_row(
    conn: sqlite3.Connection,
    *,
    fusion_json: str | None,
    final_signal: str | None = "wait",
    outcome_pts: float = 0.1,
    ts: float = BASE_TS,
) -> None:
    conn.execute(
        """
        INSERT INTO calibration_decision_log (
            decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
            outcome_5c_pts, fusion_json, final_signal
        ) VALUES (?, ?, '1m', 'trusted', ?, ?, ?)
        """,
        (ts, TICKER, outcome_pts, fusion_json, final_signal),
    )


def test_run_discrimination_excludes_null_fusion_json_from_means(tmp_path: Path) -> None:
    db_path = _seed_db(tmp_path)
    conn = sqlite3.connect(str(db_path))
    _insert_row(
        conn,
        fusion_json=json.dumps({"prob_up": 0.6, "prob_down": 0.3, "prob_flat": 0.1}),
    )
    _insert_row(conn, fusion_json=None, ts=BASE_TS - 120.0)
    conn.commit()
    conn.close()

    out = run_discrimination(db_path)
    assert out["fusion_n_present_in_log"] == 1
    assert out["fusion_n_missing_in_log"] == 1
    assert out["fusion_mean_p_up_down_flat"] == pytest.approx([0.6, 0.3, 0.1])


def test_run_discrimination_reports_none_means_when_no_valid_fusion(tmp_path: Path) -> None:
    db_path = _seed_db(tmp_path)
    conn = sqlite3.connect(str(db_path))
    _insert_row(conn, fusion_json=None)
    _insert_row(
        conn,
        fusion_json=json.dumps({"prob_up": 0.5, "prob_down": None, "prob_flat": 0.5}),
        ts=BASE_TS - 120.0,
    )
    conn.commit()
    conn.close()

    out = run_discrimination(db_path)
    assert out["fusion_n_present_in_log"] == 0
    assert out["fusion_n_missing_in_log"] == 2
    assert out["fusion_mean_p_up_down_flat"] == [None, None, None]
    assert out["fusion_triplet_spread_l1"] is None
    assert out["fusion_near_flat_max_min_gap"] is None
    assert out["flags"]["fusion_triplet_near_collapse"] is False


def test_run_discrimination_preserves_null_final_signal_via_missing_category(tmp_path: Path) -> None:
    db_path = _seed_db(tmp_path)
    conn = sqlite3.connect(str(db_path))
    _insert_row(
        conn,
        fusion_json=json.dumps({"prob_up": 0.5, "prob_down": 0.3, "prob_flat": 0.2}),
        final_signal=None,
    )
    _insert_row(
        conn,
        fusion_json=json.dumps({"prob_up": 0.5, "prob_down": 0.3, "prob_flat": 0.2}),
        final_signal="long",
        ts=BASE_TS - 120.0,
    )
    conn.commit()
    conn.close()

    out = run_discrimination(db_path)
    dist = out["final_signal_pct"]
    assert dist["missing"] == 50.0
    assert dist["long"] == 50.0
    assert dist["wait"] == 0.0


def test_run_discrimination_reports_fusion_n_present_vs_missing_counts(tmp_path: Path) -> None:
    db_path = _seed_db(tmp_path)
    conn = sqlite3.connect(str(db_path))
    valid = json.dumps({"prob_up": 0.55, "prob_down": 0.25, "prob_flat": 0.20})
    _insert_row(conn, fusion_json=valid)
    _insert_row(conn, fusion_json=None, ts=BASE_TS - 120.0)
    _insert_row(
        conn,
        fusion_json=json.dumps({"prob_up": 0.4}),
        ts=BASE_TS - 240.0,
    )
    conn.commit()
    conn.close()

    out = run_discrimination(db_path)
    assert out["n_rows"] == 3
    assert out["fusion_n_present_in_log"] == 1
    assert out["fusion_n_missing_in_log"] == 2
