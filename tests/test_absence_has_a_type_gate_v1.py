"""RC-301 — absence-coerced-to-a-value class gate is present and enforced."""

from pathlib import Path

from tools.check_absence_has_a_type import violations

REPO = Path(__file__).resolve().parent.parent


def test_absence_gate_passes_on_this_tree():
    assert violations() == []


def test_absence_gate_is_wired_into_hardening():
    src = (REPO / ".github" / "workflows" / "hardening.yml").read_text(encoding="utf-8")
    assert "check_absence_has_a_type.py" in src


def test_parity_except_no_longer_returns_zero_literal():
    src = (REPO / "math_levels.py").read_text(encoding="utf-8")
    start = src.find("def parity_f_minus_spot_from_contracts")
    block = src[start : start + 400]
    assert "return None" in block
    assert "-> float | None" in block
