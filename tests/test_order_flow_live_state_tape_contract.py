"""The console's one tape (app.options.order_flow.history.TAPE) must preserve a genuinely-missing
last-trade size as missing, not coerce it to zero -- downstream order-flow consumers need to tell
"no size reported" apart from "size was zero"."""
from __future__ import annotations
import time

import app.options.order_flow.engine as ofe
from app.options.order_flow import history


def test_live_state_preserves_missing_last_size_for_order_flow_consumers():
    sym = "MISSIZE"
    history.TAPE.forget(sym)
    history.TAPE.record_equity(
        sym,
        {
            "key": sym,
            "LAST_PRICE": 500.0,
            "TRADE_TIME_MILLIS": 1_000,
        }, ts_recv=time.time()
    )

    prints = history.TAPE.prints(sym)
    tape = [p for p in prints if p.get("time_millis") == 1_000]

    assert len(tape) == 1
    assert tape[0]["price"] == 500.0
    assert tape[0]["size"] is None
    assert tape[0]["time_millis"] == 1_000
    assert ofe._compute_cum_delta_proxy({"prints": prints}) is None
    history.TAPE.forget(sym)


def test_live_state_present_last_size_reaches_order_flow_consumers():
    sym = "HASSIZE"
    history.TAPE.forget(sym)
    # First print anchors the prior trade price; second print is on the
    # uptick (500.0 -> 500.1) so cum_delta should be the second print's size.
    history.TAPE.record_equity(
        sym,
        {
            "key": sym,
            "LAST_PRICE": 500.0,
            "LAST_SIZE": 10,
            "TRADE_TIME_MILLIS": 1_000,
        }, ts_recv=time.time()
    )
    history.TAPE.record_equity(
        sym,
        {
            "key": sym,
            "LAST_PRICE": 500.1,
            "LAST_SIZE": 12,
            "TRADE_TIME_MILLIS": 2_000,
        }, ts_recv=time.time()
    )

    prints = history.TAPE.prints(sym)

    assert ofe._compute_cum_delta_proxy({"prints": prints}) == 12
    history.TAPE.forget(sym)
