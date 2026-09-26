"""STACK-WIRE-6a — replay hold bars single authority + parity (FIND-WIRE6-1..2)."""

from __future__ import annotations

import inspect
import re

import replay_hold_bars as rhb
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






