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


# ── SCOREBOARD_ACTIONABILITY_JOIN_V1 (Phase 1 — report-only) ─────────────────

from calibration.daily_scoreboard import (  # noqa: E402
    ACTIONABILITY_STATES,
    build_actionability_report,
    classify_actionability_rows,
    read_freshness_budget_sec,
    write_actionability_report,
)


def _act_row(ticker: str, ts: float, expiry: str = "2026-06-09") -> dict:
    return {
        "ticker": ticker,
        "decision_ts_utc": ts,
        "expiry": expiry,
        "session_label": "RTH",
        "decision_source": "test",
    }


def test_actionability_state_enum_lock():
    assert ACTIONABILITY_STATES == (
        "ACTIONABLE",
        "STALE",
        "PENDING_NO_BUNDLE",
        "PENDING_KEY_MISMATCH",
        "VETO_WITHHELD",
        "UI_MISMATCH",
        "RUNTIME_ERROR",
        "UNKNOWN",
    )


def test_actionability_reads_live_freshness_budget():
    """Budget = ttl x grace READ from server.py (10.0 today) — never redefined."""
    assert read_freshness_budget_sec() == 10.0
    # Unreadable source fails closed to None.
    assert read_freshness_budget_sec("Z:/definitely/missing/server.py") is None


def test_actionability_gap_arithmetic():
    """8s gap => ACTIONABLE frac 1.0; 40s gap => STALE frac 0.25; tail => UNKNOWN."""
    rows = [_act_row("AAA", 1000.0), _act_row("AAA", 1008.0), _act_row("AAA", 1048.0)]
    out = classify_actionability_rows(rows, 10.0)
    assert [r["state"] for r in out] == ["ACTIONABLE", "STALE", "UNKNOWN"]
    assert out[0]["actionable_fraction"] == 1.0
    assert out[0]["gap_to_next_decision_sec"] == 8.0
    assert out[1]["actionable_fraction"] == 0.25
    assert out[1]["gap_to_next_decision_sec"] == 40.0
    assert out[2]["actionable_fraction"] is None
    assert out[2]["provenance"] == "unknown_no_next_row"
    assert {r["provenance"] for r in out[:2]} == {"gap_arithmetic_inferred"}


def test_actionability_partition_per_ticker_and_expiry():
    """Rows never gap across (ticker, expiry) partitions."""
    rows = [
        _act_row("AAA", 1000.0, "2026-06-09"),
        _act_row("AAA", 1005.0, "2026-06-16"),  # different expiry — separate chain
        _act_row("BBB", 1002.0, "2026-06-09"),  # different ticker — separate chain
    ]
    out = classify_actionability_rows(rows, 10.0)
    assert all(r["state"] == "UNKNOWN" for r in out), "each partition has one row => no gaps"


def test_actionability_unknown_fail_closed_without_budget():
    rows = [_act_row("AAA", 1000.0), _act_row("AAA", 1008.0)]
    out = classify_actionability_rows(rows, None)
    assert all(r["state"] == "UNKNOWN" for r in out)
    assert all(r["provenance"] == "unknown_no_budget" for r in out)


def test_actionability_harness_absence_is_not_ui_proof(tmp_path):
    """No harness artifacts => zero UI/VETO rows AND the report says zero files
    were loaded — absence never proves UI match or veto absence."""
    db = _fixture_db(tmp_path)
    rep = build_actionability_report(
        db, ET_DATE, ui_transport_dir=tmp_path / "no_such_dir"
    )
    assert rep["harness_evidence_files_loaded"] == 0
    assert rep["summary"]["by_state"]["UI_MISMATCH"] == 0
    assert rep["summary"]["by_state"]["VETO_WITHHELD"] == 0
    assert "harness_annotation" not in rep["summary"]["by_provenance"]


