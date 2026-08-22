"""Tests for research/incumbent_eval_v1 (Study #1 racetrack).

Covers: the pure statistics (MCC, balanced accuracy, baselines, day-block
bootstrap, shuffle control, Holm-Bonferroni), preregistration consistency
enforcement, cell evaluation with sample floors, the advancement screen, and
an end-to-end run against a synthetic fixture DB.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from research.incumbent_eval_v1 import runner, stats
from time_et import ET


# ── stats: multiclass MCC ────────────────────────────────────────────────────

def test_mcc_perfect_prediction_is_one():
    preds = ["up", "down", "flat", "up", "down", "flat"]
    cm = stats.confusion_matrix(preds, preds)
    assert stats.mcc_multiclass(cm) == pytest.approx(1.0)


def test_mcc_inverted_prediction_is_negative():
    preds = ["up", "up", "down", "down"]
    truths = ["down", "down", "up", "up"]
    cm = stats.confusion_matrix(preds, truths)
    assert stats.mcc_multiclass(cm) == pytest.approx(-1.0)


def test_mcc_degenerate_single_class_is_none():
    # All predictions one class -> denominator zero -> None, never a fabricated 0.
    cm = stats.confusion_matrix(["flat"] * 4, ["up", "down", "flat", "flat"])
    assert stats.mcc_multiclass(cm) is None


def test_mcc_empty_is_none():
    assert stats.mcc_multiclass(stats.confusion_matrix([], [])) is None


def test_mcc_matches_sklearn_reference_value():
    # Reference value recomputed with sklearn.metrics.matthews_corrcoef
    # (0.5909090909090909) for this exact 3-class example.
    preds = ["up", "up", "down", "flat", "up", "down"]
    truths = ["up", "down", "down", "flat", "flat", "down"]
    cm = stats.confusion_matrix(preds, truths)
    assert stats.mcc_multiclass(cm) == pytest.approx(0.5909090909090909)


# ── stats: balanced accuracy / accuracy / log loss / baselines ──────────────

def test_balanced_accuracy_mean_of_per_class_recall():
    preds = ["up", "up", "down", "down"]
    truths = ["up", "down", "down", "down"]
    cm = stats.confusion_matrix(preds, truths)
    # recall(up)=1/1, recall(down)=2/3; flat absent from truth -> excluded
    assert stats.balanced_accuracy(cm) == pytest.approx((1.0 + 2.0 / 3.0) / 2.0)


def test_log_loss_uses_probability_of_realized_class():
    import math

    rows = [
        {"prob_up": 0.5, "prob_down": 0.25, "prob_flat": 0.25},
        {"prob_up": 0.1, "prob_down": 0.8, "prob_flat": 0.1},
    ]
    ll = stats.multiclass_log_loss(rows, ["up", "down"])
    assert ll == pytest.approx((-math.log(0.5) - math.log(0.8)) / 2.0)


def test_baselines_always_flat_majority_persistence():
    truths = ["up", "up", "flat", "up"]
    b = stats.baseline_accuracies([], truths)
    assert b["always_flat"] == pytest.approx(0.25)
    assert b["majority_class"] == pytest.approx(0.75)
    # persistence hits: t1(up==up)=1, t2(flat==up)=0, t3(up==flat)=0 -> 1/3
    assert b["persistence"] == pytest.approx(1.0 / 3.0)


def test_baselines_empty_and_single_row():
    empty = stats.baseline_accuracies([], [])
    assert empty == {"always_flat": None, "majority_class": None, "persistence": None}
    single = stats.baseline_accuracies([], ["up"])
    assert single["persistence"] is None


# ── stats: bootstrap / shuffle / Holm ────────────────────────────────────────

def _signal_rows(n_days: int, per_day: int, hit_rate: float) -> tuple[list, list, list]:
    """Synthetic (preds, truths, et_dates).

    hit_rate is the probability the prediction COPIES the truth; otherwise the
    prediction is a uniform random class independent of truth. hit_rate=0.0 is
    therefore the honest chance fixture (zero pred/truth correlation)."""
    import random

    rng = random.Random(7)
    classes = list(stats.CLASSES)
    preds, truths, dates = [], [], []
    for d in range(n_days):
        date = f"2026-06-{d + 1:02d}"
        for _ in range(per_day):
            truth = classes[rng.randrange(3)]
            pred = truth if rng.random() < hit_rate else classes[rng.randrange(3)]
            preds.append(pred)
            truths.append(truth)
            dates.append(date)
    return preds, truths, dates


def test_bootstrap_detects_strong_signal_and_is_deterministic():
    preds, truths, dates = _signal_rows(n_days=15, per_day=40, hit_rate=0.9)
    b1 = stats.day_block_bootstrap_mcc(preds, truths, dates, n_boot=200, seed=1)
    b2 = stats.day_block_bootstrap_mcc(preds, truths, dates, n_boot=200, seed=1)
    assert b1 == b2  # same seed -> identical resamples
    assert b1["ci95"][0] > 0.0  # strong signal: CI excludes zero
    assert b1["p_value"] <= 0.05


def test_bootstrap_no_signal_ci_spans_zero():
    preds, truths, dates = _signal_rows(n_days=15, per_day=40, hit_rate=0.0)
    b = stats.day_block_bootstrap_mcc(preds, truths, dates, n_boot=200, seed=1)
    assert b["ci95"][0] < 0.0 < b["ci95"][1]


def test_bootstrap_fewer_than_two_days_returns_none_ci():
    b = stats.day_block_bootstrap_mcc(["up"], ["up"], ["2026-06-01"], n_boot=100, seed=1)
    assert b["ci95"] is None and b["p_value"] is None


def test_shuffle_control_null_centered_at_zero():
    preds, truths, _ = _signal_rows(n_days=10, per_day=50, hit_rate=0.9)
    sc = stats.shuffle_control_mcc(preds, truths, n_shuffles=100, seed=3)
    assert sc["null_q025"] < 0.0 < sc["null_q975"]
    assert abs(sc["null_mean"]) < 0.05


def test_holm_bonferroni_adjusts_and_orders():
    res = stats.holm_bonferroni({"a": 0.001, "b": 0.04, "c": 0.5, "d": None}, alpha=0.05)
    assert res["a"]["p_adjusted"] == pytest.approx(0.003)
    assert res["a"]["significant"] is True
    # b: rank 2 of 3 testable -> 2 * 0.04 = 0.08 >= alpha -> not significant
    assert res["b"]["significant"] is False
    assert res["c"]["significant"] is False
    assert res["d"]["p_adjusted"] is None and res["d"]["significant"] is None


def test_holm_step_down_monotone_adjustment():
    res = stats.holm_bonferroni({"a": 0.03, "b": 0.031}, alpha=0.05)
    # adjusted p is non-decreasing in rank order
    assert res["b"]["p_adjusted"] >= res["a"]["p_adjusted"]


# ── prereg enforcement ───────────────────────────────────────────────────────

def test_prereg_loads_and_is_internally_consistent():
    prereg = runner.load_prereg()
    fam = prereg["family"]
    assert fam["n_cells"] == len(fam["tickers"]) * len(fam["horizons"])
    assert prereg["primary_metric"]["name"].startswith("MCC")


def test_prereg_violation_raises(monkeypatch, tmp_path):
    bad = tmp_path / "prereg_v1.json"
    bad.write_text(json.dumps({"family": {"tickers": ["SPY"], "horizons": ["1c"], "n_cells": 99}}))
    monkeypatch.setattr(runner, "PREREG_PATH", bad)
    with pytest.raises(runner.PreregViolationError):
        runner.load_prereg()


# ── cell evaluation + advancement screen ─────────────────────────────────────

def _mk_rows(n_days: int, per_day: int, hit_rate: float) -> list[dict]:
    preds, truths, dates = _signal_rows(n_days, per_day, hit_rate)
    rows = []
    for i, (p, t, d) in enumerate(zip(preds, truths, dates)):
        probs = {f"prob_{c}": (0.8 if c == p else 0.1) for c in stats.CLASSES}
        rows.append({"ts": 1_000_000.0 + i * 60.0, "et_date": d, "pred": p, "truth": t, **probs})
    return rows


def test_evaluate_cell_under_sampled_skips_bootstrap():
    prereg = runner.load_prereg()
    cell = runner.evaluate_cell(_mk_rows(3, 10, 0.9), "1c", prereg)
    assert cell["under_sampled"] is True
    assert cell["bootstrap"] is None and cell["shuffle_control"] is None
    assert "UNDER_SAMPLED" in cell["warnings"]


def test_evaluate_cell_full_metrics_when_floors_met():
    prereg = runner.load_prereg()
    cell = runner.evaluate_cell(_mk_rows(12, 30, 0.9), "1c", prereg)
    assert cell["under_sampled"] is False
    assert cell["mcc"] > 0.5
    assert cell["bootstrap"]["ci95"][0] > 0.0
    assert cell["n_scored"] == 360


def test_advancement_screen_pass_and_fail():
    prereg = runner.load_prereg()
    cells = {
        "SPY:1c": runner.evaluate_cell(_mk_rows(12, 30, 0.9), "1c", prereg),
        "QQQ:1c": runner.evaluate_cell(_mk_rows(12, 30, 0.0), "1c", prereg),
        "IWM:1c": runner.evaluate_cell(_mk_rows(3, 10, 0.9), "1c", prereg),
    }
    runner.apply_advancement_screen(cells, prereg)
    assert cells["SPY:1c"]["verdict"] == "PASS"
    assert cells["QQQ:1c"]["verdict"] == "FAIL"
    assert cells["IWM:1c"]["verdict"] == "UNDER_SAMPLED"
    assert cells["SPY:1c"]["screen"]["shuffle_control_ok"] is True


# ── end-to-end on a synthetic fixture DB ─────────────────────────────────────

def _fixture_db(tmp_path, n_days: int = 12, per_day: int = 30):
    """calibration_decision_log with the columns the runner reads; RTH rows only."""
    db = tmp_path / "fixture.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE calibration_decision_log ("
        " ticker TEXT, decision_ts_utc REAL, model_outputs_json TEXT,"
        " outcome_1c TEXT, outcome_5c TEXT, outcome_15c TEXT, outcome_60c TEXT,"
        " calibration_trust TEXT, outcomes_attached_ts_utc REAL)"
    )
    import random

    rng = random.Random(11)
    classes = list(stats.CLASSES)
    # Weekdays only, 10:00 ET start — inside tradable RTH so is_tradable_session_ts_utc passes.
    day = datetime(2026, 6, 1, 10, 0, tzinfo=ET)
    rows = []
    days_done = 0
    while days_done < n_days:
        if day.weekday() < 5:
            for i in range(per_day):
                ts = (day + timedelta(minutes=i)).timestamp()
                truth = classes[rng.randrange(3)]
                pred = truth if rng.random() < 0.9 else classes[rng.randrange(3)]
                by_hz = {
                    "1c": {
                        "horizon_fusion_available": True,
                        "dominant_direction": pred,
                        "prob_up": 0.8 if pred == "up" else 0.1,
                        "prob_down": 0.8 if pred == "down" else 0.1,
                        "prob_flat": 0.8 if pred == "flat" else 0.1,
                    }
                }
                bundle = {
                    "stack_probs_bundle": {
                        "multi_horizon_ml_fusion_bundle": {"by_horizon": by_hz}
                    }
                }
                rows.append(("SPY", ts, json.dumps(bundle), truth, None, None, None, "trusted", ts + 120.0))
            days_done += 1
        day += timedelta(days=1)
    conn.executemany(
        "INSERT INTO calibration_decision_log VALUES (?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()
    return db


def test_run_study_end_to_end(tmp_path, monkeypatch):
    db = _fixture_db(tmp_path)
    # Freeze the environment-dependent threshold config out of the test.
    monkeypatch.setattr(runner, "invalid_threshold_horizons", lambda: [])
    report = runner.run_study(db)
    assert report["prereg_id"] == "incumbent_eval_v1_prereg_v1"
    spy_1c = report["cells"]["SPY:1c"]
    assert spy_1c["verdict"] == "PASS"
    assert spy_1c["n_scored"] == 360
    # Cells with no rows (other tickers/horizons) report under-sampled, never crash.
    assert report["cells"]["QQQ:1c"]["verdict"] == "UNDER_SAMPLED"
    assert report["summary"]["verdict"] == "SIGNAL_DETECTED_IN_SOME_CELLS"
    assert report["summary"]["n_pass"] == 1


def test_write_report_creates_json_and_latest(tmp_path, monkeypatch):
    db = _fixture_db(tmp_path, n_days=2, per_day=5)
    monkeypatch.setattr(runner, "invalid_threshold_horizons", lambda: [])
    report = runner.run_study(db)
    out = tmp_path / "reports"
    path = runner.write_report(report, out)
    assert path.is_file()
    assert (out / "latest.json").is_file()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["run_id"] == report["run_id"]
