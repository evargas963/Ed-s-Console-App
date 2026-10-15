"""Every Schwab service straight from the capture daemon to the screen (live_ui.py), end to end,
by its Schwab delivery type (Streamer API §1.1: Change, Whole, All Sequence).

The REAL daemon-side path: Schwab's frames into the daemon's own handler (capture._publisher), its
real bus (stream_spine.MessageBus), the real server (serve_live_ui), and a REAL WebSocket client
standing in for the page, over a real local socket. Real data: every message Schwab sent
2026-10-05 14:00:00-14:00:03 CT (tests/fixtures/real_stream_mix_2026_10_05_1400ct.json: 7,420
LEVELONE_OPTIONS, 152 LEVELONE_EQUITIES, 12 book messages), the daemon's record of SPY's and
TSLA's CHART_EQUITY bars and a NEWS_HEADLINE item. STAND-IN (named): the daemon's status each
beat reports (socket open, symbols held).
"""
from __future__ import annotations

import asyncio
import json
import socket
import time
from pathlib import Path

import pytest

from app.market_data.schwab.streaming import capture, live_ui
from minute_bars import CHART_1M_BARS
from stream_spine import HealthRegistry, MessageBus
from time_et import age_label, ct_label

FX = Path(__file__).resolve().parent / "fixtures"
_MIX = json.loads((FX / "real_stream_mix_2026_10_05_1400ct.json").read_text(encoding="utf-8"))["messages"]
_EVERY = sorted({m["item"]["key"] for m in _MIX})
#: the daemon's receipts of Schwab's CHART_EQUITY bars that carry Schwab's own item, in receive order
_BARS = sorted((r for r in json.loads((FX / "real_daemon_bars_spy_tsla_2026_10_01_02.json").read_text(
    encoding="utf-8"))["rows"] if r["native"]), key=lambda r: r["ts_recv"])
_NEWS = json.loads((FX / "real_schwab_news_headline_spx_2026_10_05.json").read_text(encoding="utf-8"))


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Feed:
    """The daemon's status as its heartbeat reports it (STAND-IN)."""

    def __call__(self) -> dict:
        return {"ts": time.time(), "schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": ["SPY"]}, "health": {}}


def _frame(bus, service: str, item: dict, schwab_ts) -> None:
    """One Schwab frame into the daemon's own handler for `service`, as schwab-py hands it."""
    capture._publisher(service, bus, HealthRegistry())({"timestamp": schwab_ts, "content": [item]})


class _Switch:
    """The daemon's status at `clock` (STAND-IN), its Schwab socket opened a minute before and
    closed on demand, holding `held` on LEVELONE_EQUITIES."""

    def __init__(self, clock, held=("SPY",)):
        self.clock, self.open, self.held, self.connected_at = clock, True, list(held), clock() - 60

    def __call__(self) -> dict:
        return {"ts": self.clock(), "schwab_socket_open": self.open, "connected_at": self.connected_at,
                "held": {"LEVELONE_EQUITIES": self.held}, "health": {}}


async def _run(body, feed=None, clock=time.time):
    """The daemon's server and a client on it."""
    from websockets.asyncio.client import connect

    port = _free_port()
    bus = MessageBus()
    stop = asyncio.Event()
    stats: dict = {}
    server = asyncio.create_task(live_ui.serve_live_ui(
        bus, stop, heartbeat_fn=feed if feed is not None else _Feed(), host="127.0.0.1", port=port, stats=stats,
        clock=clock))                                # the instant each beat's verdicts are judged at
    end = time.monotonic() + 5
    while not stats.get("listening") and time.monotonic() < end:
        await asyncio.sleep(0.01)
    assert stats.get("listening")
    try:
        async with connect(f"ws://127.0.0.1:{port}", max_size=None) as ws:
            await body(bus, ws, stats)
    finally:
        stop.set()
        await asyncio.wait_for(asyncio.gather(server, return_exceptions=True), 5)


