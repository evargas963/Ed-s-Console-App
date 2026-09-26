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










# ── Ticker-agnostic calibration locks (2026-07-06) ──────────────────────────








def test_server_payload_attaches_fusion_calibration_provenance():
    """The Tier C payload must carry fusion_calibration_v1 so a host serving
    raw probabilities (no artifact) is detectable from any probe."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    assert 'ms_dict["fusion_calibration_v1"]' in src, (
        "payload lost the fusion-calibration provenance block"
    )
    assert "fusion_calibration_status" in src
