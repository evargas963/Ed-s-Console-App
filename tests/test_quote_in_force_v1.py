"""A trade is read against the quote in force when it was made, never a later one.

Schwab's LEVELONE update carries a trade (LAST_PRICE, LAST_SIZE, TRADE_TIME_MILLIS) with the quote
that followed it ("quotes may be recorded ahead of trades that triggered them", Lee and Ready
1991). So the bus keeps, beside a record's newest quote, the quote that one replaced, and the two
as they stood when its last trade came (stream_spine.MessageBus, read by
stream_spine.quotes_at_trade); the quote in force is the newer of those two that Schwab timed
(QUOTE_TIME_MILLIS) at or before the trade and on its ET date
(calc.l1_trade_observation.quote_in_force); with neither, no quote in force is known. The tape
keeps each print with it (tests/test_tape_lee_ready_v1.py, tests/test_options_flow_tape_v1.py),
however late the console takes the record.

Real data, each message as Schwab sent it: SPY 261120P00703000's 45 LEVELONE_OPTIONS messages of
2026-11-20 from 12:00:00 ET (tests/fixtures/real_spy_option_levelone_2026_11_20_1200et.json);
every LEVELONE message of 3 s of 2026-10-05, PCG's four among them
(tests/fixtures/real_stream_mix_2026_10_05_1400ct.json); AMD's 14 of 2026-11-18
(tests/fixtures/real_amd_levelone_restated_2026_11_18.json); SPY's last print of 2026-11-10's
evening and its first of 2026-11-11 (tests/fixtures/real_premarket_first_prints_2026_11_11.json);
and every /markets answer the tests hold (tests/fixtures/real_schwab_markets_*.json). Each
expected value is read off those messages here. A condition Schwab has not sent is INDUCED, and
says so.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import calc.l1_trade_observation as l1
from app.options.order_flow.state import OrderFlowState
from option_contract import NO_TOP, StreamedTop
from stream_spine import MessageBus, held_key, quotes_at_trade
from tests.feed_live_helper import apply_record, on_the_bus
from time_et import ET

FX = Path(__file__).parent / "fixtures"
OPT = "LEVELONE_OPTIONS"
EQ = "LEVELONE_EQUITIES"
#: the quote's fields, as Schwab names them
_QUOTE = ("BID_PRICE", "ASK_PRICE", "BID_SIZE", "ASK_SIZE", "QUOTE_TIME_MILLIS")
#: the last trade's fields, as Schwab names them
_TRADE = ("LAST_PRICE", "LAST_SIZE", "TRADE_TIME_MILLIS")
#: the put's messages in receive order, each with its receive time and its frame's Schwab time
_PUT = json.loads(
    (FX / "real_spy_option_levelone_2026_11_20_1200et.json").read_text(encoding="utf-8")
)["option"]["rows"]
#: the LEVELONE messages of the 3 s, in receive order
_MIX = [
    m
    for m in json.loads(
        (FX / "real_stream_mix_2026_10_05_1400ct.json").read_text(encoding="utf-8")
    )["messages"]
    if m["service"] in (EQ, OPT)
]
#: PCG's messages of the 3 s, in receive order
_PCG = [m for m in _MIX if m["service"] == EQ and m["item"]["key"] == "PCG"]
#: AMD's 14 messages of 2026-11-18 around a subscription's whole record, in receive order
_AMD = json.loads((FX / "real_amd_levelone_restated_2026_11_18.json").read_text(encoding="utf-8"))[
    "messages"
]
#: SPY's last print of 2026-11-10's evening, then its first of 2026-11-11
_EVENING, _FIRST = (
    m["item"]
    for m in json.loads(
        (FX / "real_premarket_first_prints_2026_11_11.json").read_text(encoding="utf-8")
    )["messages"]
    if m["ticker"] == "SPY"
)


def _quote(items: list[dict]) -> StreamedTop:
    """Merge `items` field by field as sent: the quote a symbol's record holds after them."""
    held: dict = {}
    for item in items:
        held.update({f: item[f] for f in _QUOTE if f in item})
    return StreamedTop(
        bid=held["BID_PRICE"],
        ask=held["ASK_PRICE"],
        bid_size=held["BID_SIZE"],
        ask_size=held["ASK_SIZE"],
        quote_time_ms=held["QUOTE_TIME_MILLIS"],
    )


# ── the bus keeps the quote the newest quote replaced ────────────────────────────────────────