async def _received(ws, quiet: float = 0.5, timeout: float = 20.0, until=None) -> "tuple[list[dict], list[dict]]":
    """(every Schwab message, every beat) the client receives: until `until(messages)` holds, when
    the test knows what it waits for (a loaded machine may pause longer than `quiet` mid-delivery),
    else until `quiet` s pass with no Schwab message; never past `timeout`."""
    messages, beats = [], []
    end, last = time.monotonic() + timeout, time.monotonic()
    while time.monotonic() < end and (until is not None or time.monotonic() - last < quiet):
        if until is not None and until(messages):
            break
        try:
            frame = json.loads(await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()) if until else quiet))
        except (asyncio.TimeoutError, TimeoutError):
            break
        if frame["type"] == "schwab":
            messages += frame["messages"]
            last = time.monotonic()
        elif frame["type"] == "feed":
            beats.append(frame)
    return messages, beats


async def _next(ws, kind: str, within: float = 5.0) -> dict:
    """The next frame of `kind`, within `within` s in all (the daemon beats every second, so a
    limit on each frame alone would never end the wait)."""
    async with asyncio.timeout(within):
        while (frame := json.loads(await ws.recv()))["type"] != kind:
            pass
    return frame


def test_every_service_reaches_the_screen_by_its_delivery_type():
    """Every symbol of the real mix subscribed, then every message Schwab sent, with the real
    CHART_EQUITY bars and NEWS_HEADLINE item behind it. Change (LEVELONE_EQUITIES,
    LEVELONE_OPTIONS): each symbol's fields as the last Schwab sent each, none lost. Whole
    (NYSE_BOOK, NASDAQ_BOOK, OPTIONS_BOOK): each book as Schwab sent it, the newest last. Sequence
    (CHART_EQUITY, NEWS_HEADLINE): every bar of the ticker the page's chart draws (SPY; TSLA's
    are sent to no page, which would drop them) and every headline, in the order Schwab sent them."""
    bars = [(r["native"], r["schwab_ts"]) for r in _BARS]
    spy = [b for b, _ts in bars if b["key"] == "SPY"]
    every = sorted({*_EVERY, *(b["key"] for b, _ts in bars), _NEWS["symbol"]})
    assert {b["key"] for b, _ts in bars} == {"SPY", "TSLA"}
    assert sorted(spy, key=lambda b: b["CHART_TIME_MILLIS"]) == spy   # each a new newest minute or the newest again

    async def body(bus, ws, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": every, "chart": "SPY"}))
        await _next(ws, "series")                 # the daemon has taken the subscription
        for m in _MIX:
            _frame(bus, m["service"], m["item"], m["schwab_ts"])
        for item, ts in bars:
            _frame(bus, "CHART_EQUITY", item, ts)
        _frame(bus, "NEWS_HEADLINE", _NEWS["content"], _NEWS["schwab_ts"])
        # sent last, in order: once every bar and the headline are in, everything sent before is
        got, _beats = await _received(ws, until=lambda ms: sum(m["service"] == "CHART_EQUITY" for m in ms) == len(spy)
                                      and any(m["service"] == "NEWS_HEADLINE" for m in ms))
        by = lambda svc: [m for m in got if m["service"] == svc]   # noqa: E731
        sent = lambda svc: [m for m in _MIX if m["service"] == svc]   # noqa: E731
        assert {m["service"] for m in got} == set(live_ui.DELIVERY)
        for svc in ("LEVELONE_EQUITIES", "LEVELONE_OPTIONS"):
            want: dict = {}
            for m in sent(svc):
                want.setdefault(m["item"]["key"], {}).update(m["item"])
            fields: dict = {}
            for m in by(svc):
                fields.setdefault(m["key"], {}).update(m["content"])
            assert fields == want, f"a {svc} field Schwab sent was lost or changed"
        for svc in ("NYSE_BOOK", "NASDAQ_BOOK", "OPTIONS_BOOK"):
            for key in {m["item"]["key"] for m in sent(svc)}:
                books = [m["item"] for m in sent(svc) if m["item"]["key"] == key]
                shown = [m["content"] for m in by(svc) if m["key"] == key]
                assert shown and shown[-1] == books[-1], f"{svc} {key}: the newest book is not the one shown"
                assert all(b in books for b in shown), f"{svc} {key}: a book was changed"
        assert [m["content"] for m in by("CHART_EQUITY")] == spy
        assert [m["content"] for m in by("NEWS_HEADLINE")] == [_NEWS["content"]]
    asyncio.run(_run(body))


def test_a_client_is_sent_only_the_services_it_reads():
    """The console reads only LEVELONE_EQUITIES from the daemon (streaming._rows_loop): it names
    that service and is sent no book, bar or headline."""
    async def body(bus, ws, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": _EVERY, "services": ["LEVELONE_EQUITIES"]}))
        for m in _MIX:
            _frame(bus, m["service"], m["item"], m["schwab_ts"])
        got, _beats = await _received(ws)
        assert got and {m["service"] for m in got} == {"LEVELONE_EQUITIES"}
    asyncio.run(_run(body))


async def _series_and_headlines(ws, timeout: float = 10.0) -> "tuple[dict, list[dict]]":
    """The chart's series frame and every headline message, read until the series has come and
    `timeout` s pass without a frame of either."""
    series, news, end = None, [], time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            frame = json.loads(await asyncio.wait_for(ws.recv(), 1.5 if series else timeout))
        except (asyncio.TimeoutError, TimeoutError):
            break
        if frame["type"] == "series":
            series = frame
        elif frame["type"] == "schwab":
            news += [m for m in frame["messages"] if m["service"] == "NEWS_HEADLINE"]
    return series, news


def test_a_page_that_reconnects_gets_every_bar_and_headline_it_missed_once_in_order():
    """Across a dropped connection: the real bars, the first half received in order (All
    Sequence), the connection drops, the second half and a real headline sent meanwhile; the page
    reconnects and gets its chart's series whole, every bar Schwab sent in it, and the headline
    it missed (after `since`) once; a page reconnecting with nothing new gets no headline again.
    STAND-IN (named): the
    headline's key, SPY."""
    from websockets.asyncio.client import connect

    bars = [(r["native"], r["schwab_ts"]) for r in _BARS if r["native"]["key"] == "SPY"]
    half = len(bars) // 2
    minutes = sorted({b["CHART_TIME_MILLIS"] / 1000.0 for b, _ts in bars})

    async def body(bus, ws, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"], "chart": "SPY"}))
        await _next(ws, "symbols")
        for item, ts in bars[:half]:
            _frame(bus, "CHART_EQUITY", item, ts)
        first, _beats = await _received(ws, until=lambda ms: len(ms) == half)
        assert [m["content"] for m in first] == [b for b, _ts in bars[:half]]
        await ws.close()                                   # the page's connection drops
        for item, ts in bars[half:]:
            _frame(bus, "CHART_EQUITY", item, ts)
        _frame(bus, "NEWS_HEADLINE", {**_NEWS["content"], "key": "SPY"}, _NEWS["schwab_ts"])
        async with connect(stats["listening"], max_size=None) as again:
            await again.send(json.dumps({"op": "subscribe", "symbols": ["SPY"], "chart": "SPY"}))
            series, news = await _series_and_headlines(again)
            assert [b["t"] for b in series["bars"]] == minutes, "a bar Schwab sent is missing from the series"
            assert [m["content"]["2"] for m in news] == [_NEWS["content"]["2"]]
            since = {"SPY": news[-1]["ts_recv"]}
        async with connect(stats["listening"], max_size=None) as third:   # nothing new: no headline again
            await third.send(json.dumps({"op": "subscribe", "symbols": ["SPY"], "chart": "SPY", "since": since}))
            series, news = await _series_and_headlines(third)
            assert news == [] and [b["t"] for b in series["bars"]] == minutes
    asyncio.run(_run(body))


def test_the_screens_1_minute_series_is_the_daemons_and_equals_the_consoles_bar_for_bar():
    """One producer of the 1-minute series (minute_bars): the daemon and the console, fed the same
    real /pricehistory answer (SPY, 2026-10-07) and the same real CHART_EQUITY bars (SPY,
    2026-10-01), hold the same bars. The page drawing SPY's chart is sent the series whole on
    subscribe (and again on the next /pricehistory answer), then each bar: one producer, so the
    page chooses between none."""
    import server
    from calibration.complete_chain_capture import price_history_message
    from tests.feed_live_helper import price_history

    answer = price_history("SPY", "1m")
    topic, msg = price_history_message("SPY", "1m", answer["body"], answer["answered_utc"])
    bars = [(r["native"], r["schwab_ts"]) for r in _BARS if r["native"]["key"] == "SPY"]
    server._bars.pop("SPY", None)

    async def body(bus, ws, stats):
        bus.publish(topic, msg)
        for item, ts in bars:
            _frame(bus, "CHART_EQUITY", item, ts)
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"], "chart": "SPY"}))
        frame = await _next(ws, "series")
        server._write_price_history(msg)                              # the console, the same inputs
        for item, ts in bars:
            _topic, m = capture._message("CHART_EQUITY", "SPY", item, ts)
            server._write_streamed_bar(m)
        console = server.bars_payload("SPY", CHART_1M_BARS, "1")["bars"]
        assert frame["key"] == "SPY" and len(frame["bars"]) == min(CHART_1M_BARS, len(console)) > len(bars)
        assert frame["bars"] == console, "the daemon's series and the console's differ"
        assert frame["last_bar"] == server.bars_payload("SPY", CHART_1M_BARS, "1")["last_bar"] == \
            {"t": console[-1]["t"], "label": ct_label(console[-1]["t"])}
        bus.publish(topic, msg)                                       # the next /pricehistory answer: whole again
        again = await _next(ws, "series")
        assert again["bars"] == console
    try:
        asyncio.run(_run(body))
    finally:
        server._bars.pop("SPY", None)


def test_the_series_is_sent_whole_for_a_new_chart_and_only_then():
    """A page's chart: its series whole on the first subscribe; the same chart asked again, typed
    another way too (SPX after $SPX), nothing more (the page holds it, keyed by the daemon's key);
    another chart, that one whole."""
    async def body(bus, ws, stats):
        async def series_after(req) -> "dict | None":
            await ws.send(json.dumps(req))
            got, end = None, time.monotonic() + 1.5
            while time.monotonic() < end:
                try:
                    frame = json.loads(await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic())))
                except (asyncio.TimeoutError, TimeoutError):
                    break
                if frame["type"] == "series":
                    got = frame
            return got
        first = await series_after({"op": "subscribe", "symbols": ["$SPX"], "chart": "$SPX"})
        assert first is not None and first["key"] == "$SPX"
        assert await series_after({"op": "subscribe", "symbols": ["$SPX"], "chart": "$SPX"}) is None
        assert await series_after({"op": "subscribe", "symbols": ["$SPX", "MU"], "chart": "SPX"}) is None
        other = await series_after({"op": "subscribe", "symbols": ["SPY"], "chart": "SPY"})
        assert other is not None and other["key"] == "SPY"
    asyncio.run(_run(body))


def test_each_bar_says_what_the_series_did_and_a_resent_series_sends_no_bar_twice():
    """The page applies each bar as the daemon's series took it, comparing nothing: a new newest
    minute (append), the newest minute again (replace), any other minute (insert: the series goes
    whole to each page drawing it, the bar in it, sent no other way). A series given whole drops
    the ticker's bars still queued for the page, which it holds; a page whose chart draws another
    ticker is sent none. Real bars (SPY, 2026-10-01); STAND-IN (named): a minute sent again."""
    srv = live_ui.LiveUiServer(MessageBus(), _Feed(), {})
    c, other = live_ui._Client(None), live_ui._Client(None)
    c.symbols, c.chart = frozenset({"SPY"}), "SPY"
    other.symbols, other.chart = frozenset({"SPY"}), "TSLA"
    srv.clients.update({c, other})
    items = [r["native"] for r in _BARS if r["native"]["key"] == "SPY"]
    firsts = list({it["CHART_TIME_MILLIS"]: it for it in items}.values())[:3]   # three minutes, in time

    def route(item):
        srv.route(*capture._message("CHART_EQUITY", "SPY", item, 1))
    for it in firsts:
        route(it)
    assert [m["series_op"] for m in c.sequence] == ["append", "append", "append"]
    route({**firsts[-1], "CLOSE_PRICE": firsts[-1]["CLOSE_PRICE"] + 0.01})
    assert c.sequence[-1]["series_op"] == "replace" and c.sequence[-1]["bar"]["c"] == firsts[-1]["CLOSE_PRICE"] + 0.01
    assert c.series is None
    route(firsts[0])                                                     # an older minute: whole again
    assert c.sequence == [] and [b["t"] for b in c.series["bars"]] == [it["CHART_TIME_MILLIS"] / 1000.0 for it in firsts]
    assert other.sequence == [] and other.series is None


def test_a_headline_carries_its_time_as_the_screen_shows_it():
    """Schwab's headline time (field 1, epoch ms) labelled once, by the daemon, in Central Time."""
    m = live_ui.marked(live_ui.schwab_message("news." + _NEWS["symbol"], {
        "symbol": _NEWS["symbol"], "content": _NEWS["content"], "schwab_ts": _NEWS["schwab_ts"], "ts_recv": _NEWS["ts_recv"]}))
    assert m["content"] == _NEWS["content"] and m["time_ct"] == ct_label(_NEWS["content"]["1"] / 1000.0)


def test_a_symbol_nobody_asked_for_is_never_sent():
    async def body(bus, ws, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        for m in _MIX:
            _frame(bus, m["service"], m["item"], m["schwab_ts"])
        got, _beats = await _received(ws)
        assert got and {m["key"] for m in got} == {"SPY"}
    asyncio.run(_run(body))


def test_a_new_subscription_gets_each_symbols_current_record_at_once():
    """Schwab sent AAPL's fields before the client asked for it: on subscribing it gets every
    field Schwab has sent, each the last one, without waiting for a new message."""
    aapl = [m for m in _MIX if m["service"] == "LEVELONE_EQUITIES" and m["item"]["key"] == "AAPL"]
    want: dict = {}
    for m in aapl:
        want.update(m["item"])

    async def body(bus, ws, stats):
        for m in aapl:
            _frame(bus, m["service"], m["item"], m["schwab_ts"])
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["AAPL"]}))
        got, _beats = await _received(ws, quiet=0.3)
        assert [m["content"] for m in got] == [want]
        # its last trade's time comes with it, not a beat later
        assert got[0]["trade"]["time_ct"] == ct_label(want["TRADE_TIME_MILLIS"] / 1000.0)
    asyncio.run(_run(body))


