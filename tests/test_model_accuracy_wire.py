"""Pass 5a — model_accuracy writer + throttled wire + reader round-trip.

EdDB.log_model_accuracy is the writer; maybe_log_model_accuracy throttles
by accuracy_pct delta (MODEL_ACCURACY_DEDUP_EPSILON) so the snapshot only
persists when the value meaningfully changes; get_latest_model_accuracy and
get_model_accuracy_history are the readers (consumed by /api/accuracy and
the ops.html model-accuracy panel in Pass 5b).
"""

from __future__ import annotations

from pathlib import Path


from db import EdDB


def _new_db(tmp_path: Path) -> EdDB:
    return EdDB(tmp_path / "model_accuracy.db")
















# ───────────────────── Pass 5b — ops.html surface presence ─────────────────────


def _insert_pred_row(db: EdDB, *, et_hour: int, et_minute: int, ts: float,
                     up: float, down: float, flat: float, outcome: str) -> None:
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO snapshots (ticker, timeframe, ts_utc, ts_et, spot,"
            " et_hour, et_minute, pred_model_version,"
            " pred_5c_up_prob, pred_5c_down_prob, pred_5c_flat_prob, outcome_5c)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("SPY", "1m", ts, "test", 450.0, et_hour, et_minute, "vtest",
             up, down, flat, outcome),
        )








def test_ops_html_has_model_accuracy_panel() -> None:
    """Lock the ops.html Model accuracy section + JS refresh wire so a
    future ops.html refactor can't silently regress Pass 5b."""
    repo_root = Path(__file__).resolve().parent.parent
    html = (repo_root / "static" / "ops.html").read_text(encoding="utf-8")
    assert "<h3>Model accuracy</h3>" in html, "Model accuracy section missing from ops.html"
    assert 'id="model-acc-card"' in html
    assert 'id="model-acc-title"' in html
    assert "refreshModelAccuracy" in html, "JS refresher missing — panel won't auto-update"
    assert "/api/accuracy?ticker=SPY" in html, "ops panel must read from /api/accuracy"
    assert "setInterval(refreshModelAccuracy, 60000)" in html, "60s auto-refresh missing"


def test_ops_html_has_calibration_health_panel() -> None:
    """Pass 3 sibling lock — both consumer surfaces must remain on the
    ops dashboard. Prevents Pass 5b refactor from breaking Pass 3 visibility."""
    repo_root = Path(__file__).resolve().parent.parent
    html = (repo_root / "static" / "ops.html").read_text(encoding="utf-8")
    assert "<h3>Calibration health</h3>" in html
    assert 'id="cal-health-card"' in html
    assert "refreshCalibrationHealth" in html
    assert "/api/ops/calibration_rowcount" in html
