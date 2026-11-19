"""Each trade is a print, signed by Lee and Ready against the bid and ask Schwab sent with it.

Schwab's LEVELONE stream sends only the fields that changed (Streamer API §1.5, Change), so a trade
at the last trade's price arrives with a new TRADE_TIME_MILLIS and LAST_SIZE and no LAST_PRICE. The
daemon's bus merges each message into the symbol's current record (stream_spine.MessageBus), and
the console takes that record (streaming._ingest_pushed); the tape (state.push_level_one) keeps
each new (time, price, size) as a print, stamped with the receive time of the message that made it.

Schwab sends no buyer or seller side (docs/schwab/schwab_support_emails_2026_10_12.txt). The tape
signs each print by Lee and Ready (1991): above the midpoint of the bid and ask its record holds,
+1; below, -1; at it, the tick test (the price before; unchanged, the last change's sign). A print
with no bid and ask, or at the midpoint before any price change, is unsigned, and its share of the
size is served beside each value.

Real data: SPY's LEVELONE_EQUITIES messages of 2026-11-13 10:00:00-10:02:00 ET as the daemon
recorded them (tests/fixtures/real_spy_levelone_2026_11_13_1000et.json), 113 messages, 4 of them
trades at an unchanged price, through the daemon's bus and the console's intake
(streaming._ingest_pushed) as production takes them. The expected prints and signs are worked out
here by merging the messages' fields in order.
"""

from __future__ import annotations

import json
from pathlib import Path

import app.options.order_flow.state as state
import app.options.order_flow.streaming as ofs
import calc.l1_trade_observation as l1
from calc import order_flow as ofe
from feed.connection import SERVICE_TOPIC, held_key
from stream_spine import MessageBus, quote_msg

_MSGS = json.loads(
    (Path(__file__).parent / "fixtures" / "real_spy_levelone_2026_11_13_1000et.json").read_text(
        encoding="utf-8"
    )
)["messages"]
_FIELDS = ("TRADE_TIME_MILLIS", "LAST_PRICE", "LAST_SIZE", "BID_PRICE", "ASK_PRICE")


def _expected() -> list[tuple[float, float | None]]:
    """(size, signed size or None) of each new print, signed here from the merged fields."""
    held: dict[str, float] = {}
    out, last_triple, prev, last_tick = [], None, None, None
    for m in _MSGS:
        held.update({f: m["item"][f] for f in _FIELDS if f in m["item"]})
        if "LAST_PRICE" not in held:
            continue
        triple = (held["TRADE_TIME_MILLIS"], held["LAST_PRICE"], held.get("LAST_SIZE"))
        if triple == last_triple:
            continue
        last_triple = triple
        price = held["LAST_PRICE"]
        if prev is None:
            tick = None
        elif price == prev:
            tick = last_tick
        else:
            tick = 1 if price > prev else -1
        mid = (held["BID_PRICE"] + held["ASK_PRICE"]) / 2.0
        sign = 1 if price > mid else -1 if price < mid else tick
        if triple[2] is not None:  # a print with no size adds nothing, and still sets the price
            out.append((triple[2], None if sign is None else sign * triple[2]))
        if tick is not None:
            last_tick = tick
        prev = price
    return out


def _expected_prints() -> list[tuple[float, float, float | None, int]]:
    """(receive time, price, size, trade time) of each new print, merging fields as sent."""
    held: dict[str, object] = {}
    out, last = [], None
    for m in _MSGS:
        held.update({f: m["item"][f] for f in _FIELDS if f in m["item"]})
        if "LAST_PRICE" not in held:
            continue
        triple = (held["TRADE_TIME_MILLIS"], held["LAST_PRICE"], held.get("LAST_SIZE"))
        if triple != last:
            out.append((m["ts_recv"], triple[1], triple[2], triple[0]))
            last = triple
    return out


def _tape() -> list:
    """SPY's captured messages through the bus and the console's intake: the tape it keeps."""
    state.clear_all_live_state()
    _kind, src = SERVICE_TOPIC["LEVELONE_EQUITIES"]
    bus = MessageBus()
    key = held_key("LEVELONE_EQUITIES", "SPY")
    try:
        for m in _MSGS:
            bus.publish(
                "quote.SPY",
                quote_msg(symbol="SPY", src=src, native=m["item"], ts_recv=m["ts_recv"]),
            )
            ofs._ingest_pushed("quote.SPY", bus.current[key][1])
        return state.prints("SPY")
    finally:
        state.clear_all_live_state()


def test_every_trade_is_a_print_received_when_its_message_was():
    prints = _tape()
    want = _expected_prints()
    got = [(p["server_received_ts"], p["price"], p["size"], p["time_millis"]) for p in prints]
    assert got == want[-state.MAX_TAPE_PRINTS :]
    unchanged = [
        m["ts_recv"]
        for m in _MSGS
        if "TRADE_TIME_MILLIS" in m["item"] and "LAST_PRICE" not in m["item"]
    ]
    assert len(unchanged) == 4
    # each trade at an unchanged price is a print, stamped with its own message's receive time
    assert set(unchanged) <= {ts for ts, _p, _s, _t in got}


def test_each_print_is_signed_against_the_quote_its_record_held():
    prints = _tape()
    want = _expected()
    assert len(prints) <= state.MAX_TAPE_PRINTS  # the tape kept every print of the two minutes
    got = [(size, signed) for _x, size, signed in l1._signed_walk(prints, None)]
    assert got == want
    # the quote held is Schwab's, carried on the print
    assert all(p["bid"] is not None and p["ask"] is not None for p in prints)
    # both sides occur in two minutes of SPY: the method is not one-sided
    assert {s > 0 for _sz, s in want if s} == {True, False}


def test_the_cumulative_delta_and_its_unsigned_share_are_served():
    content = _tape()
    want = _expected()
    signed = [s for _sz, s in want if s is not None]
    total = sum(sz for sz, _s in want)
    unsigned = sum(sz for sz, s in want if s is None)
    out = ofe.OrderFlowEngine().compute(
        ofe.FlowInput(book=None, prints=content), now=_MSGS[-1]["ts_recv"]
    )
    assert out["cum_delta_proxy"] == sum(signed)
    assert out["cum_delta_unsigned"] == unsigned / total


def test_a_print_with_no_quote_is_unsigned_and_nothing_signed_is_no_value():
    """No bid and ask, no sign; a tape of only unsigned prints has no cumulative delta, never 0."""
    prints = [
        {"price": 754.38, "size": 100, "time_millis": 1, "bid": None, "ask": None},
        {"price": 754.40, "size": 50, "time_millis": 2, "bid": None, "ask": None},
    ]
    assert l1.compute_cum_delta_proxy(prints) is None
    assert l1.unsigned_share(prints) == 1.0
    assert l1.compute_tape_pressure(prints, 60.0, 2.0) is None


def test_lee_ready_signs_by_the_midpoint_and_the_tick_test_only_at_it():
    assert l1.trade_sign(754.38, 754.32, 754.37, None) == 1  # above the ask
    assert l1.trade_sign(754.33, 754.32, 754.37, 1) == -1  # below the midpoint 754.345
    assert l1.trade_sign(754.345, 754.32, 754.37, -1) == -1  # at it: the tick test
    assert l1.trade_sign(754.345, 754.32, 754.37, None) is None
    assert l1.trade_sign(754.345, None, 754.37, 1) is None
