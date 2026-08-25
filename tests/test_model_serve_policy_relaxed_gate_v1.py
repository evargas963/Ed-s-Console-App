"""Cursor-audit F10: the MODEL-04 serve-eligibility (vintage) gate must apply to the ACTIVE
canonical bundle even under ED_XGB_STRICT_ACTIVE_ONLY=0.

The byte-integrity boundary (Layer 2, _verify_governed_artifact) is already committed-policy-anchored
and AST-locked, so tampered bytes can never serve regardless of env. The residual hole was the
SELECTION gate: the MODEL-04 vintage check lived inside `if strict_active_only:`, so relaxing the
flag let the relaxed resolver land on models/active/* — whose bytes hash-verify against their own
manifest — and serve a WITHHELD / NOT_PROVEN vintage. The gate now runs on any path that resolves to
the active bundle; parallel/cascade/flat dev experiments (the flag's intended probing use) stay
ungated.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import ml_predict as mp
import model_serve_policy as msp


def _no_experiment(monkeypatch):
    monkeypatch.setattr(
        "arch_competition.stack_bundle_eval_v1.live_ablation_experiment_active", lambda: False)
    monkeypatch.setattr(
        "arch_competition.stack_bundle_eval_v1.ablation_scoring_pass_active", lambda: False)


def test_relaxed_mode_blocks_withheld_active_bundle_f10(monkeypatch):
    """ED_XGB_STRICT_ACTIVE_ONLY=0 + relaxed resolver landing on models/active/* + a WITHHELD
    vintage must still raise (no withheld-vintage serve)."""
    monkeypatch.setenv("ED_XGB_STRICT_ACTIVE_ONLY", "0")
    _no_experiment(monkeypatch)
    active_dir = mp.MODEL_DIR / "active" / "SPY"
    monkeypatch.setattr(msp, "bundle_serve_eligibility",
                        lambda t, hz, d: {"status": "SERVE_TEMPORARILY_WITHHELD",
                                          "reason": "pre-correctness vintage", "direct_serve_blocked": True})
    monkeypatch.setattr(mp, "_model_dir_for_ticker_relaxed", lambda bt, hz: active_dir)
    with pytest.raises(FileNotFoundError, match="MODEL_SERVE_POLICY"):
        mp._model_dir_for_ticker("SPY")


def test_relaxed_mode_does_not_gate_parallel_dev_dir_f10(monkeypatch):
    """The flag's intended dev use — probing a parallel/cascade challenger — is NOT gated: a
    parallel dir resolves and returns even while the eligibility oracle would block."""
    monkeypatch.setenv("ED_XGB_STRICT_ACTIVE_ONLY", "0")
    _no_experiment(monkeypatch)
    parallel_dir = mp.MODEL_DIR / "parallel" / "SPY"
    # oracle would block if consulted — proving it is NOT consulted for a non-active dir
    monkeypatch.setattr(msp, "bundle_serve_eligibility",
                        lambda t, hz, d: {"status": "NOT_PROVEN", "reason": "no manifest",
                                          "direct_serve_blocked": True})
    monkeypatch.setattr(mp, "_model_dir_for_ticker_relaxed", lambda bt, hz: parallel_dir)
    assert mp._model_dir_for_ticker("SPY") == parallel_dir


def test_relaxed_mode_serves_eligible_active_bundle_f10(monkeypatch):
    """A serve-eligible active bundle passes the gate even in relaxed mode."""
    monkeypatch.setenv("ED_XGB_STRICT_ACTIVE_ONLY", "0")
    _no_experiment(monkeypatch)
    active_dir = mp.MODEL_DIR / "active" / "SPY"
    monkeypatch.setattr(msp, "bundle_serve_eligibility",
                        lambda t, hz, d: {"status": "SERVE_ELIGIBLE", "reason": "recent vintage",
                                          "direct_serve_blocked": False})
    monkeypatch.setattr(mp, "_model_dir_for_ticker_relaxed", lambda bt, hz: active_dir)
    assert mp._model_dir_for_ticker("SPY") == active_dir