def test_actionability_harness_annotation_and_runtime_overlay():
    """Precedence: runtime window > harness annotation > gap arithmetic."""
    rows = [_act_row("AAA", 1000.0), _act_row("AAA", 1008.0), _act_row("AAA", 1016.0)]
    out = classify_actionability_rows(
        rows,
        10.0,
        runtime_error_windows=((1015.0, 1020.0),),
        harness_annotations=(
            {"ticker": "AAA", "ts_lo": 1005.0, "ts_hi": 1010.0, "state": "VETO_WITHHELD"},
        ),
    )
    assert out[0]["state"] == "ACTIONABLE"
    assert out[1]["state"] == "VETO_WITHHELD" and out[1]["provenance"] == "harness_annotation"
    assert out[2]["state"] == "RUNTIME_ERROR" and out[2]["provenance"] == "runtime_window_overlay"


def test_actionability_report_schema_and_write(tmp_path):
    """Golden schema + artifact write (actionability_<date>.json + latest)."""
    db = _fixture_db(tmp_path)
    rep = build_actionability_report(db, ET_DATE, ui_transport_dir=tmp_path / "none")
    assert rep["schema_version"] == "1"
    assert rep["freshness_budget_sec"] == 10.0
    assert rep["states_supported"] == list(ACTIONABILITY_STATES)
    assert set(rep["summary"]) == {"n_rows", "by_state", "by_provenance", "unknown_share", "by_ticker"}
    assert rep["summary"]["n_rows"] == len(rep["rows"]) > 0
    for r in rep["rows"]:
        assert set(r) == {
            "ticker", "decision_ts_utc", "expiry", "session_label", "decision_source",
            "state", "actionable_fraction", "gap_to_next_decision_sec", "provenance",
        }
        assert r["state"] in ACTIONABILITY_STATES
    out = tmp_path / "reports"
    path = write_actionability_report(rep, out)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["et_date"] == ET_DATE
    assert (out / "latest_actionability.json").is_file()


def test_scoreboard_core_schema_v3_contract(tmp_path):
    """v3 (DENOMINATOR_FIRST): all v2 keys preserved; additive denominator-first
    sections present; version bumped."""
    db = _fixture_db(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    v2_keys = {
        "schema_version", "generated_utc", "et_date", "db_path",
        "tickers_filter", "backfill_stats", "by_horizon", "by_ticker",
    }
    assert v2_keys <= set(sb)
    assert set(sb) == v2_keys | {
        "by_horizon_aggregation", "by_horizon_equal_weight", "eligible_grid", "coverage",
        "quality_circle",
    }
    assert sb["schema_version"] == "3"
    assert sb["by_horizon_aggregation"] == "row_weighted_pooled"


def test_live_skill_weight_path_untouched_by_actionability():
    """AST lock: rolling_horizon_log_loss and horizon_skill_weights reference no
    actionability code — the live weighting path is provably unchanged."""
    import ast

    src = Path(__file__).resolve().parent.parent.joinpath(
        "calibration", "daily_scoreboard.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    banned = {
        "classify_actionability_rows", "build_actionability_report",
        "read_freshness_budget_sec", "load_harness_annotations",
        "ACTIONABILITY_STATES",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "rolling_horizon_log_loss", "horizon_skill_weights",
        ):
            names = {s.id for s in ast.walk(node) if isinstance(s, ast.Name)}
            assert not (names & banned), f"{node.name} touches actionability: {names & banned}"


def test_actionability_classifier_no_ticker_literals():
    """AST lock: no uppercase ticker/session literals in the classifier cone."""
    import ast

    src = Path(__file__).resolve().parent.parent.joinpath(
        "calibration", "daily_scoreboard.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    targets = {
        "classify_actionability_rows", "_actionability_decision_rows",
        "read_freshness_budget_sec", "build_actionability_report",
    }
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in targets:
            found.add(node.name)
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    v = sub.value
                    # Uppercase state names / SQL keywords are fine; ticker-shaped
                    # 2-5 char uppercase alpha OUTSIDE the state enum is not.
                    if (
                        v.isalpha() and v.isupper() and 2 <= len(v) <= 5
                        and v not in ("RTH", "UTC", "SELECT", "FROM", "WHERE", "AND", "IN")
                        and v not in ACTIONABILITY_STATES
                    ):
                        raise AssertionError(f"ticker-literal-shaped {v!r} in {node.name}")
    assert found == targets


# ── DAILY_SCOREBOARD_DENOMINATOR_FIRST_V1 (operator-approved 2026-07-09) ──────


def _add_universe(db: Path, tickers: dict[str, str]) -> None:
    """tickers: {ticker: category}. Creates a minimal logging_universe table."""
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS logging_universe (ticker TEXT PRIMARY KEY, category TEXT)"
    )
    for t, cat in tickers.items():
        conn.execute("INSERT OR REPLACE INTO logging_universe VALUES (?, ?)", (t, cat))
    conn.commit()
    conn.close()


