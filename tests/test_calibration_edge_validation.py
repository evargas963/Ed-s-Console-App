"""Edge metrics harness: deterministic stub data must not auto-pass strict directional-alpha gates."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from calibration.edge_validation import analyze_edge
from calibration.schema import ensure_calibration_schema
from calibration.trust import CALIBRATION_TRUST_TRUSTED
from calibration.v2_a1_calibration import axis_reliability_bucket_value
from db import EdDB, configure_sqlite_connection

_CANONICAL_JSON = json.dumps(
    {
        "probability_up": 0.34,
        "probability_down": 0.33,
        "probability_flat": 0.33,
        "confidence": "low",
    }
)


def _seed_regime_slice_fixture_db(db_path: Path) -> list[dict]:
    """Trusted labeled rows with regime_primary in {NULL, '', 'unknown', 'compression'}."""
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    conn.execute(
        """
        INSERT INTO price_bars_1m (ticker, bar_start_ts_utc, bar_end_ts_utc, close, source)
        VALUES ('SPY', 1900.0, 1990.0, 100.0, 'test')
        """
    )
    regimes: list[str | None] = [None, "", "unknown", "compression"]
    seeded: list[dict] = []
    for idx, regime in enumerate(regimes):
        ts = 2000.0 + idx * 10.0
        conn.execute(
            """
            INSERT INTO calibration_decision_log (
                decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
                outcome_5c, outcome_1c, outcome_15c, outcome_60c,
                outcome_1c_pts, outcome_5c_pts, outcome_15c_pts, outcome_60c_pts,
                canonical_json, regime_primary, final_signal
            )
            VALUES (?, 'SPY', '1m', ?, 'up', 'up', 'up', 'up',
                    0.1, 0.2, 0.3, 0.4, ?, ?, 'long')
            """,
            (ts, CALIBRATION_TRUST_TRUSTED, _CANONICAL_JSON, regime),
        )
        seeded.append({"regime_primary": regime, "decision_ts_utc": ts})
    conn.commit()
    conn.close()
    return seeded


def test_analyze_edge_regime_slice_distinguishes_missing_from_unknown(tmp_path: Path) -> None:
    """
    Regression: analyze_edge by_regime_primary slicing (L324) must use axis_reliability_bucket_value.

    Seeds four regime_primary inputs (NULL, '', 'unknown', 'compression'); legacy
    `or "unknown"` would collapse the first three into one 'unknown' slice key.
    """
    db_path = tmp_path / "edge_validation_regime_sentinel.db"
    seeded = _seed_regime_slice_fixture_db(db_path)
    rep = analyze_edge(db_path)
    keys = set(rep["by_regime_primary"].keys())

    assert "__missing__" in keys, "NULL + empty regimes must bucket as __missing__"
    assert "unknown" in keys, "explicit 'unknown' must stay its own bucket"
    assert "compression" in keys
    assert "__missing__" != "unknown"

    by_rp = rep["by_regime_primary"]
    assert by_rp["__missing__"]["n_rows"] == 2
    assert by_rp["unknown"]["n_rows"] == 1
    assert by_rp["compression"]["n_rows"] == 1
    assert len(keys) == 3

    for row in seeded:
        bucket = axis_reliability_bucket_value(row["regime_primary"])
        assert by_rp[bucket]["n_rows"] >= 1


def test_edge_validation_stub_fails_strict_alpha_same_as_always_long(tmp_path: Path) -> None:
    """CI stub: dominant canonical class ties to 'up' → effective signal equals always-long; strict EV gate fails."""
    db = Path(__file__).resolve().parents[1] / "data" / "calibration_accumulation_validation.db"
    if not db.is_file():
        pytest.skip("run python -m calibration.run_production_accumulation_validation first")
    rep = analyze_edge(db)
    assert rep["pass_gates"]["aggregate_n_sufficient"] is True
    assert rep["pass_gates"]["ev_mean_actual_gt_mean_random_mix"] is True
    assert rep["pass_gates"]["ev_mean_actual_strictly_gt_always_long"] is False
    assert rep["binary_pass"] is False
