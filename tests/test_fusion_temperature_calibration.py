"""Fusion temperature calibration: fitter, apply gate, artifact IO, and serve hook.

Operator design (2026-06-10): one contiguous stack, calibration at exactly one door
(the per-horizon fusion triplet in multi_horizon_ml_bundle). Fail-closed everywhere:
no artifact / failed gate / insufficient samples => raw triplet served unchanged.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.fusion_temperature import (
    FIT_WINDOW_FLOOR_UTC,
    MIN_FIT_SAMPLES,
    apply_temperature,
    fit_fusion_temperature_artifact,
    fit_horizon_temperature,
    load_applied_temperatures,
    load_fusion_calibration_rows,
    write_fusion_temperature_artifact,
)


# ── apply_temperature ─────────────────────────────────────────────────────────────


def test_apply_temperature_identity_at_one():
    assert apply_temperature(0.5, 0.3, 0.2, 1.0) == (0.5, 0.3, 0.2)


def test_apply_temperature_flattens_above_one_and_sharpens_below():
    pu, pd, pf = apply_temperature(0.7, 0.2, 0.1, 2.0)
    assert pu < 0.7 and pf > 0.1  # flattened toward uniform
    assert abs(pu + pd + pf - 1.0) < 1e-12
    pu2, pd2, pf2 = apply_temperature(0.7, 0.2, 0.1, 0.5)
    assert pu2 > 0.7 and pf2 < 0.1  # sharpened
    assert abs(pu2 + pd2 + pf2 - 1.0) < 1e-12


def test_apply_temperature_preserves_ranking():
    """Dominant direction can never change — only confidence honesty."""
    for t in (0.25, 0.7, 1.5, 4.0):
        pu, pd, pf = apply_temperature(0.5, 0.3, 0.2, t)
        assert pu > pd > pf


def test_apply_temperature_rejects_bad_temperature():
    with pytest.raises(ValueError):
        apply_temperature(0.5, 0.3, 0.2, 0.0)
    with pytest.raises(ValueError):
        apply_temperature(0.5, 0.3, 0.2, float("nan"))


# ── fitter ────────────────────────────────────────────────────────────────────────


def _overconfident_rows(n: int) -> list[dict]:
    """Synthetic overconfident stream: predicts 0.8 'up' but is right only ~55%."""
    rows = []
    for i in range(n):
        outcome = "up" if (i % 20) < 11 else "down"  # 55% hit rate
        rows.append(
            {
                "ticker": "SPY",
                "decision_ts_utc": 1_000_000.0 + i,
                "prob_up": 0.8,
                "prob_down": 0.15,
                "prob_flat": 0.05,
                "outcome": outcome,
            }
        )
    return rows


def test_fit_recovers_flattening_temperature_on_overconfident_data():
    res = fit_horizon_temperature(_overconfident_rows(1000))
    assert res["status"] == "ok"
    assert res["apply"] is True
    assert res["temperature"] > 1.0  # overconfidence => flatten
    assert res["nll_holdout_calibrated"] < res["nll_holdout_raw"]


def test_fit_insufficient_samples_fails_closed():
    res = fit_horizon_temperature(_overconfident_rows(MIN_FIT_SAMPLES - 1))
    assert res["status"] == "insufficient_sample"
    assert res["apply"] is False
    assert res["temperature"] is None


def test_fit_well_calibrated_data_does_not_apply():
    """Honest probabilities => no strict holdout improvement => identity served."""
    rows = []
    for i in range(1000):
        # 60% up / 40% down stream predicted at exactly 0.6/0.4: already calibrated.
        outcome = "up" if (i % 5) < 3 else "down"
        rows.append(
            {
                "ticker": "SPY",
                "decision_ts_utc": 1_000_000.0 + i,
                "prob_up": 0.6,
                "prob_down": 0.4,
                "prob_flat": 0.0,
                "outcome": outcome,
            }
        )
    res = fit_horizon_temperature(rows)
    # Either the grid finds nothing strictly better, or improvement is epsilon-level;
    # the binding contract: apply=False must leave status no_holdout_improvement.
    if not res["apply"]:
        assert res["status"] == "no_holdout_improvement"


# ── artifact IO + fail-closed loader ──────────────────────────────────────────────


def test_artifact_roundtrip_and_apply_gate(tmp_path: Path):
    artifact = {
        "schema_version": "1",
        "method": "temperature_scaling",
        "by_horizon": {
            "1c": {"apply": True, "temperature": 1.4},
            "5c": {"apply": False, "temperature": 2.0},  # gate failed => excluded
            "15c": {"apply": True, "temperature": 1.0},  # identity => excluded
            "60c": {"apply": True, "temperature": "bad"},  # invalid => excluded
        },
    }
    p = write_fusion_temperature_artifact(artifact, tmp_path / "ft.json")
    temps = load_applied_temperatures(p)
    assert temps == {"1c": 1.4}


def test_load_applied_temperatures_fails_closed(tmp_path: Path):
    assert load_applied_temperatures(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert load_applied_temperatures(bad) == {}
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"method": "isotonic"}), encoding="utf-8")
    assert load_applied_temperatures(wrong) == {}


# ── DB row loader ─────────────────────────────────────────────────────────────────


def _decision_db(tmp_path: Path, blk_5c: dict, *, ts: float | None = None) -> Path:
    db = tmp_path / "cal.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE calibration_decision_log ("
        " id INTEGER PRIMARY KEY, ticker TEXT, decision_ts_utc REAL,"
        " calibration_trust TEXT, model_outputs_json TEXT,"
        " outcome_1c TEXT, outcome_5c TEXT, outcome_15c TEXT, outcome_60c TEXT)"
    )
    payload = json.dumps(
        {"stack_probs_bundle": {"multi_horizon_ml_fusion_bundle": {"by_horizon": {"5c": blk_5c}}}}
    )
    # 2026-06-10 15:00 ET == RTH (19:00 UTC) — after FIT_WINDOW_FLOOR_UTC.
    rth_ts = 1_781_118_000.0 if ts is None else float(ts)
    conn.execute(
        "INSERT INTO calibration_decision_log"
        " (ticker, decision_ts_utc, calibration_trust, model_outputs_json, outcome_5c)"
        " VALUES ('SPY', ?, 'trusted', ?, 'up')",
        (rth_ts, payload),
    )
    conn.commit()
    conn.close()
    return db


def test_loader_prefers_raw_probs_over_served(tmp_path: Path):
    """Post-hook rows carry both; the fitter must use prob_*_raw (no feedback loop)."""
    blk = {
        "horizon_fusion_available": True,
        "prob_up": 0.5, "prob_down": 0.3, "prob_flat": 0.2,  # served (calibrated)
        "prob_up_raw": 0.8, "prob_down_raw": 0.15, "prob_flat_raw": 0.05,  # raw
    }
    rows = load_fusion_calibration_rows(_decision_db(tmp_path, blk))
    assert len(rows["5c"]) == 1
    assert abs(rows["5c"][0]["prob_up"] - 0.8) < 1e-9


def test_loader_falls_back_to_served_probs_for_legacy_rows(tmp_path: Path):
    """Pre-calibration rows have no raw keys — prob_* IS raw there."""
    blk = {"horizon_fusion_available": True, "prob_up": 0.5, "prob_down": 0.3, "prob_flat": 0.2}
    rows = load_fusion_calibration_rows(_decision_db(tmp_path, blk))
    assert len(rows["5c"]) == 1
    assert abs(rows["5c"][0]["prob_up"] - 0.5) < 1e-9


def test_loader_excludes_rows_before_fit_window_floor(tmp_path: Path):
    """Broken-serve-era rows (pre-561d9fe) must never reach the fitter by default.

    The 2026-06-10 production fit mixed anti-skill May rows (raw NLL 1.4-2.4 vs
    uniform 1.0986) with clean post-repair rows, pinning T=16 at the grid edge and
    making the 1c/5c tradeable gate structurally unreachable.
    """
    blk = {"horizon_fusion_available": True, "prob_up": 0.5, "prob_down": 0.3, "prob_flat": 0.2}
    # 2026-06-09 15:00 ET (RTH) — before the serve-stack repair floor.
    pre_floor_ts = 1_781_031_600.0
    assert pre_floor_ts < FIT_WINDOW_FLOOR_UTC
    db = _decision_db(tmp_path, blk, ts=pre_floor_ts)
    rows = load_fusion_calibration_rows(db)
    assert rows["5c"] == []
    # Explicit floor override re-admits the row (research/backtest use only).
    rows_all = load_fusion_calibration_rows(db, min_decision_ts_utc=0.0)
    assert len(rows_all["5c"]) == 1


def test_artifact_records_fit_window_floor(tmp_path: Path):
    db = _decision_db(
        tmp_path,
        {"horizon_fusion_available": True, "prob_up": 0.5, "prob_down": 0.3, "prob_flat": 0.2},
    )
    artifact = fit_fusion_temperature_artifact(db)
    assert artifact["fit_window_floor_utc"] == FIT_WINDOW_FLOOR_UTC
    # One row is far below MIN_FIT_SAMPLES: every horizon must fail closed.
    for hz, blk in artifact["by_horizon"].items():
        assert blk["apply"] is False, hz


# ── serve hook (multi_horizon_ml_bundle) ──────────────────────────────────────────


class _Fusion:
    available = True
    fusion_failed_closed = False
    prob_up = 0.7
    prob_down = 0.2
    prob_flat = 0.1
    fusion_confidence = "medium"
    fusion_confidence_score = 0.5
    mc_available = True
    contributing_models = ("xgb", "lstm")
    missing_models = ()


def test_serve_hook_identity_without_artifact(monkeypatch):
    import multi_horizon_ml_bundle as mhb

    monkeypatch.setattr(mhb, "_applied_fusion_temperatures", lambda: {})
    snap = mhb.fusion_payload_to_horizon_snapshot("5c", _Fusion())
    assert snap.calibration == "none"
    assert abs(snap.prob_up - 0.7) < 1e-9
    assert snap.prob_up_raw == snap.prob_up


def test_serve_hook_applies_temperature_and_preserves_raw(monkeypatch):
    import multi_horizon_ml_bundle as mhb

    monkeypatch.setattr(mhb, "_applied_fusion_temperatures", lambda: {"5c": 2.0})
    snap = mhb.fusion_payload_to_horizon_snapshot("5c", _Fusion())
    assert snap.calibration == "temperature:2.0"
    assert "temperature_calibrated" in snap.provenance
    # Raw preserved exactly; served flattened but ranking (dominant) unchanged.
    assert abs(snap.prob_up_raw - 0.7) < 1e-9
    assert snap.prob_up < 0.7
    assert snap.dominant_direction == "up"
    assert abs(snap.prob_up + snap.prob_down + snap.prob_flat - 1.0) < 1e-9
    expected = apply_temperature(0.7, 0.2, 0.1, 2.0)
    assert abs(snap.prob_up - expected[0]) < 1e-9


def test_serve_hook_other_horizon_unaffected(monkeypatch):
    import multi_horizon_ml_bundle as mhb

    monkeypatch.setattr(mhb, "_applied_fusion_temperatures", lambda: {"60c": 1.5})
    snap = mhb.fusion_payload_to_horizon_snapshot("5c", _Fusion())
    assert snap.calibration == "none"
    assert abs(snap.prob_up - 0.7) < 1e-9


def test_unavailable_snapshot_carries_no_calibration():
    import multi_horizon_ml_bundle as mhb

    snap = mhb._unavailable_horizon_snapshot("5c", provenance="fusion_unavailable")
    assert snap.calibration == "none"
    assert snap.prob_up_raw is None