def _add_snapshots(db: Path, tickers: list[str], ts_utc: float) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS snapshots (ticker TEXT, ts_utc REAL)"
    )
    for t in tickers:
        conn.execute("INSERT INTO snapshots VALUES (?, ?)", (t, ts_utc))
    conn.commit()
    conn.close()


def _denominator_fixture(tmp_path: Path) -> Path:
    """Base fixture + roster of 4: SPY (rows), ZLOG (snapshots only, no calib rows),
    ZOFF (no producer contact at all), ZGUEST (guest-style with rows)."""
    db = _fixture_db(tmp_path)
    _add_universe(db, {"SPY": "core", "ZLOG": "panel_auto", "ZOFF": "panel_auto", "ZGUEST": "user_persisted"})
    ts0 = datetime(2026, 6, 9, 10, 0, tzinfo=ET).timestamp()
    _add_snapshots(db, ["SPY", "ZLOG", "ZGUEST"], ts0)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    # guest ticker with a scored row (required test 10)
    _insert_decision(
        conn, "ZGUEST", ts0 + 30,
        _mh_bundle({"1c": "up"}), {"1c": "up"},
    )
    conn.commit()
    conn.close()
    return db


def test_denominator_grid_emitted_for_zero_row_tickers(tmp_path):
    """Required 1+2: eligible grid appears even with no rows; zero-row eligible
    ticker carries an explicit reason."""
    db = _denominator_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    grid = sb["eligible_grid"]
    assert "ZLOG" in grid and "ZOFF" in grid  # never hidden
    assert grid["ZLOG"]["1c"]["score_status"] == "NOT_SCORED"
    assert grid["ZLOG"]["1c"]["not_scored_reason"] == "NO_ROWS_PRODUCED"


def test_denominator_not_in_active_logger_label(tmp_path):
    """Required 3: eligible ticker with zero producer contact (no snapshots, no
    calibration rows) is labeled NOT_IN_ACTIVE_LOGGER."""
    db = _denominator_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    cell = sb["eligible_grid"]["ZOFF"]["5c"]
    assert cell["score_status"] == "NOT_SCORED"
    assert cell["not_scored_reason"] == "NOT_IN_ACTIVE_LOGGER"


def test_denominator_fusion_unavailable_label(tmp_path):
    """Required 4: a horizon whose logged bundles never had fusion is labeled."""
    db = _denominator_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    # ZGUEST logged only a 1c block: 5c/15c/60c never had fusion available.
    cell = sb["eligible_grid"]["ZGUEST"]["5c"]
    assert cell["score_status"] == "NOT_SCORED"
    assert cell["not_scored_reason"] == "FUSION_UNAVAILABLE"


def test_denominator_outcome_pending_label(tmp_path):
    """Required 5+8: predictions without attached outcomes are OUTCOME_PENDING,
    visible with counts — not silently discarded (fixture SPY 60c row)."""
    db = _denominator_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    cell = sb["eligible_grid"]["SPY"]["60c"]
    assert cell["n_pred"] == 1 and cell["n_scored"] == 0
    assert cell["score_status"] == "NOT_SCORED"
    assert cell["not_scored_reason"] == "OUTCOME_PENDING"
    assert cell["n_outcome_pending"] == 1


