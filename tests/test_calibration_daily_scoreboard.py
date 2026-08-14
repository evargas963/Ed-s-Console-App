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


def test_scoreboard_core_schema_v4_contract(tmp_path):
    """v4 (SCOREBOARD_TARGET_TRUTH_V1): every v2 AND v3 key preserved byte-for-key;
    additive v4 sections present; version bumped. No silent semantic replacement."""
    db = _fixture_db(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    v2_keys = {
        "schema_version", "generated_utc", "et_date", "db_path",
        "tickers_filter", "backfill_stats", "by_horizon", "by_ticker",
    }
    v3_keys = {
        "by_horizon_aggregation", "by_horizon_equal_weight", "eligible_grid", "coverage",
        "quality_circle",
    }
    v4_keys = {
        "by_horizon_extended", "by_ticker_extended", "all_card",
        "metric_definitions", "source_identity",
    }
    assert v2_keys <= set(sb)
    assert set(sb) == v2_keys | v3_keys | v4_keys
    assert sb["schema_version"] == "4"
    assert sb["by_horizon_aggregation"] == "row_weighted_pooled"
    # Legacy v2 cell shape unchanged (historical reproducibility).
    assert set(sb["by_horizon"]["1c"]) == {
        "n_pred", "n_scored", "hits", "accuracy", "n_directional", "directional_hits",
        "directional_accuracy", "mean_top_prob_on_hits", "mean_top_prob_on_misses",
    }


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


# ── SCOREBOARD_TARGET_TRUTH_V1 (v4) — abstention, baselines, warnings ─────────

from calibration.daily_scoreboard import (  # noqa: E402
    DIRECTIONAL_MIN_N,
    JOIN_COHORTS,
    NEAR_CONSTANT_SHARE,
    SCOREBOARD_WARNINGS,
    WARN_MIN_N,
    _all_card_trade_metrics,
    _finalize_v4_cell,
    _join_identity_cohort,
    _new_v4_cell,
    _v4_accumulate,
    _v4_cell_warnings,
)


def _v4_row(pred: str, truth: str | None, hz: str = "1c", ts: float = 1000.0, **kw) -> dict:
    return {
        "ticker": "ZZZ", "decision_ts_utc": ts, "horizon": hz, "pred": pred,
        "truth": truth, "top_probability": 0.5,
        "join_cohort": kw.get("join_cohort", "exact_timestamp"),
        "bundle_identity_proven": kw.get("bundle_identity_proven", True),
    }


def _v4_fin(rows: list[dict]) -> dict:
    cell = _new_v4_cell()
    for r in rows:
        _v4_accumulate(cell, r)
    return _finalize_v4_cell(cell)


def test_all_card_wait_is_abstention_not_flat_prediction(tmp_path):
    """Required 1+4: WAIT rows are excluded from trade-call accuracy and reported
    as abstention with a descriptive outcome distribution."""
    rows = [
        _v4_row("up", "up"), _v4_row("down", "down"),           # LONG hit, SHORT hit
        _v4_row("up", "down"),                                   # LONG miss
        _v4_row("flat", "up"), _v4_row("flat", "flat"), _v4_row("flat", None),  # WAIT x3
    ]
    m = _all_card_trade_metrics(rows)
    assert m["n_long"] == 2 and m["n_short"] == 1 and m["n_wait"] == 3
    assert m["abstention_rate"] == 0.5
    assert m["combined_trade_calls"]["n_scored"] == 3          # WAIT never counted
    assert m["combined_trade_calls"]["accuracy"] == pytest.approx(2 / 3)
    assert m["outcome_distribution_during_wait"]["n_scored"] == 2
    assert m["outcome_distribution_during_wait"]["distribution"]["up"] == 1
    assert "abstention" in m["contract"]


def test_all_card_long_short_mapping_for_trade_calls():
    """Required 2+3: LONG maps to up, SHORT maps to down in trade-call scoring."""
    rows = [_v4_row("up", "up"), _v4_row("down", "down")]
    m = _all_card_trade_metrics(rows)
    assert m["long"]["hits"] == 1 and m["long"]["accuracy"] == 1.0
    assert m["short"]["hits"] == 1 and m["short"]["accuracy"] == 1.0


def test_all_card_legacy_triclass_retained_and_deprecated(tmp_path):
    """Required 5: legacy ALL triclass metric stays reproducible in by_horizon['all']
    and is explicitly labeled LEGACY_INVALID_FOR_TRADE_EDGE."""
    db = _fixture_db(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    assert sb["by_horizon"]["all"]["n_scored"] == 3            # legacy math unchanged
    assert sb["all_card"]["legacy_triclass_reference"]["label"] == "LEGACY_INVALID_FOR_TRADE_EDGE"
    assert any(
        "by_horizon['all']" in x for x in sb["metric_definitions"]["legacy_invalid_for_trade_edge"]
    )
    # v4 trade-call view of the same fixture: LONG miss + SHORT hit; WAIT excluded.
    ac = sb["all_card"]
    assert ac["n_wait"] == 1 and ac["combined_trade_calls"]["n_scored"] == 2
    assert ac["combined_trade_calls"]["hits"] == 1


def test_all_card_primary_horizon_fail_closed(tmp_path):
    """Required 6+7+12: a decision without a persisted decision-time primary horizon
    is never scored (no current-config substitution) and is counted + warned."""
    db = _fixture_db(tmp_path)
    ts0 = datetime(2026, 6, 9, 11, 0, tzinfo=ET).timestamp()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    _insert_decision(
        conn, "SPY", ts0,
        _mh_bundle({"1c": "up"}), {"1c": "up"},
        multi_horizon_json=json.dumps({"final_bias": "LONG"}),  # NO primary_horizon
    )
    conn.commit()
    conn.close()
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    assert sb["all_card"]["n_primary_horizon_identity_not_proven"] >= 1
    assert "PRIMARY_HORIZON_IDENTITY_NOT_PROVEN" in sb["all_card"]["warnings"]
    # Not scored as an ALL row: legacy 'all' cell count unchanged from base fixture.
    assert sb["by_horizon"]["all"]["n_scored"] == 3


def test_all_card_row_reads_only_persisted_row_fields():
    """Required 7 (AST lock): _all_card_row consumes ONLY the database row — no
    import/config fallback can substitute current configuration for history."""
    import ast

    src = Path(__file__).resolve().parent.parent.joinpath(
        "calibration", "daily_scoreboard.py"
    ).read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "_all_card_row"
    )
    names = {x.id for x in ast.walk(fn) if isinstance(x, ast.Name)}
    allowed = {"row", "mh", "pred", "primary_hz", "json", "isinstance", "dict", "str",
               "float", "Optional", "_FINAL_BIAS_TO_LABEL", "HORIZON_SLUGS", "ALL_CARD_SLUG",
               "TypeError", "ValueError", "Any", "sqlite3"}
    assert names <= allowed, f"unexpected names in _all_card_row: {names - allowed}"
    # The load-bearing lock: no config/roster/horizon-selection machinery inside.
    banned = {"PRIMARY_DECISION_HORIZONS", "load_movement_thresholds_by_horizon_v1",
              "_eligible_roster", "os", "importlib"}
    assert not (names & banned)


def test_v4_confusion_matrix_and_class_metrics():
    """Required 19-22: 3x3 confusion, balanced accuracy, macro F1, distributions."""
    rows = [
        _v4_row("up", "up"), _v4_row("up", "down"),
        _v4_row("down", "down"), _v4_row("flat", "flat"),
        _v4_row("flat", "up"),
    ]
    fin = _v4_fin(rows)
    assert fin["n_scored"] == 5
    assert fin["confusion_matrix"]["up"]["down"] == 1
    assert fin["confusion_matrix"]["flat"]["up"] == 1
    assert fin["pred_distribution"] == {"up": 2, "down": 1, "flat": 2}
    assert fin["truth_distribution"] == {"up": 2, "down": 2, "flat": 1}
    assert fin["accuracy"] == pytest.approx(3 / 5)
    # recalls: up 1/2, down 1/2, flat 1/1 -> balanced 2/3
    assert fin["balanced_accuracy"] == pytest.approx((0.5 + 0.5 + 1.0) / 3)
    assert fin["macro_f1"] is not None and fin["mcc"] is not None


def test_v4_baselines_and_directional_split():
    """Required 23-26: always-flat + majority baselines; directional-called vs
    both-nonflat directional accuracy are distinct metrics."""
    rows = [
        _v4_row("up", "flat"), _v4_row("up", "up"), _v4_row("down", "flat"),
        _v4_row("flat", "flat"),
    ]
    fin = _v4_fin(rows)
    assert fin["baselines"]["always_flat"] == pytest.approx(3 / 4)
    assert fin["baselines"]["majority_class"] == pytest.approx(3 / 4)
    dc = fin["directional_called"]
    assert dc["n"] == 3 and dc["hits"] == 1 and dc["accuracy"] == pytest.approx(1 / 3)
    bn = fin["both_nonflat_directional"]
    assert bn["n"] == 1 and bn["hits"] == 1 and bn["accuracy"] == 1.0


def test_v4_collapse_and_baseline_warnings():
    """Required 25+27+28: LOSES_TO_ALWAYS_FLAT, ALWAYS_FLAT_CLASSIFIER and
    NEAR_CONSTANT_CLASSIFIER fire mechanically from the data."""
    flat_rows = [_v4_row("flat", "flat" if i % 3 else "up") for i in range(WARN_MIN_N + 2)]
    fin = _v4_fin(flat_rows)
    w = _v4_cell_warnings(fin, [])
    assert "ALWAYS_FLAT_CLASSIFIER" in w
    near = [_v4_row("up", "down") for _ in range(19)] + [_v4_row("down", "down")]
    fin2 = _v4_fin(near)
    w2 = _v4_cell_warnings(fin2, [])
    assert "NEAR_CONSTANT_CLASSIFIER" in w2
    assert "LOSES_TO_ALWAYS_FLAT" not in w2 or fin2["baselines"]["always_flat"] > fin2["accuracy"]
    lose = [_v4_row("up", "flat") for _ in range(WARN_MIN_N)]
    w3 = _v4_cell_warnings(_v4_fin(lose), [])
    assert "LOSES_TO_ALWAYS_FLAT" in w3 and "LOSES_TO_MAJORITY" in w3


def test_v4_sample_size_warnings():
    """Required 29-31: small directional sample, under-sampled cell, and
    effective-sample (overlapping windows) warnings."""
    rows = [_v4_row("up", "up", hz="60c", ts=1000.0 + i) for i in range(5)]
    fin = _v4_fin(rows)                       # 5 rows inside ONE 60c window
    assert fin["n_independent_windows"] == 1
    w = _v4_cell_warnings(fin, [])
    assert "DIRECTIONAL_SAMPLE_TOO_SMALL" in w
    assert "UNDER_SAMPLED" in w
    assert "EFFECTIVE_SAMPLE_NOT_PROVEN" in w
    assert DIRECTIONAL_MIN_N >= 30 and WARN_MIN_N >= 10 and 0.5 < NEAR_CONSTANT_SHARE < 1.0


def test_v4_identity_cohort_classification_and_warnings():
    """Required 8-11+32+33: identity > exact > nearest-earlier/later cohorts;
    inferred/unknown cohorts and missing bundle identity raise warnings."""
    class _R(dict):
        def __getitem__(self, k):  # sqlite3.Row-style access
            return dict.__getitem__(self, k)

    assert _join_identity_cohort(_R({"outcome_join_method": "identity",
                                     "matched_snapshot_ts_utc": 5.0, "decision_ts_utc": 9.0})) == "identity"
    assert _join_identity_cohort(_R({"outcome_join_method": "exact",
                                     "matched_snapshot_ts_utc": 9.0, "decision_ts_utc": 9.0})) == "exact_timestamp"
    assert _join_identity_cohort(_R({"outcome_join_method": "nearest_within_tol",
                                     "matched_snapshot_ts_utc": 5.0, "decision_ts_utc": 9.0})) == "nearest_earlier"
    assert _join_identity_cohort(_R({"outcome_join_method": "nearest_within_tol",
                                     "matched_snapshot_ts_utc": 12.0, "decision_ts_utc": 9.0})) == "nearest_later"
    assert _join_identity_cohort(_R({"outcome_join_method": None,
                                     "matched_snapshot_ts_utc": None, "decision_ts_utc": 9.0})) == "unknown_join"
    rows = [
        _v4_row("up", "up", join_cohort="nearest_earlier", bundle_identity_proven=False),
        _v4_row("up", "up", join_cohort="identity"),
    ]
    fin = _v4_fin(rows)
    assert fin["identity_cohorts"]["nearest_earlier"] == 1
    assert fin["identity_cohorts"]["identity"] == 1
    w = _v4_cell_warnings(fin, [])
    assert "TIMESTAMP_IDENTITY_NOT_PROVEN" in w
    assert "BUNDLE_IDENTITY_NOT_PROVEN" in w
    assert set(JOIN_COHORTS) == {
        "identity", "exact_timestamp", "nearest_earlier", "nearest_later", "unknown_join"
    }


def test_v4_placeholder_threshold_disclosure_from_committed_config(tmp_path):
    """Required 13-15: the committed threshold config is a placeholder — the report
    must mechanically disclose PLACEHOLDER_THRESHOLD_IN_USE with source hash."""
    db = _fixture_db(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    ts = sb["source_identity"]["threshold_source"]
    assert "PLACEHOLDER_THRESHOLD_IN_USE" in ts["warning_flags"]
    assert ts["source_sha256"] and ts["units"].startswith("price points")
    for hz in ("1c", "5c", "15c", "60c"):
        assert ts["per_horizon"][hz]["ratified"] is False
    # The flag propagates into every extended cell's warning list.
    for cell in sb["by_horizon_extended"].values():
        assert "PLACEHOLDER_THRESHOLD_IN_USE" in cell["warnings"]


def test_v4_no_descriptive_metric_claims_validity(tmp_path):
    """Required 44: standing NOT_PROVEN disclosures are embedded; nothing in the
    v4 schema asserts predictive validity or calibration validity."""
    db = _fixture_db(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    md = sb["metric_definitions"]
    joined = " ".join(md["standing_not_proven_disclosures"])
    for tok in ("OUTCOME_LINEAGE_NOT_PROVEN", "CALIBRATION_NOT_PROVEN",
                "TRAIN_LIVE_PARITY_NOT_PROVEN", "LEAKAGE_ABSENCE_NOT_PROVEN"):
        assert tok in joined
    assert set(md["warnings_supported"]) == set(SCOREBOARD_WARNINGS)
    dumped = json.dumps(sb)
    assert "PREDICTIVE_VALIDITY = PROVEN" not in dumped
    assert sb["source_identity"]["horizon_outcome_schema_version"] == 3


def test_v4_universal_ticker_and_horizon_construction(tmp_path):
    """Required 41-43: extended cells exist for every scored ticker x horizon with
    identical shape (base or guest), and no ticker literal drives v4 behavior."""
    db = _denominator_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    assert set(sb["by_ticker_extended"]["SPY"]["1c"]) == set(
        sb["by_ticker_extended"]["ZGUEST"]["1c"]
    )
    import ast as _ast

    src_text = Path(__file__).resolve().parent.parent.joinpath(
        "calibration", "daily_scoreboard.py"
    ).read_text(encoding="utf-8")
    tree = _ast.parse(src_text)
    for fname in (
        "_new_v4_cell", "_v4_accumulate", "_finalize_v4_cell", "_v4_cell_warnings",
        "_all_card_trade_metrics", "_threshold_source_identity", "_join_identity_cohort",
    ):
        fn = next(n for n in _ast.walk(tree) if isinstance(n, _ast.FunctionDef) and n.name == fname)
        doc = fn.body[0].value if isinstance(fn.body[0], _ast.Expr) else None
        for node in _ast.walk(fn):
            if node is doc:
                continue
            if isinstance(node, _ast.Constant) and isinstance(node.value, str):
                v = node.value
                assert not (v.isalpha() and v.isupper() and 2 <= len(v) <= 5 and v not in ("LONG", "SHORT", "WAIT")), (
                    f"ticker-literal-shaped constant {v!r} in {fname}"
                )


def test_v4_invalid_threshold_fallback_risk_true_case(tmp_path, monkeypatch):
    """Phase-5 forward contract: a horizon missing from the threshold config is a
    fallback risk — the flag fires mechanically and rides every extended cell so
    an invalid-threshold label can never contribute to trusted accuracy silently."""
    import movement_target_threshold as mtt

    crippled = {"version": 2, "notes": "test", "horizons": {"1c": {"threshold_move_pts": 0.04, "selected_percentile": 5}}}
    monkeypatch.setattr(mtt, "load_movement_thresholds_by_horizon_v1", lambda path=None: crippled)
    db = _fixture_db(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    flags = sb["source_identity"]["threshold_source"]["warning_flags"]
    assert "INVALID_THRESHOLD_FALLBACK_RISK" in flags
    assert "PLACEHOLDER_THRESHOLD_IN_USE" in flags  # 60c unratified/missing
    for cell in sb["by_horizon_extended"].values():
        assert "INVALID_THRESHOLD_FALLBACK_RISK" in cell["warnings"]


def test_v4_invalid_threshold_rows_excluded_from_every_trusted_metric(tmp_path, monkeypatch):
    """Mandatory pre-proof correction (adversarial): a horizon whose governed
    threshold is invalid contributes to NO trusted v4 metric — not n_scored, not
    accuracy/balanced/F1/MCC, not confusion, not directional metrics, not
    baselines. Rows land in a disclosed invalid-target cohort; the historical
    legacy cell stays reproducible."""
    import movement_target_threshold as mtt

    crippled = {
        "version": 2, "notes": "test",
        "horizons": {
            "1c": {"threshold_move_pts": 0.04, "selected_percentile": 5},
            "5c": {"threshold_move_pts": 0.12, "selected_percentile": 5},
            "15c": {"threshold_move_pts": 0.26, "selected_percentile": 5},
            "60c": {"threshold_move_pts": -1.0, "selected_percentile": None},  # invalid
        },
    }
    monkeypatch.setattr(mtt, "load_movement_thresholds_by_horizon_v1", lambda path=None: crippled)
    db = _fixture_db(tmp_path)
    ts0 = datetime(2026, 6, 9, 12, 0, tzinfo=ET).timestamp()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    _insert_decision(conn, "SPY", ts0, _mh_bundle({"60c": "flat"}), {"60c": "flat"})
    conn.commit()
    conn.close()
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    ext = sb["by_horizon_extended"]["60c"]
    assert ext["n_scored"] == 0 and ext["n_pred"] == 0
    assert ext["accuracy"] is None and ext["balanced_accuracy"] is None
    assert ext["mcc"] is None and ext["macro_f1"] is None
    assert all(v == 0 for row in ext["confusion_matrix"].values() for v in row.values())
    assert ext["directional_called"]["n"] == 0 and ext["both_nonflat_directional"]["n"] == 0
    assert ext["baselines"] == {"always_flat": None, "majority_class": None}
    cohort = ext["invalid_target_cohort"]
    assert cohort["n_rows_excluded_from_trusted_scoring"] == 2  # fixture 60c pred + new scored row
    assert "INVALID_THRESHOLD_FALLBACK_RISK" in ext["warnings"]
    assert "60c" in sb["source_identity"]["threshold_source"]["invalid_horizons"]
    assert sb["source_identity"]["threshold_source"]["per_horizon"]["60c"]["invalid"] is True
    # Historical legacy cell preserved for reproducibility (raw value retained).
    assert sb["by_horizon"]["60c"]["n_scored"] == 1
    # No SPY 60c extended cell was created at all.
    assert "60c" not in sb["by_ticker_extended"].get("SPY", {})


def test_invalid_threshold_classification_is_flat_and_disclosed():
    """Historical behavior preserved and DISCLOSED: classify_direction_pts turns a
    missing/non-positive threshold into 'flat'. The forward fail-closed change to
    the truth writer (no-label instead of flat) belongs to the target-redesign
    mission; until then the risk flag is the governed disclosure."""
    from math_probabilities import classify_direction_pts

    assert classify_direction_pts(5.0, None) == "flat"
    assert classify_direction_pts(5.0, 0.0) == "flat"
    assert classify_direction_pts(5.0, -1.0) == "flat"
    assert classify_direction_pts(5.0, 1.0) == "up"


def test_v4_clean_cell_raises_no_warnings_false_cases():
    """False-case proof for every cell-level warning: a healthy cell (identity
    joins, proven bundles, >=30 directional rows in distinct windows, mixed
    classes, beats both baselines) produces an empty warning list."""
    rows = []
    for i in range(36):
        pred = ("up", "down", "flat")[i % 3]
        truth = pred if i % 4 else ("down" if pred == "up" else "up")  # 75% acc, mixed
        rows.append(_v4_row(pred, truth, hz="1c", ts=1000.0 + i * 60.0,
                            join_cohort="identity", bundle_identity_proven=True))
    fin = _v4_fin(rows)
    assert fin["n_scored"] == 36 and fin["n_independent_windows"] == 36
    assert fin["directional_called"]["n"] >= DIRECTIONAL_MIN_N - 6  # 24 directional
    w = _v4_cell_warnings(fin, [])
    # Directional n is 24 (<30) by construction of the 3-class rotation — the
    # ONLY expected warning; every other predicate is exercised false.
    assert w == ["DIRECTIONAL_SAMPLE_TOO_SMALL"]
    dir_rows = [
        _v4_row(("up", "down")[i % 2], ("up", "down")[i % 2] if i % 4 else ("down", "up")[i % 2],
                hz="1c", ts=2000.0 + i * 60.0, join_cohort="identity")
        for i in range(40)
    ]
    fin2 = _v4_fin(dir_rows)
    assert _v4_cell_warnings(fin2, []) == []   # zero warnings on a fully healthy cell


def test_v4_equal_ticker_and_row_weighted_remain_separate(tmp_path):
    """Required 38: the v3 equal-weight rollup and row-weighted pooled rollup are
    both present and unchanged by the v4 additions."""
    db = _denominator_fixture(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    assert sb["by_horizon_aggregation"] == "row_weighted_pooled"
    assert sb["by_horizon_equal_weight"]["1c"]["mean_accuracy_equal_weight"] == (0.5 + 1.0) / 2


# ── DEFECT-1: operator semantic safety (independent requirements) ─────────────
# These tests assert the REQUIRED CONCEPTS as independent strings — they do NOT
# import the production display-contract constants and echo them back.

import re as _re  # noqa: E402
import sys  # noqa: E402


def _plain_text(html: str) -> str:
    """CSS/markup-independent extraction: what a screen reader / copy-paste sees."""
    return _re.sub(r"<[^>]+>", " ", html)


def test_defect1_legacy_all_display_is_semantically_qualified(tmp_path):
    """Tests 1-4+12: the rendered LEGACY ALL metric states legacy status, triclass
    treatment, WAIT-as-scored-class, and historical-only purpose — surviving
    plain-text extraction (no reliance on CSS/color/position)."""
    db = _fixture_db(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    text = _plain_text(render_html(sb)).lower()
    assert "legacy" in text
    assert "triclass (up/down/flat" in text  # explicit treatment phrase, not just the name
    assert "wait scored as a flat-price class" in text
    assert "historical reproduction and comparison only" in text
    assert "not comparable to governed v4 trade-call accuracy" in text
    # The legacy row itself is labeled, not just a distant paragraph.
    assert "all — legacy all triclass accuracy" in text


def test_defect1_governed_trade_call_display_contract(tmp_path):
    """Tests 5-7: governed v4 accuracy renders under its OWN heading with coverage
    and eligible call counts in the same section."""
    db = _fixture_db(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    text = _plain_text(render_html(sb)).lower()
    assert "governed trade-call accuracy (schema v4)" in text
    assert "trade-call coverage" in text
    assert "abstention" in text
    assert "long 1 / short 1 / wait 1" in text
    assert "not sufficient evidence of predictive edge" in text


def test_defect1_zero_call_safety_in_render():
    """Test 8: zero eligible trade calls must not display a misleading accuracy."""
    from calibration.daily_scoreboard import _all_card_trade_metrics, render_html as _rh

    sb_min = {
        "et_date": "2026-06-09",
        "by_horizon": {},
        "by_ticker": {},
        "all_card": _all_card_trade_metrics(
            [{"ticker": "Z", "decision_ts_utc": 1.0, "horizon": "all", "pred": "flat",
              "truth": "flat", "top_probability": 0.5, "join_cohort": "identity",
              "bundle_identity_proven": True}]
        ),
        "by_horizon_extended": {},
    }
    text = _plain_text(_rh(sb_min)).lower()
    assert "no scored trade calls" in text
    assert "accuracy not applicable" in text


def test_defect1_warnings_and_invalid_cohorts_render(tmp_path, monkeypatch):
    """Tests 9-10: v4 warnings and invalid-target cohorts reach the operator."""
    import movement_target_threshold as mtt

    crippled = {
        "version": 2, "notes": "test",
        "horizons": {
            "1c": {"threshold_move_pts": 0.04, "selected_percentile": 5},
            "5c": {"threshold_move_pts": 0.12, "selected_percentile": 5},
            "15c": {"threshold_move_pts": 0.26, "selected_percentile": 5},
            "60c": {"threshold_move_pts": None, "selected_percentile": None},
        },
    }
    monkeypatch.setattr(mtt, "load_movement_thresholds_by_horizon_v1", lambda path=None: crippled)
    db = _fixture_db(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    text = _plain_text(render_html(sb))
    assert "Invalid-target cohorts" in text
    assert "labels untrusted" in text
    assert "Per-horizon v4 warnings" in text
    assert "INVALID_THRESHOLD_FALLBACK_RISK" in text


def test_defect1_no_shared_unqualified_heading(tmp_path):
    """Test 11: legacy and governed metrics never share one unqualified 'accuracy'
    heading — every h2 that mentions the pooled table carries legacy semantics."""
    db = _fixture_db(tmp_path)
    html = render_html(build_daily_scoreboard(db, ET_DATE, run_backfill=False))
    headings = _re.findall(r"<h2>(.*?)</h2>", html)
    pooled = [h for h in headings if "by horizon" in h.lower()]
    assert pooled and all("legacy metric semantics" in h.lower() for h in pooled)
    governed = [h for h in headings if "governed trade-call" in h.lower()]
    assert len(governed) == 1


def test_defect1_console_renderer_carries_contracts(tmp_path, monkeypatch, capsys):
    """The console/log summary (second operator surface found in discovery) must
    carry the same canonical semantic contracts."""
    import calibration.daily_scoreboard as ds

    db = _fixture_db(tmp_path)
    monkeypatch.setattr(
        sys, "argv",
        ["daily_scoreboard", "--db", str(db), "--date", ET_DATE, "--no-backfill",
         "--out-dir", str(tmp_path / "out"), "--allow-noncanonical-db"],
    )
    monkeypatch.setattr(ds, "require_canonical_db_target", lambda *a, **k: None)
    assert ds.main() == 0
    out = capsys.readouterr().out.lower()
    assert "by_horizon_legacy_semantics" in out
    assert "legacy" in out and "triclass" in out
    assert "governed_trade_call" in out and "trade_call_coverage" in out


# ── V2 (Cursor findings): eligible grid, governed unit, low-coverage safety ───


def test_v2_eligible_grid_all_cell_cannot_read_as_governed_accuracy(tmp_path):
    """DEFECT-A regression (Cursor case: 66.7% (n=3) under <th>all</th>): the grid
    'all' column heading AND every scored 'all' cell are structurally qualified;
    the numeric value is preserved; a copied single row keeps the qualification."""
    db = _fixture_db(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    assert sb["by_ticker"]["SPY"]["all"]["accuracy"] == pytest.approx(2 / 3)  # numeric preserved
    html = render_html(sb)
    assert "<th scope=\"col\">all — Legacy ALL triclass accuracy" in html
    assert "<th scope=\"col\">all</th>" not in html
    grid_rows = [seg for seg in html.split("<tr>") if seg.startswith("<td>SPY</td>")]
    grid_row = next(seg for seg in grid_rows if "legacy triclass, not trade-call accuracy" in seg)
    assert "66.7%" in grid_row and "(n=3)" in grid_row
    # Caption binds the semantics to the table structure itself.
    assert "<caption>Eligible grid: per-cell LEGACY triclass accuracy" in html
    # Plain-text extraction of just the row keeps the qualification.
    assert "legacy triclass" in _plain_text(grid_row)


def test_v2_governed_unit_colocates_target_threshold_validity(tmp_path):
    """DEFECT-B: the all_card JSON unit and its rendered section both carry
    target/threshold validity; placeholder targets read as untrusted evidence."""
    db = _fixture_db(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    v = sb["all_card"]["target_threshold_validity"]
    assert v["configuration_status"] == "PLACEHOLDER"  # committed placeholder config
    assert "NOT trusted trade-edge evidence" in v["statement"]
    assert v["trade_edge_validity"].startswith("NOT_PROVEN")
    assert v["target_economic_validity"].startswith("NOT_PROVEN")
    assert v["per_horizon"]["60c"]["ratified"] is False
    assert "PLACEHOLDER_THRESHOLD_IN_USE" in sb["all_card"]["warnings"]
    text = _plain_text(render_html(sb))
    assert "Target/threshold validity:" in text
    assert "NOT trusted trade-edge evidence" in text


def test_v3_ratified_config_never_inflates_target_validity(tmp_path, monkeypatch):
    """Phase-8 mutation: a fully ratified threshold config must NOT let the
    display claim proven target validity — configuration status and target
    validity are separate axes; parents stay NOT_PROVEN."""
    import movement_target_threshold as mtt

    ratified = {
        "version": 2, "notes": "governed",
        "horizons": {
            hz: {"threshold_move_pts": pts, "selected_percentile": 60, "invalid_for_dir_target": False}
            for hz, pts in (("1c", 0.04), ("5c", 0.12), ("15c", 0.26), ("60c", 0.65))
        },
    }
    monkeypatch.setattr(mtt, "load_movement_thresholds_by_horizon_v1", lambda path=None: ratified)
    db = _fixture_db(tmp_path)
    sb = build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    v = sb["all_card"]["target_threshold_validity"]
    assert v["configuration_status"] == "GOVERNED_RATIFIED"
    assert v["target_economic_validity"].startswith("NOT_PROVEN")
    assert v["trade_edge_validity"].startswith("NOT_PROVEN")
    assert "NOT a claim of target economic validity" in v["statement"]
    text = _plain_text(render_html(sb))
    assert "validity PROVEN" not in text
    assert "NOT a claim of target economic validity" in text


def test_v3_production_paths_fail_closed_on_contract_violation(tmp_path, monkeypatch, capsys):
    """Phase-5: every production emission path (render_html, write_reports,
    main/console) refuses to emit when contracts and behavior disagree; no file
    is written and no stale 'latest' is overwritten."""
    import calibration.daily_scoreboard as ds

    db = _fixture_db(tmp_path)
    sb = ds.build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    bad = dict(ds.LEGACY_ALL_DISPLAY_CONTRACT)
    bad["intended_use"] = "general evaluation"  # breaks the historical-only invariant
    monkeypatch.setattr(ds, "LEGACY_ALL_DISPLAY_CONTRACT", bad)
    with pytest.raises(ds.DisplayContractViolationError):
        ds.render_html(sb)
    out = tmp_path / "reports_fc"
    with pytest.raises(ds.DisplayContractViolationError):
        ds.write_reports(sb, out)
    assert not out.exists() or not any(out.iterdir())  # nothing written
    monkeypatch.setattr(
        sys, "argv",
        ["daily_scoreboard", "--db", str(db), "--date", ET_DATE, "--no-backfill",
         "--out-dir", str(tmp_path / "out_fc"), "--allow-noncanonical-db"],
    )
    monkeypatch.setattr(ds, "require_canonical_db_target", lambda *a, **k: None)
    with pytest.raises(ds.DisplayContractViolationError):
        ds.main()
    assert not (tmp_path / "out_fc").exists() or not any((tmp_path / "out_fc").iterdir())


def test_lane_a_mutation_manifest_purity():
    """Package truth: the Lane-A manifest contains ONLY lane-A mutations with the
    required evidence fields; Lane-B mutations live in the quarantined artifact
    marked excluded from the Lane-A package."""
    root = Path(__file__).resolve().parent.parent
    m = json.loads((root / "reports/scoreboard_forensic/mutation_evidence_manifest.json").read_text(encoding="utf-8"))
    assert m["lane"] == "A"
    assert all(r["lane"] == "A" for r in m["mutations"])
    assert not any(r["id"] in ("M2", "M3") for r in m["mutations"])
    for r in m["mutations"]:
        for field in ("preimage_sha256", "unified_diff", "iteration_history"):
            assert field in r, f"{r['id']} missing {field}"
        # schema v5: per-run evidence blocks with matched canonical signatures.
        for run_key in ("run1", "run2"):
            run = r[run_key]
            for field in ("signature_digest", "structured_failures",
                          "restoration_hashes_match_preimages", "raw_evidence_files"):
                assert field in run, f"{r['id']}.{run_key} missing {field}"
        assert r["signature_match"] is True, f"{r['id']} signatures differ between runs"
    assert m["summary"]["statement"].startswith("LANE_A_MUTATIONS_DETECTED = ")
    assert m["summary"]["signature_matches"] == "27/27"
    for run_key in ("run1", "run2"):
        assert "lane-A composition" in m["restoration"][run_key]["suite_footprint"]
    # The Lane-B artifact is EXCLUDED from the Lane-A patch; when present in a
    # combined worktree it must be explicitly quarantined.
    lane_b = root / "reports/scoreboard_forensic/mutation_evidence_lane_b_uncommitted.json"
    if lane_b.is_file():
        b = json.loads(lane_b.read_text(encoding="utf-8"))
        assert b["lane"] == "B" and "QUARANTINED" in b["composition"]
        assert {r["id"] for r in b["mutations"]} == {"M2", "M3"}


def test_legacy_differential_artifact_reproduces():
    """Packaged, independently executable legacy differential (Lane-A evidence):
    the program reruns old-vs-new on the canonical fixture and must prove the
    numeric-subset and field-value identities with a deterministic fixture id."""
    import subprocess

    root = Path(__file__).resolve().parent.parent
    prog = root / "reports/scoreboard_forensic/legacy_differential/compare_legacy_differential.py"
    base = subprocess.run(
        ["git", "merge-base", "HEAD", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        cwd=root,
    ).stdout.strip()
    r = subprocess.run(
        [sys.executable, str(prog), base],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        cwd=root,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    res = json.loads((prog.parent / "legacy_differential_result.json").read_text(encoding="utf-8"))
    assert res["LEGACY_NUMERIC_SUBSET_IDENTITY"] == "PROVEN"
    assert res["LEGACY_FIELD_VALUE_IDENTITY"] == "PROVEN"
    assert res["numeric_fields_compared"] > 100 and res["all_fields_compared"] > 150
    assert res["legacy_subset_json_sha256_old"] == res["legacy_subset_json_sha256_new"]
    assert "NOT_PROVEN" in res["LEGACY_COMPLETE_JSON_BYTE_IDENTITY"]


def test_forensic_packet_lane_purity():
    """Package truth: the forensic packet machine-readably excludes Lane-B design
    from the Lane-A patch and never claims identity-first implementation for Lane A."""
    root = Path(__file__).resolve().parent.parent
    d = json.loads((root / "reports/scoreboard_forensic/july13_2026_target_truth_forensic.json").read_text(encoding="utf-8"))
    tags = d["lane_decomposition"]["section_tags"]
    assert tags["join_identity_forensic"]["included_in_lane_a_patch"] is False
    assert tags["join_identity_forensic"]["not_commit_evidence_for_lane_a"] is True
    fw = d["join_identity_forensic"]["verdicts"]["FORWARD_IDENTITY_FIRST_DESIGN"]
    assert fw.startswith("LANE_B_UNCOMMITTED_DESIGN")
    assert "LOCALLY_IMPLEMENTED" not in fw
    dumped = json.dumps(d)
    assert "correction_landed" not in dumped


def test_board_row_lane_language_purity():
    """Package truth: the board row states the Lane-A patch ships HEAD backfill
    behavior and carries no identity-first-implemented claim for Lane A."""
    board = Path(__file__).resolve().parent.parent.joinpath("OPEN_ITEMS.md").read_text(encoding="utf-8")
    row = next(l for l in board.splitlines() if "SCOREBOARD-TARGET-TRUTH " in l)
    assert "HEAD backfill behavior only" in row
    assert "FORWARD_IDENTITY_FIRST_DESIGN = LOCALLY_IMPLEMENTED" not in row
    assert "LOCALLY_PROVEN_PENDING_PR" not in row
    assert "NOT in the Lane-A patch" in row
    assert "LANE B COMMIT_READY = NO" in row


def test_v3_metric_tables_structural_semantics(tmp_path):
    """Phase-9: every scoreboard metric table carries a caption and scoped column
    headers — checked structurally via the stdlib HTML parser, not substrings."""
    from html.parser import HTMLParser

    class _T(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tables = []
            self._cur = None

        def handle_starttag(self, tag, attrs):
            if tag == "table":
                self._cur = {"caption": False, "th": 0, "th_scoped": 0}
                self.tables.append(self._cur)
            elif self._cur is not None and tag == "caption":
                self._cur["caption"] = True
            elif self._cur is not None and tag == "th":
                self._cur["th"] += 1
                if dict(attrs).get("scope") in ("col", "row"):
                    self._cur["th_scoped"] += 1

    db = _fixture_db(tmp_path)
    html = render_html(build_daily_scoreboard(db, ET_DATE, run_backfill=False))
    p = _T()
    p.feed(html)
    assert p.tables, "no tables parsed"
    for i, t in enumerate(p.tables):
        assert t["caption"], f"table {i} lacks a caption"
        assert t["th"] > 0 and t["th"] == t["th_scoped"], f"table {i} has unscoped <th>"


def test_v2_low_coverage_fail_closed_matrix():
    """DEFECT-C: the presentation status LEADS and accuracy is never decision-
    valid on insufficient sample/coverage; the 1/1000 case cannot lead with 100%."""
    from calibration.daily_scoreboard import _all_card_trade_metrics

    def _mk(n_long_hit, n_long_miss, n_short_hit, n_short_miss, n_wait):
        rows = []
        i = 0
        for _ in range(n_long_hit):
            rows.append(_v4_row("up", "up", ts=float(i))); i += 1
        for _ in range(n_long_miss):
            rows.append(_v4_row("up", "down", ts=float(i))); i += 1
        for _ in range(n_short_hit):
            rows.append(_v4_row("down", "down", ts=float(i))); i += 1
        for _ in range(n_short_miss):
            rows.append(_v4_row("down", "up", ts=float(i))); i += 1
        for _ in range(n_wait):
            rows.append(_v4_row("flat", "flat", ts=float(i))); i += 1
        return _all_card_trade_metrics(rows)

    # 1) 0 calls / 1000 eligible
    m = _mk(0, 0, 0, 0, 1000)
    assert m["accuracy_presentation"]["status"] == "NO_SCORED_CALLS"
    assert m["combined_trade_calls"]["accuracy"] is None
    # 2+3) 1 call / 1000, correct and incorrect — SINGLE_CALL, never decision-valid
    for hit in (1, 0):
        m = _mk(hit, 1 - hit, 0, 0, 999)
        p = m["accuracy_presentation"]
        assert p["status"] == "SINGLE_CALL" and p["decision_valid"] is False
        assert "NOT decision-valid" in p["leading_text"]
    # 4) 2 calls / 10000
    m = _mk(1, 0, 1, 0, 9998)
    assert m["accuracy_presentation"]["status"] == "SAMPLE_BELOW_GOVERNED_MINIMUM"
    # 5+6) one-sided calls only (>=30 so the sample floor passes first)
    m = _mk(35, 0, 0, 0, 0)
    assert m["accuracy_presentation"]["status"] == "ONE_SIDED_CALLS"
    m = _mk(0, 0, 35, 0, 0)
    assert m["accuracy_presentation"]["status"] == "ONE_SIDED_CALLS"
    # 9) sufficient two-sided calls but low coverage (40 calls / 10040 eligible)
    m = _mk(15, 5, 15, 5, 10000)
    assert m["accuracy_presentation"]["status"] == "LOW_COVERAGE"
    assert m["accuracy_presentation"]["decision_valid"] is False
    # sufficient sample + coverage -> SUFFICIENT, still not "validation"
    m = _mk(15, 5, 15, 5, 10)
    p = m["accuracy_presentation"]
    assert p["status"] == "SUFFICIENT" and p["decision_valid"] is True
    assert "not predictive validation" in p["leading_text"]


def test_v2_low_coverage_render_leads_with_status():
    """The rendered governed section opens with validity + sample status; the
    percentage appears only inside the qualified sentence."""
    from calibration.daily_scoreboard import _all_card_trade_metrics, render_html as _rh

    rows = [_v4_row("up", "up", ts=1.0)] + [
        _v4_row("flat", "flat", ts=float(i + 2)) for i in range(999)
    ]
    sb_min = {
        "et_date": "2026-06-09", "by_horizon": {}, "by_ticker": {},
        "all_card": _all_card_trade_metrics(rows), "by_horizon_extended": {},
    }
    html = _rh(sb_min)
    text = _plain_text(html)
    i_status = text.find("sample status SINGLE_CALL")
    i_pct = text.find("100.0%")
    assert 0 <= i_status < i_pct, "status must precede the accuracy percentage"
    assert "descriptive-only accuracy 100.0%" in text
    assert "NOT decision-valid" in text


def test_v2_every_table_labels_the_legacy_all_row(tmp_path):
    """E7 lock: EVERY table that renders an 'all' row/column carries the legacy
    qualification inside that table segment — pooled, equal-weight, per-ticker,
    and eligible grid alike (no unqualified 'all' cell anywhere in the HTML)."""
    db = _fixture_db(tmp_path)
    html = render_html(build_daily_scoreboard(db, ET_DATE, run_backfill=False))
    tables = html.split("<table>")[1:]
    for i, seg in enumerate(tables):
        seg = seg.split("</table>")[0]
        has_all_cell = _re.search(r"<t[dh][^>]*>all\b", seg) is not None
        if has_all_cell or ">all —" in seg:
            assert "Legacy ALL triclass accuracy" in seg, f"table {i} renders 'all' unqualified"
    # And no bare 'all' cell exists anywhere (every occurrence is the qualified form).
    assert not _re.search(r"<t[dh][^>]*>all</t[dh]>", html)


def test_v2_display_contracts_behaviorally_bound():
    """DEFECT-G: the executable binding validator passes on the committed code."""
    from calibration.daily_scoreboard import validate_display_contracts

    assert validate_display_contracts() == []


def test_v2_contract_mismatch_detection(monkeypatch):
    """DEFECT-G mismatch probes: the validator fails when metadata and behavior
    disagree (both directions), without touching production behavior."""
    import calibration.daily_scoreboard as ds

    # metadata says WAIT excluded, text mutated away -> caught
    bad = dict(ds.TRADE_CALL_DISPLAY_CONTRACT)
    bad["wait_treatment"] = "WAIT counted"
    monkeypatch.setattr(ds, "TRADE_CALL_DISPLAY_CONTRACT", bad)
    assert any("abstention" in e for e in ds.validate_display_contracts())
    monkeypatch.undo()
    # legacy mapping mutated -> caught
    monkeypatch.setattr(ds, "_FINAL_BIAS_TO_LABEL", {"LONG": "up", "SHORT": "down", "WAIT": "down"})
    assert any("_FINAL_BIAS_TO_LABEL" in e for e in ds.validate_display_contracts())
    monkeypatch.undo()
    # implementation includes WAIT (behavior side) -> caught
    real = ds._all_card_trade_metrics

    def _bad_metrics(rows):
        out = real(rows)
        out["combined_trade_calls"]["n_scored"] += out["n_wait"]  # WAIT leaks into denominator
        return out

    monkeypatch.setattr(ds, "_all_card_trade_metrics", _bad_metrics)
    assert any("WAIT not excluded" in e or "coverage denominator" in e or "presentation" in e
               for e in ds.validate_display_contracts())
    monkeypatch.undo()
    # legacy historical-purpose text removed -> caught
    bad_l = dict(ds.LEGACY_ALL_DISPLAY_CONTRACT)
    bad_l["intended_use"] = "general evaluation"
    monkeypatch.setattr(ds, "LEGACY_ALL_DISPLAY_CONTRACT", bad_l)
    assert any("historical" in e for e in ds.validate_display_contracts())


def test_defect1_renderers_consume_canonical_contracts_source_lock():
    """Test 17 (mechanical recurrence lock): both renderers reference the canonical
    display contracts; the legacy explanatory text is not independently hard-coded
    (single governed semantic-definition source)."""
    import ast

    src = Path(__file__).resolve().parent.parent.joinpath(
        "calibration", "daily_scoreboard.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for fname in ("render_html", "main"):
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fname)
        names = {x.id for x in ast.walk(fn) if isinstance(x, ast.Name)}
        assert "LEGACY_ALL_DISPLAY_CONTRACT" in names, f"{fname} does not consume the canonical legacy contract"
        assert "TRADE_CALL_DISPLAY_CONTRACT" in names, f"{fname} does not consume the canonical governed contract"
    # The load-bearing legacy phrase exists exactly once (in the contract), never
    # duplicated as renderer-local literals that could drift.
    assert src.count("WAIT scored as a flat-price class") == 1
    # Machine-readable copy is embedded in the JSON output definitions.
    from calibration.daily_scoreboard import _v4_metric_definitions

    md = _v4_metric_definitions()
    assert md["display_contracts"]["legacy_all"]["classification"] == "legacy"
    assert md["display_contracts"]["trade_call"]["classification"] == "governed"
