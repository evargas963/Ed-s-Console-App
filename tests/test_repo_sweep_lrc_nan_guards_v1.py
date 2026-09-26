"""REPO_SWEEP SWEEP-LRC-NAN: lifecycle_rule_core NaN guards (OBS-LRC-3 + OBS-LRC-4)."""

from __future__ import annotations

import re
from pathlib import Path



_LIFECYCLE_NAN_PASSTHROUGH = re.compile(r"return\s+float\(distance_pct\)")
_LIFECYCLE_CORE = Path(__file__).resolve().parents[1] / "lifecycle_rule_core.py"


def _bar(*, high: float, low: float) -> dict:
    return {"candle_high": high, "candle_low": low}










def test_lifecycle_nan_passthrough_pattern_banned_in_production():
    src = _LIFECYCLE_CORE.read_text(encoding="utf-8")
    matches = _LIFECYCLE_NAN_PASSTHROUGH.findall(src)
    assert matches == []


