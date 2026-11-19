"""Schwab -> the tape. A print's size is the count Schwab sent; the screen rounds it.

Real data: SPY's LEVELONE_EQUITIES messages of 2026-11-13 from 10:00 ET as the capture daemon
recorded them (tests/fixtures/real_spy_levelone_2026_11_13_1000et.json).
"""

from __future__ import annotations

import json
from pathlib import Path

import calc.l1_trade_observation as l1
from app.options.order_flow.state import OrderFlowState

_MSGS = json.loads(
    (Path(__file__).parent / "fixtures" / "real_spy_levelone_2026_11_13_1000et.json").read_text(
        encoding="utf-8"
    )
)["messages"]


def test_a_print_keeps_the_size_schwab_sent():
    """LAST_SIZE is the count Schwab sent, and the signed size on the tape is that same count.

    The stream's first three messages hold one sized print: 92 shares at 754.29 against a
    754.30 / 754.32 quote, below its midpoint, so it signs -1 (each message through the live
    state, its top first as the console takes it).
    """
    printed = l1.extract_vendor_print(_MSGS[2]["item"])
    assert printed is not None and printed.size == 92
    state = OrderFlowState()
    for m in _MSGS[:3]:
        state.push_option_top("SPY", m["item"])
        state.push_level_one("SPY", m["item"], ts_recv=m["ts_recv"])
    points = l1.iter_signed_cum_points(state.prints("SPY"))
    assert points[-1][1] == -92
