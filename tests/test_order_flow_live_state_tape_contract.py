"""app.options.order_flow.state must preserve a genuinely-missing last-trade size as missing.

It must not coerce it to zero -- downstream order-flow consumers need to tell
"no size reported" apart from "size was zero".

Real data: Schwab's LEVELONE_EQUITIES messages of 2026-10-05 14:00:00-14:00:03 CT as the daemon
received them (real_stream_mix_2026_10_05_1400ct.json): $SPX's first print (an index: no
LAST_SIZE), and SPY's messages in receive order.
"""

from __future__ import annotations

import json
from pathlib import Path

import app.options.order_flow.engine as ofe
import app.options.order_flow.state as live_state

_MIX = [
    m
    for m in json.loads(
        (
            Path(__file__).resolve().parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json"
        ).read_text(encoding="utf-8")
    )["messages"]
    if m["service"] == "LEVELONE_EQUITIES"
]


def _sent(key: str) -> list[dict]:
    return [m for m in _MIX if m["item"]["key"] == key]


def test_live_state_preserves_missing_last_size_for_order_flow_consumers():
    sym = "$SPX"
    first = next(m for m in _sent(sym) if "LAST_PRICE" in m["item"])
    assert "LAST_SIZE" not in first["item"]
    live_state.clear_symbol(sym)
    try:
        live_state.push_level_one(sym, first["item"], ts_recv=first["ts_recv"])
        content = live_state.get_content_for_symbol(sym)
    finally:
        live_state.clear_symbol(sym)
    tape = [item for item in content if item["time_millis"] == first["item"]["TRADE_TIME_MILLIS"]]

    assert len(tape) == 1
    assert tape[0]["price"] == first["item"]["LAST_PRICE"]
    assert tape[0]["size"] is None
    assert tape[0]["time_millis"] == first["item"]["TRADE_TIME_MILLIS"]
    assert tape[0]["native_event_id"] is False
    assert tape[0]["receive_seq"] == 1
    assert ofe._compute_cum_delta_proxy({"content": content}) is None


def test_live_state_present_last_size_reaches_order_flow_consumers():
    """SPY: 775.565 x 40, then 775.57 with no size, then 775.565 x 49.

    The first print anchors the price; the second has no size and counts for nothing but its
    price; the third is a downtick from it, so the cumulative delta is -49.
    """
    sym = "SPY"
    prints = [
        (m["item"]["LAST_PRICE"], m["item"].get("LAST_SIZE"))
        for m in _sent(sym)
        if "LAST_PRICE" in m["item"]
    ]
    assert prints == [(775.565, 40), (775.57, None), (775.565, 49)]
    live_state.clear_symbol(sym)
    try:
        for m in _sent(sym):
            live_state.push_level_one(sym, m["item"], ts_recv=m["ts_recv"])
        content = live_state.get_content_for_symbol(sym)
    finally:
        live_state.clear_symbol(sym)

    assert ofe._compute_cum_delta_proxy({"content": content}) == -49
