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


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))



# ── apply_temperature ─────────────────────────────────────────────────────────────










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








# ── artifact IO + fail-closed loader ──────────────────────────────────────────────






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










# ── serve hook (multi_horizon_ml_bundle) ──────────────────────────────────────────


class _Fusion:
    available = True
    stack_directional_authorized = True
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


# ── Ticker-agnostic calibration locks (2026-07-06) ──────────────────────────


def test_calibration_application_is_ticker_agnostic_by_construction():
    """The ONE calibration door, fusion_payload_to_horizon_snapshot, must accept
    no ticker input and key the temperature lookup by horizon only — no ticker
    path can bypass or vary calibration."""
    import inspect
    import multi_horizon_ml_bundle as mhb

    sig = inspect.signature(mhb.fusion_payload_to_horizon_snapshot)
    assert list(sig.parameters) == ["hz", "fus"], (
        f"calibration door grew unexpected inputs: {list(sig.parameters)} — a "
        "ticker-dependent parameter could make calibration non-uniform"
    )
    src = inspect.getsource(mhb.fusion_payload_to_horizon_snapshot)
    assert "_applied_fusion_temperatures().get(hz)" in src, (
        "temperature lookup is no longer horizon-keyed"
    )
    assert "ticker" not in src.lower(), (
        "calibration door references a ticker — per-ticker calibration is not "
        "a supported surface"
    )


def test_calibration_uniform_across_calls_and_argmax_preserved(monkeypatch):
    """Identical fusion triplets calibrate identically on every call (no ticker
    context exists to diverge on); argmax and ordering never change; raw probs
    are preserved; stronger T flattens more."""
    import multi_horizon_ml_bundle as mhb

    monkeypatch.setattr(
        mhb, "_applied_fusion_temperatures",
        lambda: {"5c": 2.828427, "15c": 16.0, "60c": 16.0},
    )
    snaps = {}
    for hz in ("1c", "5c", "15c", "60c"):
        a = mhb.fusion_payload_to_horizon_snapshot(hz, _Fusion())
        b = mhb.fusion_payload_to_horizon_snapshot(hz, _Fusion())
        assert (a.prob_up, a.prob_down, a.prob_flat) == (b.prob_up, b.prob_down, b.prob_flat), (
            f"{hz}: identical inputs calibrated differently across calls"
        )
        snaps[hz] = a
    assert snaps["1c"].calibration == "none"
    assert abs(snaps["1c"].prob_up - 0.7) < 1e-9
    for hz, t in (("5c", 2.828427), ("15c", 16.0), ("60c", 16.0)):
        s = snaps[hz]
        assert s.calibration == f"temperature:{t}"
        assert abs(s.prob_up_raw - 0.7) < 1e-9
        assert s.dominant_direction == "up", f"{hz}: argmax changed under calibration"
        assert s.prob_up < 0.7, f"{hz}: overconfident prob was not softened"
        assert s.prob_up > s.prob_down > s.prob_flat, f"{hz}: ordering not preserved"
    assert snaps["15c"].prob_up < snaps["5c"].prob_up


def test_fusion_calibration_status_exposes_host_artifact_state(monkeypatch):
    """Host-visibility lock: artifact_loaded=false + empty horizons IS the
    raw-serving fail-closed state — it must be observable and horizon-keyed."""
    import multi_horizon_ml_bundle as mhb

    monkeypatch.setattr(mhb, "_applied_fusion_temperatures", lambda: {})
    off = mhb.fusion_calibration_status()
    assert off == {
        "artifact_loaded": False,
        "applied_horizons": [],
        "applied_temperatures": {},
        "keying": "horizon_only",
    }
    monkeypatch.setattr(
        mhb, "_applied_fusion_temperatures", lambda: {"5c": 2.828427, "15c": 16.0}
    )
    on = mhb.fusion_calibration_status()
    assert on["artifact_loaded"] is True
    assert on["applied_horizons"] == ["15c", "5c"]
    assert on["applied_temperatures"]["5c"] == 2.828427
    assert on["keying"] == "horizon_only"


def test_server_payload_attaches_fusion_calibration_provenance():
    """The Tier C payload must carry fusion_calibration_v1 so a host serving
    raw probabilities (no artifact) is detectable from any probe."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    assert 'ms_dict["fusion_calibration_v1"]' in src, (
        "payload lost the fusion-calibration provenance block"
    )
    assert "fusion_calibration_status" in src