def test_denominator_non_rth_counted_not_scored(tmp_path):
    """Required 6: non-RTH rows excluded from scoring but counted in tallies
    (fixture has an after-hours SPY row; rows_today includes it while n_pred
    reflects RTH-only scoring)."""
    db = _denominator_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    rows_today = sb["coverage"]["rows_per_ticker"]["SPY"]
    scored_1c = sb["eligible_grid"]["SPY"]["1c"]["n_pred"]
    assert rows_today > scored_1c  # after-hours + untrusted rows counted, not scored


def test_denominator_existing_hit_math_preserved(tmp_path):
    """Required 7: v2 scoring numbers are unchanged for scored rows."""
    db = _denominator_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    spy = sb["by_ticker"]["SPY"]
    assert spy["1c"]["n_scored"] == 2 and spy["1c"]["hits"] == 1 and spy["1c"]["accuracy"] == 0.5


def test_denominator_equal_weight_differs_from_pooled(tmp_path):
    """Required 8+9: with unequal row counts (SPY 2 scored, ZGUEST 1 scored on 1c)
    the pooled rollup and the equal-weight rollup differ, and SPY volume cannot
    dominate the equal-weight mean."""
    db = _denominator_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    pooled = sb["by_horizon"]["1c"]["accuracy"]           # (1+1 hits)/(2+1 scored) = 2/3
    ew = sb["by_horizon_equal_weight"]["1c"]
    assert ew["n_tickers"] == 2
    assert ew["mean_accuracy_equal_weight"] == (0.5 + 1.0) / 2   # 0.75
    assert pooled != ew["mean_accuracy_equal_weight"]
    assert sb["by_horizon_aggregation"] == "row_weighted_pooled"


def test_denominator_guest_ticker_scored_identically(tmp_path):
    """Required 10: guest-style roster ticker with valid rows scores through the
    same path with the same cell shape as base tickers."""
    db = _denominator_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    g = sb["eligible_grid"]["ZGUEST"]["1c"]
    assert g["score_status"] == "SCORED" and g["accuracy"] == 1.0
    assert set(g) == set(sb["eligible_grid"]["SPY"]["1c"]) - {"not_scored_reason"} | set(
        k for k in ("not_scored_reason",) if "not_scored_reason" in g
    )


def test_denominator_no_ticker_literals_in_grid_code():
    """Required 11: no ticker literals drive grid/reason/rollup behavior."""
    import ast as _ast

    src_text = Path(__file__).resolve().parent.parent.joinpath(
        "calibration", "daily_scoreboard.py"
    ).read_text(encoding="utf-8")
    tree = _ast.parse(src_text)
    for fname in (
        "_eligible_roster", "_production_tallies", "_cell_not_scored_reason",
        "_build_eligible_grid", "_equal_weight_rollup", "_coverage_diagnostics",
        "_quality_circle_summary",
    ):
        fn = next(n for n in _ast.walk(tree) if isinstance(n, _ast.FunctionDef) and n.name == fname)
        doc = fn.body[0].value if isinstance(fn.body[0], _ast.Expr) else None
        for node in _ast.walk(fn):
            if node is doc:
                continue  # prose docstring, not behavior
            if isinstance(node, _ast.Constant) and isinstance(node.value, str):
                assert not (node.value.isalpha() and node.value.isupper() and len(node.value) <= 5), (
                    f"ticker-literal-shaped constant {node.value!r} in {fname}"
                )


def test_denominator_coverage_diagnostics_exposed(tmp_path):
    """Required 12: coverage block with eligible/with-rows/zero-row/percentages."""
    db = _denominator_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    cov = sb["coverage"]
    assert cov["roster_source"] == "logging_universe"
    assert cov["eligible_tickers"] == 4
    assert cov["tickers_with_rows"] == 2          # SPY + ZGUEST have calib rows
    assert set(cov["zero_row_tickers"]) == {"ZLOG", "ZOFF"}
    assert cov["ticker_coverage_pct"] == 0.5
    assert "1c" in cov["horizon_coverage"] and "rows_per_ticker" in cov


