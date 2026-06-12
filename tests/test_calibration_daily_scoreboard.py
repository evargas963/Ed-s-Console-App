"""Daily signal scoreboard: per-horizon fusion prediction vs attached outcome labels."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

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


def _mh_json(final_bias: str, primary_horizon: str, final_confidence: float = 0.61) -> str:
    return json.dumps(
        {
            "final_bias": final_bias,
            "final_confidence": final_confidence,
            "primary_horizon": primary_horizon,
            "final_tradeable": final_bias in ("LONG", "SHORT"),
        }
    )


def _insert_decision(
    conn: sqlite3.Connection,
    ticker: str,
    ts_utc: float,
    model_outputs_json: str,
    outcomes: dict[str, str | None],
    multi_horizon_json: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO calibration_decision_log (
            decision_ts_utc, ticker, canonical_timeframe, model_outputs_json,
            multi_horizon_json,
            outcome_1c, outcome_5c, outcome_15c, outcome_60c, calibration_trust
        ) VALUES (?, ?, '1m', ?, ?, ?, ?, ?, ?, 'trusted')
        """,
        (
            ts_utc,
            ticker,
            model_outputs_json,
            multi_horizon_json,
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
    # ALL card: LONG scored at primary 5c (outcome down) -> directional miss.
    _insert_decision(
        conn,
        "SPY",
        ts0,
        _mh_bundle({"1c": "up", "5c": "up", "15c": "flat", "60c": "up"}),
        {"1c": "up", "5c": "down", "15c": "flat", "60c": None},
        multi_horizon_json=_mh_json("LONG", "5c"),
    )
    # SPY row 2: directional hit on 5c. ALL card: SHORT at primary 5c (down) -> hit.
    _insert_decision(
        conn,
        "SPY",
        ts0 + 60,
        _mh_bundle({"1c": "down", "5c": "down"}),
        {"1c": "flat", "5c": "down"},
        multi_horizon_json=_mh_json("SHORT", "5c"),
    )
    # SPY row 3: WAIT decision -> ALL card scores as flat vs 15c outcome flat (non-directional hit).
    _insert_decision(
        conn,
        "SPY",
        ts0 + 90,
        _mh_bundle({}),
        {"15c": "flat"},
        multi_horizon_json=_mh_json("WAIT", "15c"),
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


def test_all_card_row_scores_final_bias_at_primary_horizon(tmp_path):
    """ALL card (trade-entry signal): final_bias vs the logged primary-horizon outcome."""
    db = _fixture_db(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)

    spy_all = sb["by_ticker"]["SPY"]["all"]
    # Row 1 LONG@5c vs down = miss; row 2 SHORT@5c vs down = hit; row 3 WAIT@15c vs flat = hit.
    assert spy_all["n_scored"] == 3
    assert spy_all["hits"] == 2
    assert spy_all["n_directional"] == 2
    assert spy_all["directional_hits"] == 1
    assert spy_all["directional_accuracy"] == 0.5
    # Rollup carries the ALL pseudo-horizon alongside the four product horizons.
    assert sb["by_horizon"]["all"]["n_scored"] == 3
    # final_confidence flows into the mean-confidence diagnostics.
    assert sb["by_horizon"]["all"]["mean_top_prob_on_hits"] == 0.61
    # Rendered report includes the ALL row.
    assert ">all<" in render_html(sb)


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


# ── Rolling skill weights for ALL-card pooling (operator 2026-06-11) ─────────


def _insert_skill_rows(conn: sqlite3.Connection, n: int, ts0: float) -> None:
    """n trusted rows, outcomes attached: 1c predicts truth at p=0.6 (skilled),
    5c/15c/60c uniform 1/3 (zero skill vs ln(3) baseline)."""
    for i in range(n):
        truth = "up" if i % 2 == 0 else "down"
        by_hz = {}
        for hz in ("1c", "5c", "15c", "60c"):
            if hz == "1c":
                probs = {"prob_up": 0.2, "prob_down": 0.2, "prob_flat": 0.2}
                probs[f"prob_{truth}"] = 0.6
            else:
                probs = {"prob_up": 1 / 3, "prob_down": 1 / 3, "prob_flat": 1 / 3}
            by_hz[hz] = {
                "horizon_slug": hz,
                "horizon_fusion_available": True,
                "dominant_direction": truth,
                "top_probability": max(probs.values()),
                **probs,
            }
        mo = json.dumps(
            {"stack_probs_bundle": {"multi_horizon_ml_fusion_bundle": {"by_horizon": by_hz}}}
        )
        conn.execute(
            """
            INSERT INTO calibration_decision_log (
                decision_ts_utc, ticker, canonical_timeframe, model_outputs_json,
                outcome_1c, outcome_5c, outcome_15c, outcome_60c,
                outcomes_attached_ts_utc, calibration_trust
            ) VALUES (?, 'SPY', '1m', ?, ?, ?, ?, ?, ?, 'trusted')
            """,
            (ts0 + i * 60.0, mo, truth, truth, truth, truth, ts0 + i * 60.0 + 900.0),
        )


def test_rolling_horizon_log_loss_and_skill_weights(tmp_path):
    """Bates–Granger pool weights: skilled horizon (NLL < ln 3) wins the weight;
    zero-skill horizons get ~0; under-sampled window fails closed to equal."""
    import math

    from calibration.daily_scoreboard import (
        HORIZON_SLUGS,
        horizon_skill_weights,
        rolling_horizon_log_loss,
    )
    from calibration.fusion_temperature import FIT_WINDOW_FLOOR_UTC

    from time_et import is_rth_ts_utc

    db = tmp_path / "skill.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    ensure_calibration_schema(conn)
    # Anchor inside RTH after the clean-data floor — skill scores RTH rows only.
    ts0 = FIT_WINDOW_FLOOR_UTC + 3600.0
    while not is_rth_ts_utc(ts0):
        ts0 += 60.0
    _insert_skill_rows(conn, 160, ts0)
    # After-hours rows inside the lookback window must NOT enter the skill
    # window (bugbot 2026-06-11: rolling_horizon_log_loss skipped the RTH gate
    # that _per_horizon_prediction_rows applies). Counted, they would inflate n
    # and let stale post-close labels distort live ALL-card pool weights.
    ah_ts = ts0
    while is_rth_ts_utc(ah_ts):
        ah_ts += 3600.0
    _insert_skill_rows(conn, 10, ah_ts)
    conn.commit()
    conn.close()
    now = max(ts0, ah_ts) + 86400.0

    ll = rolling_horizon_log_loss(db, now_ts_utc=now)
    assert ll["1c"]["n"] == 160  # 10 after-hours rows excluded by the RTH gate
    assert ll["1c"]["log_loss"] == pytest.approx(-math.log(0.6))
    assert ll["5c"]["log_loss"] == pytest.approx(math.log(3.0))

    res = horizon_skill_weights(db, now_ts_utc=now)
    assert res["fallback_equal"] is False
    assert res["weights"]["1c"] == pytest.approx(1.0)
    for hz in ("5c", "15c", "60c"):
        assert res["weights"][hz] == pytest.approx(0.0)
    assert sum(res["weights"].values()) == pytest.approx(1.0)

    # Under-sampled (min_rows above row count) → fail-closed equal weights.
    res_eq = horizon_skill_weights(db, now_ts_utc=now, min_rows=500)
    assert res_eq["fallback_equal"] is True
    assert all(res_eq["weights"][hz] == pytest.approx(0.25) for hz in HORIZON_SLUGS)

    # Rows BEFORE the clean-data floor never enter the fit window.
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    _insert_skill_rows(conn, 10, FIT_WINDOW_FLOOR_UTC - 86400.0)
    conn.commit()
    conn.close()
    ll2 = rolling_horizon_log_loss(db, now_ts_utc=now, lookback_days=365.0)
    assert ll2["1c"]["n"] == 160  # poisoned-era rows excluded by the floor


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
