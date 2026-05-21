"""STACK-WIRE-4 — contract + consumer-cone verification (FIND-WIRE4-1..4)."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import governed_stack_contract as gsc
from signal_types import TRADABLE_CANONICAL_PROVENANCE

_CONSUMER_CONE = (
    "signals.py",
    "market_state.py",
    "call_engine.py",
    "prediction_engine.py",
    "mc_fusion_adjustment.py",
    "multi_horizon_decision.py",
    "multi_horizon_ml_bundle.py",
    "features/fusion_policy_contract.py",
    "v2_decision/a1_raw_probability.py",
    "v2_decision/module_a_adapter.py",
)

_BANNED_PROVENANCE = (
    r'provenance\s*==\s*["\']bayesian_fusion["\']',
    r'provenance\s*!=\s*["\']fusion_unavailable["\']',
)
# Fusion availability must use fusion_is_authoritative (same rule as test_fusion_contract).
_FUSION_AVAILABLE_GETATTR = re.compile(
    r"""getattr\s*\(\s*_?fusion\w*\s*,\s*['"]available['"]\s*""",
    re.IGNORECASE,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_no_second_tradability_predicate_in_consumer_cone():
    root = _repo_root()
    offenders: list[str] = []
    for rel in _CONSUMER_CONE:
        path = root / rel
        src = path.read_text(encoding="utf-8")
        for pat in _BANNED_PROVENANCE:
            if re.search(pat, src):
                offenders.append(f"{rel}: provenance literal: {pat}")
        if _FUSION_AVAILABLE_GETATTR.search(src):
            offenders.append(f"{rel}: inline fusion getattr(available)")
    assert not offenders, offenders


def test_tradable_canonical_provenance_single_member():
    assert TRADABLE_CANONICAL_PROVENANCE == frozenset({"bayesian_fusion"})
    assert len(TRADABLE_CANONICAL_PROVENANCE) == 1


def test_governed_stack_contract_threshold_constants_exist_and_used():
    assert gsc.MC_BASE_MODEL_WEIGHT_XGBOOST == 0.40
    assert gsc.MC_BASE_MODEL_WEIGHT_LSTM == 0.35
    assert gsc.MC_BASE_MODEL_WEIGHT_TRANSFORMER == 0.25
    assert gsc.MC_DIRECTION_CONFIDENCE_HIGH_THRESHOLD == 0.5
    assert gsc.MC_DIRECTION_CONFIDENCE_MEDIUM_THRESHOLD == 0.4

    src = inspect.getsource(gsc.mc_model_direction_inputs)
    banned = [
        r"(?<![\w.])0\.40(?![\w.])",
        r"(?<![\w.])0\.35(?![\w.])",
        r"(?<![\w.])0\.25(?![\w.])",
        r"(?<![\w.])0\.5(?![\w.])",
        r"(?<![\w.])0\.4(?![\w.])",
    ]
    for pat in banned:
        assert re.search(pat, src) is None, f"literal still in mc_model_direction_inputs: {pat}"
    assert "MC_MODEL_CONF_HIGH_THRESHOLD" not in src
    assert "MC_MODEL_CONF_MEDIUM_THRESHOLD" not in src


def test_mc_model_direction_inputs_stack_probs_path_does_not_raise():
    out = gsc.mc_model_direction_inputs(
        xgb_out=None,
        lstm_out=None,
        transformer_out=None,
        stack_probs={"up": 0.5, "down": 0.3, "flat": 0.2},
    )
    assert out[2] in ("high", "medium", "low")
    assert out[4] == "stack_probs_meta_or_weighted"


def test_classify_stack_health_single_producer():
    root = _repo_root()
    skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", "tests", ".claude"}
    call_sites: list[str] = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] in skip_dirs:
            continue
        if any(part in skip_dirs for part in rel.parts):
            continue
        if rel.parts[0] == "tests":
            continue
        src = path.read_text(encoding="utf-8")
        for i, line in enumerate(src.splitlines(), 1):
            if "classify_stack_health(" not in line:
                continue
            if "def classify_stack_health" in line:
                continue
            call_sites.append(f"{rel}:{i}")
    assert call_sites == ["server.py:1995"], call_sites
