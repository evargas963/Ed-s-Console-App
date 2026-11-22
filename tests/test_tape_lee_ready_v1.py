"""Each trade is a print, signed by Lee and Ready against the bid and ask in force when it traded.

Schwab's LEVELONE stream sends only the fields that changed (Streamer API §1.5, Change), so a trade
at the last trade's price arrives with a new TRADE_TIME_MILLIS and LAST_SIZE and no LAST_PRICE. The
daemon's bus merges each message into the symbol's current record (stream_spine.MessageBus), and
the console takes that record (streaming._ingest_pushed); the tape (state.push_level_one) keeps
each new (time, price, size) as a print, stamped with the receive time of the message that made it.

Schwab sends no buyer or seller side (docs/schwab/schwab_support_emails_2026_10_12.txt). The tape
signs each print by Lee and Ready (1991): above the midpoint of the bid and ask in force when it
traded, +1; below, -1; at it, the tick test (the price before; unchanged, the last change's sign).
The quote in force is the newest Schwab timed (QUOTE_TIME_MILLIS) at or before the trade
(TRADE_TIME_MILLIS): an update carries a trade with the quote that followed it, so its own quote
is the trade's only when timed no later than it; otherwise it is the quote the update replaced. A
print with no such bid and ask, or at the midpoint before any price change, is unsigned, and its
share of the size is served beside each value.

Real data: SPY's LEVELONE_EQUITIES messages of 2026-11-13 10:00:00-10:02:00 ET as the daemon
recorded them (tests/fixtures/real_spy_levelone_2026_11_13_1000et.json), 113 messages, 4 of them
trades at an unchanged price, through the daemon's bus and the console's intake
(streaming._ingest_pushed) as production takes them. The expected prints, quotes and signs are
worked out here by merging the messages' fields in order.
"""

from __future__ import annotations

import json
from pathlib import Path

import app.options.order_flow.state as state
import app.options.order_flow.streaming as ofs
import calc.l1_trade_observation as l1
from app.options.order_flow import history
from calc import order_flow as ofe
from option_contract import NO_GREEKS, NO_TOP
from stream_spine import SERVICE_TOPIC, MessageBus, held_key, quote_msg

_MSGS = json.loads(
    (Path(__file__).parent / "fixtures" / "real_spy_levelone_2026_11_13_1000et.json").read_text(
        encoding="utf-8"
    )
)["messages"]
_FIELDS = ("TRADE_TIME_MILLIS", "LAST_PRICE", "LAST_SIZE", "BID_PRICE", "ASK_PRICE")
#: the quote's fields: a message that changes one replaces the quote the record held
_QUOTE = ("BID_PRICE", "ASK_PRICE", "BID_SIZE", "ASK_SIZE", "QUOTE_TIME_MILLIS")
#: a print with no quote in force: no bid and no ask
_NO_QUOTE = (None, None)


def _walked() -> list[dict]:
    """Each new print, worked out here by merging the messages' fields in order.

    Its size, price and tick test; `in_force`, the (bid, ask) of the newest quote Schwab timed at
    or before the trade: the update's own when its QUOTE_TIME_MILLIS is not after the trade's
    TRADE_TIME_MILLIS, else the quote the update replaced when that one's is not, else _NO_QUOTE;
    `same`, the (bid, ask) of the print's own update; and `later`, whether Schwab timed that
    update's quote after the trade.
    """
    held: dict[str, float] = {}
    before: dict[str, float] = {}
    out, last_triple, prev, last_tick = [], None, None, None
    for m in _MSGS:
        item = m["item"]
        if any(f in item and f in held and item[f] != held[f] for f in _QUOTE):
            before = {f: held[f] for f in _QUOTE if f in held}
        held.update({f: item[f] for f in (*_FIELDS, *_QUOTE) if f in item})
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
        in_force = _NO_QUOTE
        for quote in (held, before):
            if "QUOTE_TIME_MILLIS" in quote and quote["QUOTE_TIME_MILLIS"] <= triple[0]:
                in_force = (quote.get("BID_PRICE"), quote.get("ASK_PRICE"))
                break
        out.append(
            {
                "size": triple[2],
                "price": price,
                "tick": tick,
                "in_force": in_force,
                "same": (held["BID_PRICE"], held["ASK_PRICE"]),
                "later": held["QUOTE_TIME_MILLIS"] > triple[0],
            }
        )
        if tick is not None:
            last_tick = tick
        prev = price
    return out


def _signed(walked: list[dict], quote: str) -> list[tuple[float, float | None]]:
    """(size, signed size or None) of each print with a size, signed against its `quote`.

    Lee and Ready: above the quote's midpoint +1, below -1, at it the tick test; no bid or no
    ask, no sign. A print with no size adds nothing.
    """
    out = []
    for w in walked:
        bid, ask = w[quote]
        if bid is None or ask is None:
            sign = None
        else:
            mid = (bid + ask) / 2.0
            sign = 1 if w["price"] > mid else -1 if w["price"] < mid else w["tick"]
        if w["size"] is not None:
            out.append((w["size"], None if sign is None else sign * w["size"]))
    return out


def _expected() -> list[tuple[float, float | None]]:
    """(size, signed size or None) of each new print, signed against the quote in force."""
    return _signed(_walked(), "in_force")


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
    state.bind_bus(bus.current)
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
    got = [(p.server_received_ts, p.price, p.size, p.time_millis) for p in prints]
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
    """The quote kept with a print is the one in force when it traded, never a later one.

    Of the 113 prints, 105 arrived in an update whose own quote Schwab timed after the trade.
    104 of them are read against the quote that update replaced, and the first has none before
    it: no bid and no ask, and it is unsigned. For 102 the bid or the ask in force is not the
    update's own. Read against their own update's quote instead, 54 of the 111 prints with a size
    would take the opposite sign.
    """
    prints = _tape()
    walked = _walked()
    want = _expected()
    assert len(prints) <= state.MAX_TAPE_PRINTS  # the tape kept every print of the two minutes
    got = [(size, signed) for _x, size, signed in l1._signed_walk(prints, None)]
    assert got == want
    # the quote carried on each print is Schwab's quote in force when it traded
    assert [(p.bid, p.ask) for p in prints] == [w["in_force"] for w in walked]
    assert sum(w["later"] for w in walked) == 105
    assert [w["in_force"] for w in walked].count(_NO_QUOTE) == 1 and walked[0]["size"] is None
    assert sum(w["in_force"] != w["same"] for w in walked) == 102
    # both sides occur in two minutes of SPY: the method is not one-sided
    assert {s > 0 for _sz, s in want if s} == {True, False}
    later = _signed(walked, "same")
    assert sum(a[1] * b[1] < 0 for a, b in zip(want, later, strict=True)) == 54


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
        history.quoted(l1.TradePrint(price, size, ms), 0.0, NO_TOP, NO_GREEKS)
        for price, size, ms in ((754.38, 100, 1), (754.40, 50, 2))
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
