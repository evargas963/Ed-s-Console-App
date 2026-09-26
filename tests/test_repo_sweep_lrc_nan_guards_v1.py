"""REPO_SWEEP SWEEP-LRC-NAN: lifecycle_rule_core NaN guards (OBS-LRC-3 + OBS-LRC-4)."""

from __future__ import annotations

import re
from pathlib import Path


from lifecycle_rule_core import (
    fire_exit,
)

_LIFECYCLE_NAN_PASSTHROUGH = re.compile(r"return\s+float\(distance_pct\)")
_LIFECYCLE_CORE = Path(__file__).resolve().parents[1] / "lifecycle_rule_core.py"


def _bar(*, high: float, low: float) -> dict:
    return {"candle_high": high, "candle_low": low}


def test_fire_exit_nan_max_hold_bars_defaults_to_1_not_value_error():
    bars = [_bar(high=102, low=100)] * 5
    with_nan = fire_exit(
        signal="long",
        stop=99.0,
        target=103.0,
        forward_bars=bars,
        max_hold_bars=float("nan"),  # type: ignore[arg-type]
    )
    one_bar = fire_exit(
        signal="long",
        stop=99.0,
        target=103.0,
        forward_bars=bars,
        max_hold_bars=1,
    )
    assert with_nan == one_bar
    assert with_nan.exit_reason == "time_expiry"








def test_lifecycle_nan_passthrough_pattern_banned_in_production():
    src = _LIFECYCLE_CORE.read_text(encoding="utf-8")
    matches = _LIFECYCLE_NAN_PASSTHROUGH.findall(src)
    assert matches == []