def test_each_bar_carries_schwabs_fields_as_the_chart_draws_them():
    """Every real CHART_EQUITY bar: its start (CHART_TIME_MILLIS, s), open, high, low, close and
    volume as Schwab sent them, the change over the bar (close - open, and its percent of the open)
    and its start labelled in Central Time (the series' newest bar), each by its one producer, read
    from the daemon's own message of it (capture._message)."""
    for r in _BARS:
        n = r["native"]
        srv = live_ui.LiveUiServer(MessageBus(), _Feed(), {})
        c = live_ui._Client(None)
        c.chart = n["key"]
        srv.clients.add(c)
        srv.route(*capture._message("CHART_EQUITY", n["key"], n, r["schwab_ts"]))
        m = c.drain()[0]
        chg = n["CLOSE_PRICE"] - n["OPEN_PRICE"]
        assert m["content"] == n
        assert m["bar"] == {"t": n["CHART_TIME_MILLIS"] / 1000.0, "o": n["OPEN_PRICE"], "h": n["HIGH_PRICE"],
                            "l": n["LOW_PRICE"], "c": n["CLOSE_PRICE"], "v": n["VOLUME"], "chg": chg,
                            "chg_pct": chg / n["OPEN_PRICE"] * 100}
        assert m["last_bar"] == {"t": n["CHART_TIME_MILLIS"] / 1000.0, "label": ct_label(n["CHART_TIME_MILLIS"] / 1000.0)}


