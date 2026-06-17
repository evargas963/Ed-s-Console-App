"""P3-8 regression guard: legacy _promote_candidate must not return to ml_scheduler.py."""
from __future__ import annotations

from pathlib import Path


def test_no_promote_candidate_symbol_in_ml_scheduler_source():
    src = Path(__file__).resolve().parents[1] / "ml_scheduler.py"
    text = src.read_text(encoding="utf-8")
    assert "_promote_candidate" not in text
