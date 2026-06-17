"""STACK-WIRE-6a — replay hold bars single authority + parity (FIND-WIRE6-1..2)."""

from __future__ import annotations

import inspect
import re

import replay_hold_bars as rhb
from micro_structure import R_COMPRESSION, R_RANGE, R_TREND_UP
from time_et import RTH_END_MINS, RTH_OPEN_MINS, RTH_SESSION_MINUTES


def test_rth_session_minutes_authority():
    """FIND-WIRE6-1: RTH_SESSION_MINUTES derives from RTH_END_MINS − RTH_OPEN_MINS (= 390)."""
    assert RTH_SESSION_MINUTES == RTH_END_MINS - RTH_OPEN_MINS
    assert RTH_SESSION_MINUTES == 390


def test_replay_max_hold_bars_from_context_uses_rth_session_minutes_authority():
    """FIND-WIRE6-1: bare 390 magic replaced by RTH_SESSION_MINUTES; function caps via authority."""
    src = inspect.getsource(rhb.replay_max_hold_bars_from_context)
    assert re.search(r"(?<![\w.])390(?![\w.])", src) is None, "bare 390 still in source"
    assert "RTH_SESSION_MINUTES" in src
    # path-execution: cap behavior still holds
    assert rhb.replay_max_hold_bars_from_context({"replay_max_hold_bars": 500}) == RTH_SESSION_MINUTES
    assert rhb.replay_max_hold_bars_from_context({"replay_max_hold_bars": 15}) == 15


def test_trade_type_hold_bars_single_source_of_truth():
    """FIND-WIRE6-2: TRADE_TYPE_HOLD_BARS dict is the authority for both setup + fallback."""
    assert rhb.TRADE_TYPE_HOLD_BARS == {
        "trend_continuation": 60,
        "breakout": 15,
        "reversal": 20,
        "fade": 30,
        "mean_reversion": 30,
        "none": 0,
    }
    assert rhb.TRADE_TYPE_HOLD_BARS_DEFAULT == 30
    assert rhb.MICRO_REGIME_HOLD_BARS_COMPRESSION == 15


def test_for_trade_type_and_for_setup_none_parity():
    """FIND-WIRE6-2 parity fix: trade_type='none' returns 0 in BOTH paths (was 20 vs 0)."""
    assert rhb.replay_max_hold_bars_for_trade_type("none") == 0
    assert rhb.replay_max_hold_bars_for_setup(R_TREND_UP, "none") == 0
    # "none" wins over micro_regime override — no trade still means no hold
    assert rhb.replay_max_hold_bars_for_setup(R_COMPRESSION, "none") == 0
    assert rhb.replay_max_hold_bars_for_setup(R_RANGE, "none") == 0


def test_no_hardcoded_trade_type_branches_in_for_setup():
    """FIND-WIRE6-2: explicit per-trade-type if/return branches replaced by dict lookup."""
    src = inspect.getsource(rhb.replay_max_hold_bars_for_setup)
    for tk in ("fade", "breakout", "reversal", "trend_continuation", "mean_reversion"):
        assert f'trade_type == "{tk}"' not in src, f"hardcoded branch for trade_type=={tk!r} remains"
    assert "TRADE_TYPE_HOLD_BARS" in src
    assert "MICRO_REGIME_HOLD_BARS_COMPRESSION" in src