def test_a_time_schwab_sent_as_no_value_is_not_labelled_and_replaces_no_held_time():
    """AGENTS.md rule 2: -999 is no value. A real book, headline and quote with that time field
    sent as -999 (STAND-IN: the field's value) get no time label, and the -999 trade time does not
    replace the last trade time Schwab sent (none is labelled 1969, "Wed 12/31 05:59 PM CT")."""
    book = next(m for m in _MIX if m["service"] == "NASDAQ_BOOK")
    quote = next(m for m in _MIX if m["service"] == "LEVELONE_EQUITIES" and "TRADE_TIME_MILLIS" in m["item"])
    for service, topic, body, item in (("NASDAQ_BOOK", "book.", "content", {**book["item"], "BOOK_TIME": -999}),
                                       ("NEWS_HEADLINE", "news.", "content", {**_NEWS["content"], "1": -999})):
        m = live_ui.marked(live_ui.schwab_message(topic + item["key"], {"symbol": item["key"], "service": service,
                                                                        body: item, "schwab_ts": 1, "ts_recv": 1.0}))
        assert m["content"] == item and "time_ct" not in m
    srv = live_ui.LiveUiServer(MessageBus(), _Feed(), {})
    key = quote["item"]["key"]
    srv.route("quote." + key, {"symbol": key, "native": quote["item"], "schwab_ts": 1, "ts_recv": 1.0})
    srv.route("quote." + key, {"symbol": key, "native": {"key": key, "TRADE_TIME_MILLIS": -999}, "schwab_ts": 2,
                               "ts_recv": 2.0})
    assert srv.trade_s[key] == quote["item"]["TRADE_TIME_MILLIS"] / 1000.0


