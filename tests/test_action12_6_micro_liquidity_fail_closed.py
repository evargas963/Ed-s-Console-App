"""Action 12.6: micro_structure + liquidity_value_engine fail-closed (full read fixes)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent








def test_liquidity_engine_no_hardcoded_500_reference():
    text = (ROOT / "liquidity_value_engine.py").read_text(encoding="utf-8")
    assert " or 500.0" not in text


def test_micro_structure_no_spot_500_default():
    text = (ROOT / "micro_structure.py").read_text(encoding="utf-8")
    assert "spot: float = 500.0" not in text
