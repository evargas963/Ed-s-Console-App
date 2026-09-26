"""Action 11.8: signals.py fail-closed on missing MC / fusion attributes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


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