def test_each_book_carries_its_levels_and_each_quote_marks_the_fields_that_are_not_numbers():
    """One reader per Schwab value, in the daemon, for the screen (AGENTS.md rules 2 and 3): a
    real book's levels as the ladder shows them (engine.book_levels: each level's price and
    TOTAL_VOLUME, in Schwab's order for a real book), a level whose price is -999 dropped (it has no
    place), one whose size is -999 kept with its size absent, the book otherwise as sent; a real quote's field sent as -999, or a negative size, marked absent
    (live_market_plane.read_stream_field), its other fields not; a client behind gets the newest
    mark of each field. STAND-IN (named): the -999 and the negative size."""
    books = [m for m in _MIX if live_ui.DELIVERY[m["service"]] == live_ui.WHOLE]
    books += [{"service": "NASDAQ_BOOK", "item": r[2]} for r in json.loads((FX / "real_tsla_book_rows.json").read_text(
        encoding="utf-8"))["rows"][:2]]
    for b in books:
        it = b["item"]
        m = live_ui.marked(live_ui.schwab_message("book." + it["key"], {"symbol": it["key"], "service": b["service"],
                                                                        "content": it}))
        assert m["content"] == it
        assert m["levels"] == {"bids": [[lv["BID_PRICE"], lv["TOTAL_VOLUME"]] for lv in it["BIDS"]],
                               "asks": [[lv["ASK_PRICE"], lv["TOTAL_VOLUME"]] for lv in it["ASKS"]]}
    it = books[0]["item"]
    bad = {**it, "BIDS": [{**it["BIDS"][0], "BID_PRICE": -999}, *it["BIDS"][1:]]}
    m = live_ui.marked(live_ui.schwab_message("book." + it["key"], {"symbol": it["key"], "service": books[0]["service"],
                                                                    "content": bad}))
    assert m["content"] == bad and m["levels"]["bids"] == [[lv["BID_PRICE"], lv["TOTAL_VOLUME"]] for lv in it["BIDS"][1:]]
    # a level with Schwab's price and a size sent as -999: shown at its price, its size absent ('-')
    no_size = {**it, "BIDS": [{**it["BIDS"][0], "TOTAL_VOLUME": -999}, *it["BIDS"][1:]]}
    m = live_ui.marked(live_ui.schwab_message("book." + it["key"], {"symbol": it["key"], "service": books[0]["service"],
                                                                    "content": no_size}))
    assert m["levels"]["bids"][0] == [it["BIDS"][0]["BID_PRICE"], None]
    q = next(m["item"] for m in _MIX if m["service"] == "LEVELONE_EQUITIES" and "BID_SIZE" in m["item"]
             and "LAST_PRICE" in m["item"])
    sent = {**q, "LAST_PRICE": -999, "BID_SIZE": -5}
    m = live_ui.marked(live_ui.schwab_message("quote." + q["key"], {"symbol": q["key"], "native": sent}))
    assert m["content"] == sent and {"LAST_PRICE", "BID_SIZE"} <= set(m["absent"])
    assert not {k for k in q if isinstance(q[k], (int, float)) and k not in ("LAST_PRICE", "BID_SIZE")} & set(m["absent"])
    c = live_ui._Client(None)
    c.take(m)
    c.take(live_ui.marked(live_ui.schwab_message("quote." + q["key"], {"symbol": q["key"],
                                                                       "native": {"key": q["key"], "LAST_PRICE": 1.5}})))
    held = c.drain()[0]
    assert held["content"]["LAST_PRICE"] == 1.5 and "LAST_PRICE" not in held["absent"] and "BID_SIZE" in held["absent"]