def test_a_record_keeps_whole_the_quote_its_newest_quote_replaced():
    """The put's first eight messages, each changing its quote and bringing a new trade.

    The first record has no quote before it. After each later message the record keeps the quote
    it held just before, whole: the seventh message sends no BID_PRICE (the bid stood at 2.6), and
    the quote the eighth replaces has that bid with the seventh's ask, sizes and time. Each brings
    a new trade, so the quotes kept with the record's trade are its newest and that one.
    """
    bus = MessageBus()
    assert quotes_at_trade(None) == (NO_TOP, NO_TOP)  # a symbol the bus holds no record of
    kept, read = [], []
    for row in _PUT[:8]:
        record = on_the_bus(bus, OPT, row["item"], row["ts_recv"], row["schwab_ts"])
        kept.append(record[1]["quote_before"])
        read.append(quotes_at_trade(record))
    items = [row["item"] for row in _PUT]
    assert kept[0] == {} and read[0] == (_quote(items[:1]), NO_TOP)
    assert kept[1] == {
        "BID_PRICE": 2.46,
        "ASK_PRICE": 2.47,
        "BID_SIZE": 77,
        "ASK_SIZE": 8,
        "QUOTE_TIME_MILLIS": 1795193999808,
    }
    assert "BID_PRICE" not in _PUT[6]["item"]
    assert kept[6] == {
        "BID_PRICE": 2.6,
        "ASK_PRICE": 2.61,
        "BID_SIZE": 50,
        "ASK_SIZE": 56,
        "QUOTE_TIME_MILLIS": 1795194005257,
    }
    assert kept[7] == {
        "BID_PRICE": 2.6,
        "ASK_PRICE": 2.62,
        "BID_SIZE": 65,
        "ASK_SIZE": 102,
        "QUOTE_TIME_MILLIS": 1795194006309,
    }
    assert read[7][1] == StreamedTop(
        bid=2.6, ask=2.62, bid_size=65, ask_size=102, quote_time_ms=1795194006309
    )
    # each is the quote of the messages up to it, and of those before it, merged here
    assert read[1:] == [(_quote(items[: n + 1]), _quote(items[:n])) for n in range(1, 8)]


def test_a_message_with_no_quote_field_leaves_the_quote_kept_before():
    """PCG's four messages of the 3 s, in receive order.

    The capture opens mid-stream, so each carries only what changed. The second and the third
    bring a new quote time (and an ask size), and the record keeps the quote fields it held just
    before each. The fourth is the day's volume alone: it brings no quote field, and the quote
    kept before stands as it was.
    """
    assert [[f for f in _QUOTE if f in m["item"]] for m in _PCG] == [
        ["BID_SIZE", "QUOTE_TIME_MILLIS"],
        ["ASK_SIZE", "QUOTE_TIME_MILLIS"],
        ["ASK_SIZE", "QUOTE_TIME_MILLIS"],
        [],
    ]
    bus = MessageBus()
    kept = [
        on_the_bus(bus, EQ, m["item"], m["ts_recv"], m["schwab_ts"])[1]["quote_before"]
        for m in _PCG
    ]
    assert kept == [
        {},
        {"BID_SIZE": 11700, "QUOTE_TIME_MILLIS": 1791226798622},
        {"BID_SIZE": 11700, "ASK_SIZE": 21300, "QUOTE_TIME_MILLIS": 1791226799478},
        {"BID_SIZE": 11700, "ASK_SIZE": 21300, "QUOTE_TIME_MILLIS": 1791226799478},
    ]


def test_an_older_message_taken_late_does_not_move_the_quote_kept_before():
    """INDUCED: PCG's first message put on the bus last, after the two that followed it.

    Schwab's frame time makes it the oldest of the three. The record holds a newer quote time, so
    its own is not taken; its BID_SIZE, which the record was never sent, is. The quote kept before
    is still the one the third message replaced: an older message is not the newest quote.
    """
    first, second, third, _volume = _PCG
    assert first["schwab_ts"] < second["schwab_ts"] < third["schwab_ts"]
    bus = MessageBus()
    for m in (second, third):
        on_the_bus(bus, EQ, m["item"], m["ts_recv"], m["schwab_ts"])
    _topic, record = on_the_bus(bus, EQ, first["item"], first["ts_recv"], first["schwab_ts"])
    assert record["native"]["BID_SIZE"] == 11700
    assert record["native"]["QUOTE_TIME_MILLIS"] == 1791226800538
    assert record["quote_before"] == {"ASK_SIZE": 21300, "QUOTE_TIME_MILLIS": 1791226799478}


def test_a_message_delivered_twice_does_not_move_the_quote_kept_before():
    """INDUCED: the put's second message put on the bus twice.

    The second delivery restates the quote the record holds and changes none of it, so the quote
    kept before is still the first message's, not the one restated. It restates the trade too, no
    new trade: the quotes kept with the trade are still the second message's and the first's.
    """
    bus = MessageBus()
    for row in (_PUT[0], _PUT[1]):
        on_the_bus(bus, OPT, row["item"], row["ts_recv"], row["schwab_ts"])
    again = _PUT[1]
    record = on_the_bus(bus, OPT, again["item"], again["ts_recv"], again["schwab_ts"])
    assert record[1]["quote_before"] == {f: _PUT[0]["item"][f] for f in _QUOTE}
    assert quotes_at_trade(record) == (
        _quote([_PUT[0]["item"], _PUT[1]["item"]]),
        _quote([_PUT[0]["item"]]),
    )


