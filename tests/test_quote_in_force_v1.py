"""A trade is read against the quote in force when it was made, never a later one.

Schwab's LEVELONE update carries a trade (LAST_PRICE, LAST_SIZE, TRADE_TIME_MILLIS) with the quote
that followed it ("quotes may be recorded ahead of trades that triggered them", Lee and Ready
1991). So the bus keeps, beside a record's newest quote, the quote that one replaced
(stream_spine.MessageBus, read by stream_spine.quote_before), and the quote in force is the newer
of the two that Schwab timed (QUOTE_TIME_MILLIS) at or before the trade and on its ET date
(calc.l1_trade_observation.quote_in_force); with neither, no quote in force is known. The tape
keeps each print with it (tests/test_tape_lee_ready_v1.py, tests/test_options_flow_tape_v1.py).

Real data, each message as Schwab sent it: SPY 261120P00703000's 45 LEVELONE_OPTIONS messages of
2026-11-20 from 12:00:00 ET (tests/fixtures/real_spy_option_levelone_2026_11_20_1200et.json);
PCG's four LEVELONE_EQUITIES messages in 3 s of 2026-10-05
(tests/fixtures/real_stream_mix_2026_10_05_1400ct.json); SPY's last print of 2026-11-10's evening
and its first of 2026-11-11 (tests/fixtures/real_premarket_first_prints_2026_11_11.json); and
every /markets answer the tests hold (tests/fixtures/real_schwab_markets_*.json). Each expected
value is read off those messages here. A condition Schwab has not sent is INDUCED, and says so.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import calc.l1_trade_observation as l1
from option_contract import NO_TOP, StreamedTop
from stream_spine import MessageBus, quote_before
from tests.feed_live_helper import on_the_bus
from time_et import ET

FX = Path(__file__).parent / "fixtures"
OPT = "LEVELONE_OPTIONS"
EQ = "LEVELONE_EQUITIES"
#: the quote's fields, as Schwab names them
_QUOTE = ("BID_PRICE", "ASK_PRICE", "BID_SIZE", "ASK_SIZE", "QUOTE_TIME_MILLIS")
#: the put's messages in receive order, each with its receive time and its frame's Schwab time
_PUT = json.loads(
    (FX / "real_spy_option_levelone_2026_11_20_1200et.json").read_text(encoding="utf-8")
)["option"]["rows"]
#: PCG's messages of the 3 s, in receive order
_PCG = [
    m
    for m in json.loads(
        (FX / "real_stream_mix_2026_10_05_1400ct.json").read_text(encoding="utf-8")
    )["messages"]
    if m["service"] == EQ and m["item"]["key"] == "PCG"
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
    """The quote a symbol's record holds after `items`, merged here field by field as sent."""
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
    """The put's first eight messages, each changing its quote.

    The first record has no quote before it. After each later message the record keeps the quote
    it held just before, whole: the seventh message sends no BID_PRICE (the bid stood at 2.6), and
    the quote the eighth replaces has that bid with the seventh's ask, sizes and time.
    """
    bus = MessageBus()
    assert quote_before(None) == NO_TOP  # a symbol the bus holds no record of
    kept, read = [], []
    for row in _PUT[:8]:
        record = on_the_bus(bus, OPT, row["item"], row["ts_recv"], row["schwab_ts"])
        kept.append(record[1]["quote_before"])
        read.append(quote_before(record))
    assert kept[0] == {} and read[0] == NO_TOP
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
    assert read[7] == StreamedTop(
        bid=2.6, ask=2.62, bid_size=65, ask_size=102, quote_time_ms=1795194006309
    )
    # each is the quote of the messages before it, merged here
    assert read[1:] == [_quote([row["item"] for row in _PUT[:n]]) for n in range(1, 8)]


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
    kept before is still the first message's, not the one restated.
    """
    bus = MessageBus()
    for row in (_PUT[0], _PUT[1]):
        on_the_bus(bus, OPT, row["item"], row["ts_recv"], row["schwab_ts"])
    again = _PUT[1]
    record = on_the_bus(bus, OPT, again["item"], again["ts_recv"], again["schwab_ts"])
    assert record[1]["quote_before"] == {f: _PUT[0]["item"][f] for f in _QUOTE}
    assert quote_before(record) == _quote([_PUT[0]["item"]])


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
