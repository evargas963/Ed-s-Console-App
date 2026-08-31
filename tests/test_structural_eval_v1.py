"""Tests for research/structural_eval_v1 (Study #3 structural rule race).

Covers: the fixed semantic rules (zone mapping, wall attraction/repulsion
mirror symmetry, regime-gated momentum with honest abstention), prereg
enforcement, abstention accounting, and an end-to-end run against a synthetic
fixture DB where the zone field carries real signal and the incumbent is noise.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from research.structural_eval_v1 import runner
from time_et import ET


# ── fixed semantic rules ─────────────────────────────────────────────────────

def test_zone_direction_mapping_and_abstention():
    assert runner.zone_direction_prediction("pin_bull") == "up"
    assert runner.zone_direction_prediction("pin_bear") == "down"
    assert runner.zone_direction_prediction("breakout") == "up"
    assert runner.zone_direction_prediction("breakdown") == "down"
    assert runner.zone_direction_prediction("pin_chaos") is None
    assert runner.zone_direction_prediction(None) is None
    assert runner.zone_direction_prediction("") is None


def test_wall_attraction_toward_nearer_wall():
    # Above wall nearer -> price pulled up; below nearer -> pulled down.
    assert runner.wall_prediction(0.5, 3.0, attract=True) == "up"
    assert runner.wall_prediction(3.0, 0.5, attract=True) == "down"


def test_wall_repulsion_is_exact_mirror():
    for a, b in ((0.5, 3.0), (3.0, 0.5), (1.2, 7.9)):
        att = runner.wall_prediction(a, b, attract=True)
        rep = runner.wall_prediction(a, b, attract=False)
        assert {att, rep} == {"up", "down"}


def test_wall_prediction_abstains_on_tie_or_missing():
    assert runner.wall_prediction(1.0, 1.0, attract=True) is None
    assert runner.wall_prediction(None, 1.0, attract=True) is None
    assert runner.wall_prediction(1.0, None, attract=False) is None


def test_regime_gated_momentum_abstains_outside_directional_regimes():
    closes = [100.0 + i for i in range(30)]
    j = len(closes) - 1
    assert runner.regime_gated_momentum_prediction("pinning", closes, j) is None
    assert runner.regime_gated_momentum_prediction(None, closes, j) is None
    assert runner.regime_gated_momentum_prediction("trend_continuation", closes, None) is None
    assert runner.regime_gated_momentum_prediction("trend_continuation", closes, j) == "up"
    assert runner.regime_gated_momentum_prediction("acceleration", closes, j) == "up"


# ── prereg enforcement ───────────────────────────────────────────────────────

def test_prereg_loads_and_is_internally_consistent():
    prereg = runner.load_prereg()
    fam = prereg["family"]
    assert fam["n_tests"] == len(fam["tickers"]) * len(fam["horizons"]) * len(fam["rules"])
    assert set(fam["rules"]) == set(runner.RULES)


def test_prereg_roster_divergence_raises(monkeypatch, tmp_path):
    bad = tmp_path / "prereg_v1.json"
    bad.write_text(json.dumps({
        "family": {"tickers": ["SPY"], "horizons": ["1c"], "rules": ["zone_direction"], "n_tests": 1},
        "primary_metric": {"name": "MCC"},
    }))
    monkeypatch.setattr(runner, "PREREG_PATH", bad)
    with pytest.raises(runner.PreregViolationError):
        runner.load_prereg()


# ── abstention accounting ────────────────────────────────────────────────────

def test_attach_rule_predictions_counts_abstentions():
    rows = [
        {"ts": 200.0, "zone": "pin_bull", "regime_primary": "pinning",
         "nearest_above_dist": 1.0, "nearest_below_dist": 1.0},
        {"ts": 200.0, "zone": "pin_chaos", "regime_primary": "trend_continuation",
         "nearest_above_dist": 0.5, "nearest_below_dist": 2.0},
    ]
    ends = [60.0 * (i + 1) for i in range(3)]
    closes = [100.0, 101.0, 102.0]
    tallies = runner.attach_rule_predictions(rows, (ends, closes), 120.0)
    assert rows[0]["pred_zone_direction"] == "up"
    assert rows[0]["pred_wall_attraction"] is None  # tie
    assert rows[1]["pred_zone_direction"] is None  # chaos
    assert rows[1]["pred_wall_attraction"] == "up"
    # momentum_15 needs 15 bars of history -> abstains for both rows here
    assert tallies["ABSTAIN_regime_gated_momentum_15"] == 2
    assert tallies["ABSTAIN_zone_direction"] == 1
    assert tallies["ABSTAIN_wall_attraction"] == 1


# ── end-to-end fixture DB ────────────────────────────────────────────────────

def _fixture_db(tmp_path, n_days: int = 12, per_day: int = 60):
    """zone carries near-perfect signal; walls and incumbent are noise."""
    import random

    db = tmp_path / "fixture.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE calibration_decision_log ("
        " ticker TEXT, decision_ts_utc REAL, model_outputs_json TEXT,"
        " zone TEXT, regime_primary TEXT, nearest_above_dist REAL, nearest_below_dist REAL,"
        " outcome_1c TEXT, outcome_5c TEXT, outcome_15c TEXT, outcome_60c TEXT,"
        " calibration_trust TEXT, outcomes_attached_ts_utc REAL)"
    )
    conn.execute(
        "CREATE TABLE price_bars_1m ("
        " ticker TEXT, bar_start_ts_utc REAL, bar_end_ts_utc REAL,"
        " open REAL, high REAL, low REAL, close REAL, volume REAL, source TEXT)"
    )
    rng = random.Random(31)
    day = datetime(2026, 6, 1, 10, 0, tzinfo=ET)
    cal_rows, bar_rows = [], []
    days_done = 0
    while days_done < n_days:
        if day.weekday() < 5:
            price = 500.0
            day_bar_start = day - timedelta(minutes=30)
            for b in range(120):
                start = (day_bar_start + timedelta(minutes=b)).timestamp()
                nxt = price + rng.uniform(-0.1, 0.1)
                bar_rows.append(("SPY", start, start + 60.0, price, max(price, nxt), min(price, nxt), nxt, 1000.0, "fixture"))
                price = nxt
            for i in range(per_day):
                ts = (day + timedelta(minutes=i)).timestamp()
                truth = ["up", "down", "flat"][rng.randrange(3)]
                # zone encodes truth 90% of the time (up->pin_bull, down->pin_bear,
                # flat->pin_chaos so the rule abstains on flat truths).
                if rng.random() < 0.9:
                    zone = {"up": "pin_bull", "down": "pin_bear", "flat": "pin_chaos"}[truth]
                else:
                    zone = ["pin_bull", "pin_bear", "pin_chaos"][rng.randrange(3)]
                incumbent = ["up", "down", "flat"][rng.randrange(3)]
                by_hz = {"1c": {
                    "horizon_fusion_available": True,
                    "dominant_direction": incumbent,
                    "prob_up": 0.34, "prob_down": 0.33, "prob_flat": 0.33,
                }}
                bundle = {"stack_probs_bundle": {"multi_horizon_ml_fusion_bundle": {"by_horizon": by_hz}}}
                cal_rows.append((
                    "SPY", ts, json.dumps(bundle), zone, "pinning",
                    rng.uniform(0.1, 5.0), rng.uniform(0.1, 5.0),
                    truth, None, None, None, "trusted", ts + 120.0,
                ))
            days_done += 1
        day += timedelta(days=1)
    conn.executemany(
        "INSERT INTO calibration_decision_log VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", cal_rows
    )
    conn.executemany("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)", bar_rows)
    conn.commit()
    conn.close()
    return db


def test_run_study_end_to_end(tmp_path, monkeypatch):
    db = _fixture_db(tmp_path)
    monkeypatch.setattr(runner, "invalid_threshold_horizons", lambda: [])
    report = runner.run_study(db)
    zone = report["tests"]["SPY:1c:zone_direction"]
    assert zone["verdict"] == "PASS"
    assert zone["mcc"] > 0.5
    assert zone["mcc_delta_vs_incumbent"] > 0.3
    assert zone["abstention_rate"] > 0.2  # flat truths mostly map to chaos -> abstain
    # Random walls: attraction and repulsion both fail on a noise fixture.
    assert report["tests"]["SPY:1c:wall_attraction"]["verdict"] in ("FAIL", "UNDER_SAMPLED")
    assert report["tests"]["SPY:1c:wall_repulsion"]["verdict"] in ("FAIL", "UNDER_SAMPLED")
    # Empty cells (other tickers) report UNDER_SAMPLED, never crash.
    assert report["tests"]["QQQ:1c:zone_direction"]["verdict"] == "UNDER_SAMPLED"
    assert report["summary"]["verdict"] == "SIGNAL_DETECTED_IN_SOME_TESTS"


def test_write_report_creates_json_and_latest(tmp_path, monkeypatch):
    # institutional-duplicate-ok: same-shaped test against a DIFFERENT production
    # module (research.structural_eval_v1.runner, not challenger_eval_v1.runner) --
    # TEST_SYSTEM_REHAB_V2 semantic review kept both deliberately.
    db = _fixture_db(tmp_path, n_days=2, per_day=5)
    monkeypatch.setattr(runner, "invalid_threshold_horizons", lambda: [])
    report = runner.run_study(db)
    out = tmp_path / "reports"
    path = runner.write_report(report, out)
    assert path.is_file()
    assert (out / "latest.json").is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["run_id"] == report["run_id"]