def test_a_new_trade_reaches_the_screen_with_its_own_time_and_age():
    """AGENTS.md rule 5, every value with its time: a real quote with a new trade carries that
    trade's time and age as the daemon labels them, so the screen never shows the new price
    with the previous trade's time until the next beat."""
    q = next(m for m in _MIX if m["service"] == "LEVELONE_EQUITIES" and "TRADE_TIME_MILLIS" in m["item"])
    at = q["item"]["TRADE_TIME_MILLIS"] / 1000.0 + 2.0
    srv = live_ui.LiveUiServer(MessageBus(), _Feed(), {}, clock=lambda: at)
    c = live_ui._Client(None)
    c.symbols = frozenset({q["item"]["key"]})
    srv.clients.add(c)
    srv.route("quote." + q["item"]["key"], {"symbol": q["item"]["key"], "native": q["item"], "schwab_ts": 1, "ts_recv": 1.0})
    sent = c.drain()[0]
    assert sent["content"] == q["item"]
    assert sent["trade"] == {"time_ct": ct_label(q["item"]["TRADE_TIME_MILLIS"] / 1000.0), "age": age_label(2.0)}


def test_a_contract_opened_after_its_messages_gets_every_field_schwab_streamed():
    """Operator 2026-10-14 (the bank's running balance): a screen that asks for a contract Schwab
    has been streaming gets, at once, every LEVELONE_OPTIONS field Schwab sent for it, each the
    last one, as sent, not only the next change."""
    key = max({m["item"]["key"] for m in _MIX if m["service"] == "LEVELONE_OPTIONS"},
              key=lambda k: sum(1 for m in _MIX if m["item"]["key"] == k))
    sent = [m for m in _MIX if m["item"]["key"] == key]
    want: dict = {}
    for m in sent:
        want.update(m["item"])

    async def body(bus, ws, stats):
        for m in sent:
            _frame(bus, m["service"], m["item"], m["schwab_ts"])
        await ws.send(json.dumps({"op": "subscribe", "symbols": [key]}))
        got, _beats = await _received(ws, quiet=0.3)
        assert len(sent) > 1 and [(m["service"], m["content"]) for m in got] == [("LEVELONE_OPTIONS", want)]
    asyncio.run(_run(body))


