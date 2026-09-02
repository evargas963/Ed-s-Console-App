"""Tests for research/challenger_eval_v1 (Study #2 challenger race).

Covers: challenger prediction rules (causality, zero-move honesty, reversal),
the causal bar join (bar_end <= decision_ts, staleness gate), head-to-head
incumbent rescoring on identical rows, prereg enforcement, the advancement
screen, and an end-to-end run against a synthetic fixture DB.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from research.challenger_eval_v1 import runner
from research.incumbent_eval_v1 import stats
from app.domain.time_et import ET


# ── challenger prediction rules ──────────────────────────────────────────────

def test_momentum_prediction_direction():
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    assert runner.challenger_prediction(closes, 5, "momentum_5") == "up"
    falling = list(reversed(closes))
    assert runner.challenger_prediction(falling, 5, "momentum_5") == "down"


def test_mean_reversion_is_opposite_of_momentum():
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    assert runner.challenger_prediction(closes, 5, "mean_reversion_5") == "down"


def test_insufficient_history_returns_none():
    closes = [100.0, 101.0]
    assert runner.challenger_prediction(closes, 1, "momentum_5") is None


def test_zero_move_returns_none_never_a_fabricated_direction():
    closes = [100.0] * 10
    assert runner.challenger_prediction(closes, 9, "momentum_5") is None


# ── causal bar join ──────────────────────────────────────────────────────────

def test_attach_predictions_uses_last_completed_bar_only():
    # Bars end at t=60,120,180; decision at t=150 must see the t=120 bar (j=1),
    # never the t=180 bar that has not completed yet.
    ends = [60.0, 120.0, 180.0]
    closes = [100.0, 101.0, 99.0]
    rows = [{"ts": 150.0, "et_date": "2026-06-01", "truth": "up", "incumbent_pred": "up"}]
    runner.attach_challenger_predictions(rows, (ends, closes), ["momentum_5"], 120.0)
    # j=1 -> needs closes[1-5] which is out of range -> None (short history),
    # proving the join landed on the completed bar, not the future one.
    assert rows[0]["pred_momentum_5"] is None


def test_attach_predictions_bar_gap_skip():
    ends = [60.0]
    closes = [100.0]
    rows = [{"ts": 100_000.0, "et_date": "2026-06-01", "truth": "up", "incumbent_pred": "up"}]
    skips = runner.attach_challenger_predictions(rows, (ends, closes), ["momentum_5"], 120.0)
    assert skips["BAR_GAP"] == 1
    assert rows[0]["pred_momentum_5"] is None


def test_attach_predictions_happy_path_momentum():
    n = 20
    ends = [60.0 * (i + 1) for i in range(n)]
    closes = [100.0 + i for i in range(n)]  # strictly rising
    rows = [{"ts": ends[-1] + 10.0, "et_date": "2026-06-01", "truth": "up", "incumbent_pred": "flat"}]
    skips = runner.attach_challenger_predictions(
        rows, (ends, closes), ["momentum_5", "mean_reversion_5"], 120.0
    )
    assert rows[0]["pred_momentum_5"] == "up"
    assert rows[0]["pred_mean_reversion_5"] == "down"
    assert skips["BAR_GAP"] == 0


# ── prereg enforcement ───────────────────────────────────────────────────────

def test_prereg_loads_and_is_internally_consistent():
    prereg = runner.load_prereg()
    fam = prereg["family"]
    assert fam["n_tests"] == len(fam["tickers"]) * len(fam["horizons"]) * len(fam["challengers"])
    assert set(fam["challengers"]) == set(runner.CHALLENGER_LOOKBACKS)


def test_prereg_roster_divergence_raises(monkeypatch, tmp_path):
    bad = tmp_path / "prereg_v1.json"
    bad.write_text(json.dumps({
        "family": {"tickers": ["SPY"], "horizons": ["1c"], "challengers": ["momentum_5"], "n_tests": 1},
        "primary_metric": {"name": "MCC"},
    }))
    monkeypatch.setattr(runner, "PREREG_PATH", bad)
    with pytest.raises(runner.PreregViolationError):
        runner.load_prereg()


# ── evaluation + screen ──────────────────────────────────────────────────────

def _mk_rows(n_days: int, per_day: int, challenger_hit: float, incumbent_hit: float) -> list[dict]:
    import random

    rng = random.Random(5)
    classes = list(stats.CLASSES)
    rows = []
    for d in range(n_days):
        date = f"2026-06-{d + 1:02d}"
        for i in range(per_day):
            truth = classes[rng.randrange(3)]
            chal = truth if rng.random() < challenger_hit else classes[rng.randrange(3)]
            inc = truth if rng.random() < incumbent_hit else classes[rng.randrange(3)]
            rows.append({
                "ts": 1_000_000.0 + (d * per_day + i) * 60.0,
                "et_date": date,
                "truth": truth,
                "incumbent_pred": inc,
                "pred_momentum_5": chal if chal != "flat" else None,
            })
    return rows


def test_evaluate_test_head_to_head_on_identical_rows():
    prereg = runner.load_prereg()
    # per_day=60: ~1/3 of rows get no challenger prediction (truth=flat copies
    # to None), so scored rows must still clear the 300-row prereg floor.
    rows = _mk_rows(12, 60, challenger_hit=0.9, incumbent_hit=0.0)
    t = runner.evaluate_test(rows, "momentum_5", "1c", prereg)
    assert t["under_sampled"] is False
    assert t["mcc"] > 0.5
    # Incumbent rescored on the exact rows the challenger scored.
    assert t["n_scored"] == t["n_rows_in_cell"] - sum(
        1 for r in rows if r["pred_momentum_5"] is None
    )
    assert t["incumbent_on_identical_rows"]["mcc"] < 0.2
    assert t["mcc_delta_vs_incumbent"] > 0.3


def test_advancement_screen_pass_fail_undersampled():
    prereg = runner.load_prereg()
    tests = {
        "SPY:1c:momentum_5": runner.evaluate_test(
            _mk_rows(12, 60, 0.9, 0.5), "momentum_5", "1c", prereg
        ),
        "QQQ:1c:momentum_5": runner.evaluate_test(
            _mk_rows(12, 60, 0.0, 0.5), "momentum_5", "1c", prereg
        ),
        "IWM:1c:momentum_5": runner.evaluate_test(
            _mk_rows(2, 10, 0.9, 0.5), "momentum_5", "1c", prereg
        ),
    }
    runner.apply_advancement_screen(tests, prereg)
    assert tests["SPY:1c:momentum_5"]["verdict"] == "PASS"
    assert tests["QQQ:1c:momentum_5"]["verdict"] == "FAIL"
    assert tests["IWM:1c:momentum_5"]["verdict"] == "UNDER_SAMPLED"


# ── end-to-end fixture DB ────────────────────────────────────────────────────

def _fixture_db(tmp_path, n_days: int = 12, per_day: int = 40):
    """Fixture with price_bars_1m driving BOTH the truth labels and the bars, so
    momentum has real signal; incumbent recorded predictions are pure noise."""
    import random

    db = tmp_path / "fixture.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE calibration_decision_log ("
        " ticker TEXT, decision_ts_utc REAL, model_outputs_json TEXT,"
        " outcome_1c TEXT, outcome_5c TEXT, outcome_15c TEXT, outcome_60c TEXT,"
        " calibration_trust TEXT, outcomes_attached_ts_utc REAL)"
    )
    conn.execute(
        "CREATE TABLE price_bars_1m ("
        " ticker TEXT, bar_start_ts_utc REAL, bar_end_ts_utc REAL,"
        " open REAL, high REAL, low REAL, close REAL, volume REAL, source TEXT)"
    )
    rng = random.Random(23)
    classes = list(stats.CLASSES)
    day = datetime(2026, 6, 1, 10, 0, tzinfo=ET)
    cal_rows, bar_rows = [], []
    days_done = 0
    while days_done < n_days:
        if day.weekday() < 5:
            # 90 bars of a persistent trend (up on even fixture-days, down on odd).
            direction = 1.0 if days_done % 2 == 0 else -1.0
            price = 500.0
            day_bar_start = day - timedelta(minutes=30)
            for b in range(90):
                start = (day_bar_start + timedelta(minutes=b)).timestamp()
                nxt = price + direction * 0.1
                bar_rows.append(("SPY", start, start + 60.0, price, max(price, nxt), min(price, nxt), nxt, 1000.0, "fixture"))
                price = nxt
            for i in range(per_day):
                ts = (day + timedelta(minutes=i)).timestamp()
                truth = "up" if direction > 0 else "down"  # trend continues
                incumbent = classes[rng.randrange(3)]  # noise
                by_hz = {"1c": {
                    "horizon_fusion_available": True,
                    "dominant_direction": incumbent,
                    "prob_up": 0.34, "prob_down": 0.33, "prob_flat": 0.33,
                }}
                bundle = {"stack_probs_bundle": {"multi_horizon_ml_fusion_bundle": {"by_horizon": by_hz}}}
                cal_rows.append(("SPY", ts, json.dumps(bundle), truth, None, None, None, "trusted", ts + 120.0))
            days_done += 1
        day += timedelta(days=1)
    conn.executemany("INSERT INTO calibration_decision_log VALUES (?,?,?,?,?,?,?,?,?)", cal_rows)
    conn.executemany("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)", bar_rows)
    conn.commit()
    conn.close()
    return db


def test_run_study_end_to_end(tmp_path, monkeypatch):
    db = _fixture_db(tmp_path)
    monkeypatch.setattr(runner, "invalid_threshold_horizons", lambda: [])
    report = runner.run_study(db)
    t = report["tests"]["SPY:1c:momentum_5"]
    # Trend-following momentum on a trending fixture: near-perfect signal.
    assert t["verdict"] == "PASS"
    assert t["mcc"] > 0.8
    assert t["mcc_delta_vs_incumbent"] > 0.5
    # Its mirror must be exactly as wrong (never scored PASS).
    rev = report["tests"]["SPY:1c:mean_reversion_5"]
    assert rev["mcc"] < -0.8
    assert rev["verdict"] == "FAIL"
    # Empty cells (other tickers) report UNDER_SAMPLED, never crash.
    assert report["tests"]["QQQ:1c:momentum_5"]["verdict"] == "UNDER_SAMPLED"
    assert report["summary"]["verdict"] == "SIGNAL_DETECTED_IN_SOME_TESTS"


def test_write_report_creates_json_and_latest(tmp_path, monkeypatch):
    db = _fixture_db(tmp_path, n_days=2, per_day=5)
    monkeypatch.setattr(runner, "invalid_threshold_horizons", lambda: [])
    report = runner.run_study(db)
    out = tmp_path / "reports"
    path = runner.write_report(report, out)
    assert path.is_file()
    assert (out / "latest.json").is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["run_id"] == report["run_id"]