def test_denominator_grid_built_before_scoring_source_lock():
    """Required local proof: the eligible grid/tallies are constructed BEFORE the
    scoring pass inside build_daily_scoreboard."""
    src_text = Path(__file__).resolve().parent.parent.joinpath(
        "calibration", "daily_scoreboard.py"
    ).read_text(encoding="utf-8")
    body = src_text[src_text.index("def build_daily_scoreboard(") :]
    i_roster = body.index("_eligible_roster(conn)")
    i_tallies = body.index("_production_tallies(conn")
    i_scoring = body.index("_per_horizon_prediction_rows(conn")
    assert i_roster < i_scoring and i_tallies < i_scoring


def test_denominator_reasons_enum_complete():
    """Contract: the reasons enum carries all operator-specified labels."""
    from calibration.daily_scoreboard import NOT_SCORED_REASONS

    assert set(NOT_SCORED_REASONS) == {
        "NO_ROWS_PRODUCED", "NOT_IN_ACTIVE_LOGGER", "FUSION_UNAVAILABLE",
        "OUTCOME_PENDING", "NON_RTH", "UNTRUSTED_CALIBRATION",
        "UNPARSEABLE_BUNDLE", "UNSUPPORTED_TICKER_OR_HORIZON",
    }


def test_denominator_untrusted_only_ticker_labeled(tmp_path):
    """A ticker whose only rows today are untrusted -> UNTRUSTED_CALIBRATION."""
    db = _denominator_fixture(tmp_path)
    _add_universe(db, {"ZBAD": "core"})
    ts0 = datetime(2026, 6, 9, 10, 0, tzinfo=ET).timestamp()
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO calibration_decision_log (
            decision_ts_utc, ticker, canonical_timeframe, model_outputs_json,
            outcome_1c, calibration_trust
        ) VALUES (?, 'ZBAD', '1m', ?, 'up', 'legacy')
        """,
        (ts0 + 15, _mh_bundle({"1c": "up"})),
    )
    conn.commit()
    conn.close()
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    cell = sb["eligible_grid"]["ZBAD"]["1c"]
    assert cell["score_status"] == "NOT_SCORED"
    assert cell["not_scored_reason"] == "UNTRUSTED_CALIBRATION"


def test_denominator_unparseable_only_ticker_labeled(tmp_path):
    """A ticker whose only trusted RTH row has garbage JSON -> UNPARSEABLE_BUNDLE."""
    db = _denominator_fixture(tmp_path)
    _add_universe(db, {"ZJSON": "core"})
    ts0 = datetime(2026, 6, 9, 10, 0, tzinfo=ET).timestamp()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    _insert_decision(conn, "ZJSON", ts0 + 20, "{not json", {})
    conn.commit()
    conn.close()
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    cell = sb["eligible_grid"]["ZJSON"]["1c"]
    assert cell["score_status"] == "NOT_SCORED"
    assert cell["not_scored_reason"] == "UNPARSEABLE_BUNDLE"


def test_denominator_non_rth_only_ticker_labeled(tmp_path):
    """A ticker whose only rows today are outside RTH -> NON_RTH."""
    db = _denominator_fixture(tmp_path)
    _add_universe(db, {"ZNIGHT": "core"})
    after_hours = datetime(2026, 6, 9, 20, 30, tzinfo=ET).timestamp()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    _insert_decision(conn, "ZNIGHT", after_hours, _mh_bundle({"1c": "up"}), {"1c": "up"})
    conn.commit()
    conn.close()
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    cell = sb["eligible_grid"]["ZNIGHT"]["1c"]
    assert cell["score_status"] == "NOT_SCORED"
    assert cell["not_scored_reason"] == "NON_RTH"


def test_denominator_html_renders_grid_and_zero_row_tickers(tmp_path):
    """Operator-facing HTML must not hide zero-row eligible tickers."""
    db = _denominator_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    html = render_html(sb)
    assert "Eligible grid" in html and "equal weight per ticker" in html
    assert "ZOFF" in html and "NOT_IN_ACTIVE_LOGGER" in html
    assert "ZLOG" in html and "NO_ROWS_PRODUCED" in html


# ── Quality-circle contract (operator 2026-07-09, item 8) ────────────────────


def test_qc_section_contract(tmp_path):
    """quality_circle carries all item-8 refinement inputs with bounded lists."""
    db = _denominator_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    qc = sb["quality_circle"]
    assert set(qc) == {
        "purpose", "min_scored_for_trust", "worst_tickers_by_accuracy",
        "under_sampled_tickers", "worst_horizons_by_accuracy",
        "lowest_coverage_tickers", "highest_missing_outcome_cells",
        "trusted_cells", "under_sampled_cells",
    }
    for key in (
        "worst_tickers_by_accuracy", "under_sampled_tickers",
        "lowest_coverage_tickers", "highest_missing_outcome_cells",
        "trusted_cells", "under_sampled_cells",
    ):
        blk = qc[key]
        assert {"n_total", "list_limit", "rows"} <= set(blk)
        assert len(blk["rows"]) <= blk["list_limit"]  # truncation never silent


def _qc_trusted_fixture(tmp_path):
    """_denominator_fixture + ZBIG: 30 trusted scored 1c rows (18 hits -> 0.6),
    enough to clear the QC_MIN_SCORED_CELL_N trust floor."""
    from calibration.daily_scoreboard import QC_MIN_SCORED_CELL_N

    db = _denominator_fixture(tmp_path)
    _add_universe(db, {"ZBIG": "core"})
    ts0 = datetime(2026, 6, 9, 10, 30, tzinfo=ET).timestamp()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    n = max(30, QC_MIN_SCORED_CELL_N)
    n_hits = int(round(n * 0.6))
    for i in range(n):
        outcome = "up" if i < n_hits else "down"
        _insert_decision(
            conn, "ZBIG", ts0 + 60 * i, _mh_bundle({"1c": "up"}), {"1c": outcome}
        )
    conn.commit()
    conn.close()
    return db, n, n_hits


def test_qc_worst_ticker_ranking_gated_by_sample_size(tmp_path):
    """Required 2: worst-ticker ranking contains ONLY tickers with trusted cells;
    under-sampled tickers are separated (listed alphabetically, never ranked)."""
    db, n, n_hits = _qc_trusted_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    qc = sb["quality_circle"]
    rows = qc["worst_tickers_by_accuracy"]["rows"]
    assert [r["ticker"] for r in rows] == ["ZBIG"]
    assert abs(rows[0]["mean_accuracy_trusted"] - n_hits / n) < 1e-9
    under = qc["under_sampled_tickers"]["rows"]
    under_tickers = {r["ticker"] for r in under}
    assert {"SPY", "ZGUEST"} <= under_tickers and "ZBIG" not in under_tickers
    assert all(r["trust"] == "UNDER_SAMPLED_NOT_TRUSTWORTHY" for r in under)
    assert [r["ticker"] for r in under] == sorted(r["ticker"] for r in under)


def test_qc_worst_horizon_ranking_gated_by_sample_size(tmp_path):
    """Required 3: horizon ranking uses trusted cells only; horizons with no
    trusted cell are flagged insufficient_sample and rank last, not worst."""
    db, n, n_hits = _qc_trusted_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    hz_rank = sb["quality_circle"]["worst_horizons_by_accuracy"]
    first = hz_rank[0]
    assert first["horizon"] == "1c" and not first["insufficient_sample"]
    assert first["n_tickers_trusted"] == 1
    assert abs(first["mean_accuracy_equal_weight"] - n_hits / n) < 1e-9
    assert first["n_tickers_under_sampled"] >= 2  # SPY + ZGUEST 1c cells separated
    for r in hz_rank[1:]:
        assert r["insufficient_sample"] and r["mean_accuracy_equal_weight"] is None


def test_qc_trusted_cells_populated_over_floor(tmp_path):
    """Required 6 (positive side): a cell at/over the floor lands in trusted_cells."""
    db, n, _ = _qc_trusted_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    qc = sb["quality_circle"]
    trusted = qc["trusted_cells"]["rows"]
    assert any(
        r["ticker"] == "ZBIG" and r["horizon"] == "1c" and r["n_scored"] == n for r in trusted
    )
    assert all(r["n_scored"] < sb["quality_circle"]["min_scored_for_trust"] for r in qc["under_sampled_cells"]["rows"])


def test_qc_does_not_change_scored_math(tmp_path):
    """Required 7: quality_circle is pure post-processing — by_ticker/by_horizon
    values are identical to what the scoring pass produces for the same rows."""
    db, n, n_hits = _qc_trusted_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    spy = sb["by_ticker"]["SPY"]
    assert spy["1c"]["n_scored"] == 2 and spy["1c"]["hits"] == 1 and spy["1c"]["accuracy"] == 0.5
    zbig = sb["by_ticker"]["ZBIG"]["1c"]
    assert zbig["n_scored"] == n and zbig["hits"] == n_hits


def test_qc_board_and_purpose_linkage_present():
    """Required 8: purpose statement + QUALITY_CIRCLE_SIGNAL_REFINEMENT_V1
    dependency linkage exist in the module docstring and OPEN_ITEMS.md."""
    import calibration.daily_scoreboard as ds

    assert "QUALITY CIRCLE PURPOSE" in (ds.__doc__ or "")
    board = Path(__file__).resolve().parent.parent.joinpath("OPEN_ITEMS.md").read_text(
        encoding="utf-8"
    )
    assert "QUALITY_CIRCLE_SIGNAL_REFINEMENT_V1" in board
    assert "DEPENDS ON DAILY_SCOREBOARD_DENOMINATOR_FIRST_V1" in board


def test_qc_trust_split_threshold(tmp_path):
    """Every scored cell lands in exactly one trust bucket; fixture cells
    (n_scored <= 3) all fall under the QC_MIN_SCORED_CELL_N floor."""
    from calibration.daily_scoreboard import QC_MIN_SCORED_CELL_N

    db = _denominator_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    qc = sb["quality_circle"]
    assert QC_MIN_SCORED_CELL_N > 3
    assert qc["trusted_cells"]["n_total"] == 0
    n_scored_cells = sum(
        1
        for cells in sb["eligible_grid"].values()
        for hz, cell in cells.items()
        if cell["n_scored"] > 0
    )
    assert qc["under_sampled_cells"]["n_total"] == n_scored_cells > 0
    assert all(r["n_scored"] < QC_MIN_SCORED_CELL_N for r in qc["under_sampled_cells"]["rows"])


def test_qc_missing_outcome_and_coverage_rankings(tmp_path):
    """SPY 60c (prediction logged, outcome unattached) tops the missing-outcome
    list; zero-row eligible tickers top the lowest-coverage list."""
    db = _denominator_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    qc = sb["quality_circle"]
    pending = qc["highest_missing_outcome_cells"]["rows"]
    assert {"ticker": "SPY", "horizon": "60c", "n_outcome_pending": 1} in pending
    cov = qc["lowest_coverage_tickers"]["rows"]
    worst_two = {cov[0]["ticker"], cov[1]["ticker"]}
    assert worst_two == {"ZLOG", "ZOFF"}
    assert cov[0]["n_horizons_scored"] == 0 and cov[0]["rows_today"] == 0


def test_qc_html_renders_refinement_inputs(tmp_path):
    db = _denominator_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    html = render_html(sb)
    assert "Quality circle" in html and "Worst tickers by mean accuracy" in html
    assert "under-sampled" in html