# ── a console that takes a record late still reads each trade against its quote in force ─────


def _trade(record: tuple[str, dict]) -> tuple:
    """Return the last trade a record holds, its fields as merged."""
    topic, rec = record
    held = rec["content" if topic.startswith("optquote.") else "native"]
    return tuple(held.get(f) for f in _TRADE)


def _tapes(messages: list[dict]) -> tuple[OrderFlowState, OrderFlowState]:
    """Return the tapes of two consoles taking the records of `messages`, put on one bus as sent.

    The first takes every version of a record as it comes. INDUCED: the second is behind, and takes
    a symbol's record only once the next message brings a new trade, and at the end: the latest it
    can take while the record still holds the trade before.
    """
    bus, every, late = MessageBus(), OrderFlowState(), OrderFlowState()
    every.current = bus.current
    services = {}
    for m in messages:
        key = held_key(m["service"], m["item"]["key"].upper())
        services[key], waiting = m["service"], bus.current.get(key)
        record = on_the_bus(bus, m["service"], m["item"], m["ts_recv"], m["schwab_ts"])
        apply_record(every, m["service"], record)
        if waiting is not None and _trade(waiting) != _trade(record):
            late.current[key] = waiting
            apply_record(late, m["service"], waiting)
    for key, record in bus.current.items():
        late.current[key] = record
        apply_record(late, services[key], record)
    return every, late


def _kept(state: OrderFlowState, symbol: str) -> list[tuple]:
    """Return each print a tape kept: the trade, the quote in force with it, where it landed."""
    return [
        (p.price, p.size, p.time_millis, p.bid, p.ask, p.bid_size, p.ask_size, p.landed)
        for p in state.prints(symbol)
    ]


def test_a_print_keeps_its_quote_in_force_however_late_the_console_takes_the_record():
    """Every LEVELONE message of the 3 s, and AMD's 14, as sent; INDUCED: a console behind.

    The console takes a symbol's newest record, not each message (stream_spine LATEST), so when it
    is behind, the record it takes may hold a trade and quotes Schwab sent after it. Schwab sent
    such quotes alone: SPY 261016P00780000's 7.90 x 2 traded at ...798887 came with a quote timed
    ...799384, and the next message is a quote alone timed ...800570; the quote in force is the one
    before the trade's message, an ask size of 277 timed ...798368 (the capture opens mid-stream,
    so no bid or ask is held). AMD's 513.57 x 1 at ...816236 came with no quote of its own: the
    quote in force is 513.06 x 513.95, a bid size of 440, timed ...815669; three messages later the
    record holds two quotes after it (the subscription's whole record, then a quote alone). A
    console that takes the record that late keeps each print with the quote in force kept by a
    console that took every version, and where its price landed against it.
    """
    mix = {m["item"]["key"].upper() for m in _MIX}
    every, late = _tapes(_MIX)
    assert {s: _kept(late, s) for s in mix} == {s: _kept(every, s) for s in mix}
    assert sum(len(every.prints(s)) for s in mix) == 96
    assert _kept(late, "SPY   261016P00780000") == [
        (7.9, 2.0, 1791226798887, None, None, None, 277.0, "unknown"),
    ]
    every, late = _tapes(_AMD)
    assert _kept(late, "AMD") == _kept(every, "AMD")
    assert _kept(late, "AMD")[2] == (
        513.57,
        1.0,
        1795002816236,
        513.06,
        513.95,
        440.0,
        None,
        "inside_spread",
    )


# ── the quote in force: the newest Schwab timed at or before the trade, on its ET date ───────


def test_the_quote_in_force_is_the_newest_schwab_timed_at_or_before_the_trade():
    """Two of the put's prints, each with its record's quote and the quote before it, as sent.

    The 40th message's quote is timed at its trade: its own quote is in force, though the record
    keeps one before it. The second message's quote is timed 11 ms after its trade: the quote in
    force is the first message's, which it replaced.
    """
    items = [row["item"] for row in _PUT]
    own, before = _quote(items[:40]), _quote(items[:39])
    assert own == StreamedTop(
        bid=3.1, ask=3.11, bid_size=57, ask_size=97, quote_time_ms=1795194041192
    )
    assert before == StreamedTop(
        bid=3.03, ask=3.04, bid_size=59, ask_size=10, quote_time_ms=1795194040274
    )
    assert items[39]["TRADE_TIME_MILLIS"] == 1795194041192
    assert l1.quote_in_force(1795194041192, own, before) == own

    own, before = _quote(items[:2]), _quote(items[:1])
    trade = items[1]["TRADE_TIME_MILLIS"]
    assert own.quote_time_ms - trade == 11 and before.quote_time_ms < trade
    assert before == StreamedTop(
        bid=2.46, ask=2.47, bid_size=77, ask_size=8, quote_time_ms=1795193999808
    )
    assert l1.quote_in_force(trade, own, before) == before


