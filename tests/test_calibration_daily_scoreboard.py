"""Daily signal scoreboard: per-horizon fusion prediction vs attached outcome labels."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from calibration.daily_scoreboard import (
    build_daily_scoreboard,
    et_day_utc_bounds,
    render_html,
    write_reports,
)
from calibration.schema import ensure_calibration_schema

ET = ZoneInfo("America/New_York")
ET_DATE = "2026-06-09"


def _mh_bundle(direction_by_hz: dict[str, str], top_prob: float = 0.55) -> str:
    by_hz = {
        hz: {
            "horizon_slug": hz,
            "horizon_fusion_available": True,
            "dominant_direction": d,
            "top_probability": top_prob,
        }
        for hz, d in direction_by_hz.items()
    }
    return json.dumps(
        {"stack_probs_bundle": {"multi_horizon_ml_fusion_bundle": {"by_horizon": by_hz}}}
    )


def _insert_decision(
    conn: sqlite3.Connection,
    ticker: str,
    ts_utc: float,
    model_outputs_json: str,
    outcomes: dict[str, str | None],
) -> None:
    conn.execute(
        """
        INSERT INTO calibration_decision_log (
            decision_ts_utc, ticker, canonical_timeframe, model_outputs_json,
            outcome_1c, outcome_5c, outcome_15c, outcome_60c, calibration_trust
        ) VALUES (?, ?, '1m', ?, ?, ?, ?, ?, 'trusted')
        """,
        (
            ts_utc,
            ticker,
            model_outputs_json,
            outcomes.get("1c"),
            outcomes.get("5c"),
            outcomes.get("15c"),
            outcomes.get("60c"),
        ),
    )


def _fixture_db(tmp_path: Path) -> Path:
    db = tmp_path / "calib.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    ensure_calibration_schema(conn)
    ts0 = datetime(2026, 6, 9, 10, 0, tzinfo=ET).timestamp()

    # SPY row 1: 1c hit (up/up), 5c miss (up/down), 15c flat-pred hit, 60c outcome unattached.
    _insert_decision(
        conn,
        "SPY",
        ts0,
        _mh_bundle({"1c": "up", "5c": "up", "15c": "flat", "60c": "up"}),
        {"1c": "up", "5c": "down", "15c": "flat", "60c": None},
    )
    # SPY row 2: directional hit on 5c.
    _insert_decision(
        conn,
        "SPY",
        ts0 + 60,
        _mh_bundle({"1c": "down", "5c": "down"}),
        {"1c": "flat", "5c": "down"},
    )
    # QQQ row on another ET date: must be excluded.
    other_day = datetime(2026, 6, 8, 10, 0, tzinfo=ET).timestamp()
    _insert_decision(conn, "QQQ", other_day, _mh_bundle({"1c": "up"}), {"1c": "up"})
    # After-hours row on the date (20:00 ET): no snapshot/outcome bar exists — must be excluded.
    after_hours = datetime(2026, 6, 9, 20, 0, tzinfo=ET).timestamp()
    _insert_decision(conn, "SPY", after_hours, _mh_bundle({"1c": "up"}), {"1c": "up"})
    # Untrusted row on the date: must be excluded.
    conn.execute(
        """
        INSERT INTO calibration_decision_log (
            decision_ts_utc, ticker, canonical_timeframe, model_outputs_json,
            outcome_1c, calibration_trust
        ) VALUES (?, 'SPY', '1m', ?, 'up', 'legacy')
        """,
        (ts0 + 120, _mh_bundle({"1c": "up"})),
    )
    conn.commit()
    conn.close()
    return db


def test_et_day_utc_bounds_cover_exactly_one_day():
    lo, hi = et_day_utc_bounds(ET_DATE)
    assert hi - lo == 86400.0
    assert datetime.fromtimestamp(lo, tz=ET).strftime("%Y-%m-%d %H:%M") == "2026-06-09 00:00"


def test_build_daily_scoreboard_scores_per_ticker_and_horizon(tmp_path):
    db = _fixture_db(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)

    spy = sb["by_ticker"]["SPY"]
    # 1c: two scored predictions (up/up hit, down/flat miss) — untrusted row excluded.
    assert spy["1c"]["n_scored"] == 2
    assert spy["1c"]["hits"] == 1
    assert spy["1c"]["accuracy"] == 0.5
    assert spy["1c"]["n_directional"] == 2
    assert spy["1c"]["directional_hits"] == 1
    # 5c: up/down miss + down/down hit.
    assert spy["5c"]["n_scored"] == 2 and spy["5c"]["hits"] == 1
    # 15c: flat prediction scored as hit but not directional.
    assert spy["15c"] == {
        **spy["15c"],
        "n_scored": 1,
        "hits": 1,
        "n_directional": 0,
        "directional_accuracy": None,
    }
    # 60c: prediction logged but outcome not attached -> counted as pred, not scored.
    assert spy["60c"]["n_pred"] == 1 and spy["60c"]["n_scored"] == 0
    # Other ET date excluded entirely.
    assert "QQQ" not in sb["by_ticker"]
    # Rollup mirrors SPY-only contributions on this fixture.
    assert sb["by_horizon"]["1c"]["n_scored"] == 2


def test_write_reports_emit_json_html_and_latest(tmp_path):
    db = _fixture_db(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    out = tmp_path / "reports"
    paths = write_reports(sb, out)
    data = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    assert data["et_date"] == ET_DATE
    html = Path(paths["html"]).read_text(encoding="utf-8")
    assert "Daily signal scoreboard" in html and "SPY" in html
    assert (out / "latest.json").is_file() and (out / "latest.html").is_file()
    # HTML renders percentages for populated cells.
    assert "50.0%" in render_html(sb)


def test_ticker_filter_limits_scope(tmp_path):
    db = _fixture_db(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, tickers=["QQQ"], run_backfill=False)
    assert sb["by_ticker"] == {}
    assert sb["by_horizon"]["1c"]["n_pred"] == 0


def test_backfill_uses_bar_alignment_tolerance(tmp_path, monkeypatch):
    """Live decision_ts_utc is sub-second; snapshots are bar-aligned. tol=0 attaches nothing,
    so build_daily_scoreboard must call backfill with BACKFILL_JOIN_TOL_SEC (<30s, tie-safe)."""
    import calibration.daily_scoreboard as ds

    seen = {}

    def _fake_backfill(db_path, tol_sec):
        seen["tol_sec"] = tol_sec
        return {"updated": 0}

    monkeypatch.setattr(ds, "backfill", _fake_backfill)
    db = _fixture_db(tmp_path)
    ds.build_daily_scoreboard(db, ET_DATE, run_backfill=True)
    assert seen["tol_sec"] == ds.BACKFILL_JOIN_TOL_SEC
    assert 0.0 < ds.BACKFILL_JOIN_TOL_SEC < 30.0