def test_the_page_is_told_what_each_symbol_it_names_is():
    """ONE-14 (2026-09-28 audit): the page stripped "$" in eight places to match a row to what it
    asked for. The daemon answers each subscribe with each named symbol's key (what its messages
    carry) and display name, from instrument_identity, for an index typed bare or with "$", an ETF
    in lower case and a single name alike."""
    async def body(bus, ws, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPX", "$VIX", "spy", "MU"]}))
        frame = await _next(ws, "symbols")
        assert frame["symbols"] == [
            {"requested": "SPX", "key": "$SPX", "display": "SPX"},
            {"requested": "$VIX", "key": "$VIX", "display": "VIX"},
            {"requested": "spy", "key": "SPY", "display": "SPY"},
            {"requested": "MU", "key": "MU", "display": "MU"}]
    asyncio.run(_run(body))


#: Wednesday 2026-09-30, 11:00 ET (RTH) and 22:00 ET (Closed), as epoch seconds
_RTH, _CLOSED = 1790780400.0, 1790820000.0


def _clock_from(start: float):
    """A clock running from `start` (the session the test is in); time still passes. The daemon's
    server and its status are given it (serve_live_ui's `clock`); nothing is patched."""
    offset = start - time.time()
    return lambda: time.time() + offset


async def _verdict(ws, key: str, until, timeout: float = 3.0) -> dict:
    """`key`'s LEVELONE_EQUITIES verdict in the first beat for which `until(verdict)` holds."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if frame["type"] == "feed" and key in frame["state"]:
            v = frame["state"][key]["LEVELONE_EQUITIES"]
            if until(v):
                return v
    raise AssertionError(f"no beat with the verdict sought for {key}")


@pytest.mark.parametrize("start, outage", [(_RTH, "Schwab LEVELONE_EQUITIES feed down during RTH"), (_CLOSED, None)],
                         ids=["rth", "closed"])
def test_a_closed_schwab_socket_reads_not_live_within_one_beat(start, outage):
    """Nothing from Schwab; only the daemon's status knows (docs/DATA_FLOW.md §2 D5): SPY live on a
    real quote Schwab sent, then Schwab's socket closes: the next beat says not live, with the
    outage while the market is open and none while Closed (the values as of the close stand)."""
    clock = _clock_from(start)
    quote = next(m for m in _MIX if m["service"] == "LEVELONE_EQUITIES" and m["item"]["key"] == "SPY")
    feed = _Switch(clock)

    async def body(bus, ws, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        _frame(bus, "LEVELONE_EQUITIES", quote["item"], quote["schwab_ts"])
        assert await _verdict(ws, "SPY", lambda v: v["live"]) == {"live": True, "outage": None}
        feed.open = False
        assert await _verdict(ws, "SPY", lambda v: not v["live"], timeout=2.5) == {"live": False, "outage": outage}
    asyncio.run(_run(body, feed=feed, clock=clock))


def test_a_symbol_the_daemon_does_not_hold_is_not_live():
    """A quote for a symbol the daemon does not hold on Schwab is never live."""
    clock = _clock_from(_CLOSED)
    quote = next(m for m in _MIX if m["service"] == "LEVELONE_EQUITIES" and m["item"]["key"] != "SPY")

    async def body(bus, ws, stats):
        key = quote["item"]["key"]
        await ws.send(json.dumps({"op": "subscribe", "symbols": [key]}))
        _frame(bus, "LEVELONE_EQUITIES", quote["item"], quote["schwab_ts"])
        assert await _verdict(ws, key, lambda v: True) == {"live": False, "outage": None}
    asyncio.run(_run(body, feed=_Switch(clock, held=("SPY",)), clock=clock))


def test_each_beat_is_the_daemons_whole_status():
    async def body(bus, ws, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        frame = await _next(ws, "feed")
        assert set(frame) == {"type", "feed", "state", "trades"} and frame["feed"]["held"] == {"LEVELONE_EQUITIES": ["SPY"]}
        assert set(frame["state"]["SPY"]) == set(live_ui.EQUITY_SERVICES)
    asyncio.run(_run(body))


def test_shutdown_is_not_held_up_by_a_connected_client():
    async def body(bus, ws, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        await asyncio.wait_for(ws.recv(), 2)
    t0 = time.monotonic()
    asyncio.run(_run(body))
    assert time.monotonic() - t0 < 5


def test_the_daemons_socket_and_the_console_listen_on_this_computer_only():
    """Operator 2026-10-14: "Bind both 8800 and 8000 to 127.0.0.1. I only use this computer."
    The daemon's socket, served as the daemon serves it (its own host), listens on 127.0.0.1;
    the console is started by the launcher on 127.0.0.1; neither listens on every address."""
    import launch

    async def go():
        stop, stats = asyncio.Event(), {}
        server = asyncio.create_task(live_ui.serve_live_ui(MessageBus(), stop, heartbeat_fn=_Feed(), port=0, stats=stats))
        end = time.monotonic() + 5
        while not stats.get("listening") and time.monotonic() < end:
            await asyncio.sleep(0.01)
        stop.set()
        await asyncio.wait_for(server, 5)
        return stats["listening"]
    assert asyncio.run(go()).startswith("ws://127.0.0.1:")
    host = launch.CONSOLE[launch.CONSOLE.index("--host") + 1]
    assert host == "127.0.0.1"
