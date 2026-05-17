"""Action 11.8: signals.py fail-closed on missing MC / fusion attributes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from signals import _build_stack_decision_path

ROOT = Path(__file__).resolve().parent.parent
SIGNALS = (ROOT / "signals.py").read_text(encoding="utf-8")

_FORBIDDEN_SIGNALS_PATTERNS = (
    'getattr(mc_out, "directional_bias", None) or 0.0',
    'getattr(mc_out, "tail_risk", None) or 0.0',
    '(exp or 0) >= (cont or 0)',
    '(exp if is_expansion else cont) or 0',
    'getattr(fusion, "dominant_outcome", "unknown")',
    'getattr(fusion, "dominant_probability", 0.0)',
    'getattr(fusion, "model_agreement", 0.0)',
)


def _call():
    return SimpleNamespace(signal="wait", conviction="low")


def test_signals_file_has_no_fail_open_mc_fusion_patterns():
    for pattern in _FORBIDDEN_SIGNALS_PATTERNS:
        assert pattern not in SIGNALS, f"fail-open pattern still present: {pattern}"


def test_support_note_none_when_directional_bias_absent():
    mc = SimpleNamespace(
        available=True,
        containment_prob=0.4,
        expansion_prob=0.3,
        tail_risk=0.1,
    )
    path = _build_stack_decision_path(None, None, None, mc, None, _call())
    assert "supports stack" not in path.monte_carlo.note
    assert "contradicts stack" not in path.monte_carlo.note


def test_skew_none_when_mc_directional_bias_absent():
    mc = SimpleNamespace(
        available=True,
        containment_prob=0.4,
        expansion_prob=0.3,
        tail_risk=0.1,
    )
    path = _build_stack_decision_path(None, None, None, mc, None, _call())
    assert "upside skew" not in path.monte_carlo.note
    assert "downside skew" not in path.monte_carlo.note


def test_skew_none_when_mc_out_missing():
    path = _build_stack_decision_path(None, None, None, None, None, _call())
    assert path.monte_carlo.status == "inactive"


def test_expansion_containment_skipped_when_both_none():
    mc = SimpleNamespace(available=True, directional_bias=0.2, tail_risk=0.1)
    path = _build_stack_decision_path(None, None, None, mc, None, _call())
    assert "expansion" not in path.monte_carlo.note.lower()
    assert "containment" not in path.monte_carlo.note.lower()


def test_dominant_none_when_fusion_absent():
    path = _build_stack_decision_path(None, None, None, None, None, _call())
    assert path.fusion.status == "inactive"


def test_fusion_probability_none_when_attribute_missing():
    fusion = SimpleNamespace(
        available=True,
        dominant_outcome="continuation",
        dominant_direction="up",
        fusion_confidence="medium",
    )
    path = _build_stack_decision_path(None, None, None, None, fusion, _call())
    assert path.fusion.probability is None
