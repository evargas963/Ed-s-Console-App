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

import app.options.order_flow.state as live_state
import calc.l1_trade_observation as l1
from stream_spine import MessageBus
from tests.feed_live_helper import apply_record, on_the_bus
from tests.shared_helpers import sent

EQ = "LEVELONE_EQUITIES"

_MIX = [
    m
    for m in json.loads(
        (
            Path(__file__).resolve().parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json"
        ).read_text(encoding="utf-8")
    )["messages"]
    if m["service"] == "LEVELONE_EQUITIES"
]


def test_live_state_preserves_missing_last_size_for_order_flow_consumers():
    sym = "$SPX"
    first = next(m for m in sent(_MIX, sym) if "LAST_PRICE" in m["item"])
    assert "LAST_SIZE" not in first["item"]
    live_state.clear_all_live_state()
    bus = MessageBus()
    live_state.bind_bus(bus.current)
    try:
        record = on_the_bus(bus, EQ, first["item"], first["ts_recv"])
        apply_record(live_state._LIVE_STATE, EQ, record)
        content = live_state.prints(sym)
    finally:
        live_state.clear_all_live_state()
    tape = [item for item in content if item.time_millis == first["item"]["TRADE_TIME_MILLIS"]]

    assert len(tape) == 1
    assert tape[0].price == first["item"]["LAST_PRICE"]
    assert tape[0].size is None
    assert tape[0].time_millis == first["item"]["TRADE_TIME_MILLIS"]
    assert l1.compute_cum_delta_proxy(content) is None


def test_live_state_present_last_size_reaches_order_flow_consumers():
    """SPY: 775.565 x 40, then 775.57 with no LAST_SIZE, then 775.565 x 49, then 250 with no price.

    LEVELONE_EQUITIES is delivered on Change (Schwab Streamer API §1.5): a field not sent is
    unchanged, so the second print's size is the first's, 40, and the fourth (a new trade time) is
    a trade of 250 at the unchanged price; SPY's record on the bus holds them so. Every print's
    size reaches the consumers. These messages carry no bid or ask, so Lee and Ready signs none
    of them: the whole size is unsigned and the cumulative delta is no value, never 0.
    """
    sym = "SPY"
    prints = [
        (m["item"]["LAST_PRICE"], m["item"].get("LAST_SIZE"))
        for m in sent(_MIX, sym)
        if "LAST_PRICE" in m["item"]
    ]
    assert prints == [(775.565, 40), (775.57, None), (775.565, 49)]
    live_state.clear_all_live_state()
    bus = MessageBus()
    live_state.bind_bus(bus.current)
    try:
        for m in sent(_MIX, sym):
            apply_record(live_state._LIVE_STATE, EQ, on_the_bus(bus, EQ, m["item"], m["ts_recv"]))
        content = live_state.prints(sym)
    finally:
        live_state.clear_all_live_state()

    assert [size for _x, size, _s in l1._signed_walk(content, None)] == [40, 40, 49, 250]
    assert l1.compute_cum_delta_proxy(content) is None
