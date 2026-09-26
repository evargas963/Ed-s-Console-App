"""AUDIT_LANE lifecycle_rule_core — FIND-LRC-1..8 finite / fail-closed numerics."""

from __future__ import annotations



from lifecycle_rule_core import (
    fire_exit,
)


def _bar(high: float, low: float) -> dict:
    return {"candle_high": high, "candle_low": low}




















def test_lrc7_fire_exit_nan_stop_skips_not_time_expiry():
    outcome = fire_exit(
        signal="long",
        stop=float("nan"),
        target=103.0,
        forward_bars=[_bar(high=102, low=100)],
        max_hold_bars=5,
    )
    assert outcome.skip_reason == "missing_stop_target_for_exit"
    assert outcome.exit_reason is None


def test_lrc7_fire_exit_nan_target_skips():
    outcome = fire_exit(
        signal="long",
        stop=99.0,
        target=float("nan"),
        forward_bars=[_bar(high=102, low=100)],
        max_hold_bars=5,
    )
    assert outcome.skip_reason == "missing_stop_target_for_exit"