def test_no_quote_is_in_force_when_schwab_timed_none_at_or_before_the_trade():
    """The put's first print as sent, then INDUCED conditions on its second.

    The first message's quote is timed 405 ms after its trade and its record has no quote before
    it: none is in force. INDUCED, with the second message's quote and the first's before it: no
    trade time; the first print's trade time, earlier than both quotes; and a quote with no time
    of Schwab's, which is never in force whatever it holds.
    """
    items = [row["item"] for row in _PUT]
    first = _quote(items[:1])
    made = items[0]["TRADE_TIME_MILLIS"]
    assert first.quote_time_ms - made == 405
    assert l1.quote_in_force(made, first, NO_TOP) == NO_TOP

    own, before = _quote(items[:2]), first
    trade = items[1]["TRADE_TIME_MILLIS"]
    assert l1.quote_in_force(None, own, before) == NO_TOP
    assert made < before.quote_time_ms < own.quote_time_ms
    assert l1.quote_in_force(made, own, before) == NO_TOP
    assert l1.quote_in_force(trade, own, replace(before, quote_time_ms=None)) == NO_TOP
    assert l1.quote_in_force(trade, replace(own, quote_time_ms=None), before) == before


def test_a_quote_of_an_earlier_et_date_is_not_in_force():
    """SPY's first print of 2026-11-11, with the evening's quote before it, as sent.

    Its own quote is timed 149 ms after the trade. The quote before is the evening's, timed
    2026-11-10 20:00:00.052 ET, eight hours before the trade at 04:00:00.912 ET: the market closed
    between them, so it is not in force and none is. INDUCED: the evening's quote timed at the
    first millisecond of 2026-11-11 ET is in force; a millisecond earlier it is not.
    """
    trade = _FIRST["TRADE_TIME_MILLIS"]
    own, before = _quote([_FIRST]), _quote([_EVENING])
    assert own.quote_time_ms - trade == 149
    timed = datetime.fromtimestamp(before.quote_time_ms / 1000, ET)
    assert timed.isoformat() == "2026-11-10T20:00:00.052000-05:00"
    made = datetime.fromtimestamp(trade / 1000, ET)
    assert made.isoformat() == "2026-11-11T04:00:00.912000-05:00"
    assert l1.quote_in_force(trade, own, before) == NO_TOP

    midnight = int(datetime(2026, 11, 11, tzinfo=ET).timestamp() * 1000)
    at_midnight = replace(before, quote_time_ms=midnight)
    assert l1.quote_in_force(trade, own, at_midnight) == at_midnight
    assert l1.quote_in_force(trade, own, replace(before, quote_time_ms=midnight - 1)) == NO_TOP


def test_no_window_schwab_sent_crosses_midnight_et():
    """Every window of every /markets answer the tests hold starts and ends on its own ET date.

    The date rule rests on it: a quote of an earlier ET date is not in force because every market
    Schwab lists is closed over midnight ET. The 376 answers (2026-09-30 to 2027-10-07 as Schwab
    answered on 2026-10-07, and 2026-11-02, 2026-11-11 and 2026-11-12 as the daemon recorded
    them) hold 1,349 windows. An answer with a window that crosses midnight ET fails here, and the
    date rule is reworked on it (23-hour trading: docs/SOURCES.md, trading-hours-2026-12-06).
    """
    answers = []
    for path in sorted(FX.glob("real_schwab_markets_*.json")):
        held = json.loads(path.read_text(encoding="utf-8"))
        if "answers" in held:
            sent = [json.loads(a["body"]) for a in held["answers"].values() if a["status"] == 200]
        else:
            assert held["status"] == 200
            sent = [held["body"]]
        answers += sent
    windows = [
        (product["date"], datetime.fromisoformat(w["start"]), datetime.fromisoformat(w["end"]))
        for body in answers
        for market in body.values()
        for product in market.values()
        if "sessionHours" in product
        for spans in product["sessionHours"].values()
        for w in spans
    ]
    assert (len(answers), len(windows)) == (376, 1349)
    for day, start, end in windows:
        assert start.astimezone(ET).date() == end.astimezone(ET).date() == date.fromisoformat(day)
