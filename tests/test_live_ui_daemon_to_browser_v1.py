"""Prices straight from the capture daemon to the browser (live_ui.py), end to end.

The REAL daemon-side server (serve_live_ui, its plane fed from a real stream_spine.MessageBus by
the daemon's follow_market), served at /ws by the program's real web server (server.app on
uvicorn with capture.PAGES), and a REAL WebSocket client standing in for the browser, over a
real local socket. No console startup work, no database. Proves:

  * a subscribed symbol gets its current row at once, then a row for every Schwab change;
  * the row is the one producer's row (live_price_rows.price_row): spot, feed verdict,
    Schwab trade age, and no bar (charts show Schwab's completed bars only);
  * a symbol nobody subscribed to is never sent;
  * the feed verdict rides every beat: a closed Schwab socket reads feed_live False within one
    beat, with no message needed from Schwab; the last values stand, and in session the row
    names the outage (docs/DATA_FLOW.md §2 D5);
  * the watchlist rides every beat as the daemon's status; a failed status is a beat with none;
  * a slow browser gets the newest row per symbol, never a backlog of stale ones;
  * shutdown is not held up by a connected browser.

And the selected ticker's panels (server.PAGE_PANELS), the expiry dropdown's list first: the levels
producer (server._publish_levels) prices real chains the daemon captured on 2026-10-07
(tests/real_chains.py: CRWD's 2026-10-16 expiry, MRVL's full chain of 20 expiries) on a thread of
its own, as the pricing thread runs it, and the expected lists are worked out from the captured
chains here (each expirationDate's day, Schwab's daysToExpiration as sent). Proves:

  * a page subscribing on a ticker gets that ticker's list at once, with no GET (the route is
    gone);
  * a ticker with no chain yet gets an unknown list (None) with the levels' own reason, never an
    empty list standing for unknown;
  * a new chain pushes the new list only to the pages on that ticker; two pages on different
    tickers each get only their own;
  * switching ticker sends the new ticker's list at once and stops the old ticker's;
  * a page that drops and returns gets the list again on its subscribe; a page with no ticker
    gets none.

Then the levels' panels a page shows, each with the parameters its subscribe names (the Vanna and
Charm tabs, push.strike_bars, with their window), the expected rows
the ones the levels producer published, worked into the window here:

  * a page on the tab gets the panel at once, in the window it asks (a window it cannot draw is
    unavailable with its words); before the ticker's levels, unavailable with the reason;
  * new levels reach only the pages showing that panel on that ticker; a switch sends the new
    ticker's and none of the old; a page that drops and returns gets its panels again;
  * a producer waiting on the levels' lock (induced) does not stall the beat.
"""

from __future__ import annotations

import asyncio
import base64
import json
import socket
import threading
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psutil
import pytest
from websockets.asyncio.client import connect

import live_market_plane as lmp
import live_price_rows
import server
import time_et
from app.market_data.schwab.streaming import capture, live_ui
from instrument_identity import ticker_storage_key
from numeric_contract import compact_text, count_text, dollars_text, strike_text
from push import chain as push_chain
from push import verdict as push_verdict
from state import level_store
from stream_spine import HealthRegistry, MessageBus, quote_msg
from tests.feed_live_helper import clock_from, forget_news, news_on_the_bus, publish_capture
from tests.real_chains import CRWD, MRVL
from tests.test_live_push_channel_v1 import listener, serve_page_socket


@pytest.fixture(autouse=True)
def _fresh_plane():
    """Each test starts from an empty quote plane, then the plane is put back."""
    quotes, fields = lmp._by_ticker, lmp._fields_by_ticker
    lmp._by_ticker = {}
    lmp._fields_by_ticker = {}
    yield
    lmp._by_ticker = quotes
    lmp._fields_by_ticker = fields


def _trade(sym: str, last: float, ts: float, **extra) -> dict:
    native = {
        "key": sym,
        "BID_PRICE": last - 0.01,
        "ASK_PRICE": last + 0.01,
        "LAST_PRICE": last,
        "TRADE_TIME_MILLIS": int(ts * 1000),
        "QUOTE_TIME_MILLIS": int(ts * 1000),
        **extra,
    }
    return quote_msg(
        symbol=sym,
        bid=last - 0.01,
        ask=last + 0.01,
        last=last,
        src="schwab_l1",
        ts_recv=ts,
        native=native,
    )


class _Feed:
    def __init__(self, held=("SPY", "AAPL"), clock=time_et.now):
        self.open = True
        self.held = list(held)
        self.clock = clock

    def __call__(self, now: float) -> dict:
        return {
            "ts": now,
            "schwab_socket_open": self.open,
            "held": {"LEVELONE_EQUITIES": self.held},
            "health": {},
            "apply_failures": 0,
            "tick_failures": 0,
        }


async def _run(body, feed=None):
    sock, url = listener()
    bus = MessageBus()
    stop = asyncio.Event()
    stats: dict = {}
    feed = feed if feed is not None else _Feed()
    server = asyncio.create_task(
        serve_page_socket(stop, sock, {"heartbeat_fn": feed, "stats": stats, "clock": feed.clock})
    )
    follower = asyncio.create_task(capture.Daemon(bus, HealthRegistry(), []).follow_market(stop))
    end = time_et.elapsed() + 5
    while "clients" not in stats and time_et.elapsed() < end:
        await asyncio.sleep(0.01)
    assert "clients" in stats  # serving
    try:
        async with connect(f"{url}/ws") as ws:
            await body(bus, ws, feed, stats)
    finally:
        stop.set()
        await asyncio.wait_for(asyncio.gather(server, follower, return_exceptions=True), 5)


async def _next_row(ws, sym, pred=lambda _r: True, timeout=3.0):
    end = time_et.elapsed() + timeout
    while time_et.elapsed() < end:
        msg = json.loads(await asyncio.wait_for(ws.recv(), max(0.01, end - time_et.elapsed())))
        if msg["type"] == "symbols":  # the one frame with no rows (live_ui's protocol)
            continue
        for r in msg["rows"]:
            if r["ticker"] == sym and pred(r):
                return msg, r
    raise AssertionError(f"no matching {sym} row within {timeout}s")


def test_a_schwab_trade_reaches_the_browser_as_a_finished_live_row():
    """In regular hours: the server's clock runs from _RTH."""
    clock = clock_from(_RTH)

    async def body(bus, ws, _feed, _stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["spy"]}))
        now = clock()
        bus.publish("quote.SPY", _trade("SPY", 583.41, now))
        msg, row = await _next_row(ws, "SPY", lambda r: r["spot"] == 583.41)
        assert row["spot_disp"] == "583.41" and row["trade_time_ct"] is not None
        assert row["feed_live"] is True and row["spot_source"] == "streaming_plane"
        assert row["bid"] == pytest.approx(583.40) and row["ask"] == pytest.approx(583.42)
        # the header's bid × ask as the screen shows them, two decimals
        assert (row["bid_text"], row["ask_text"]) == ("583.40", "583.42")
        # epoch SECONDS: Schwab's TRADE_TIME_MILLIS as sent, over 1000
        assert row["trade_ts"] == int(now * 1000) / 1000
        assert row["trade_age_text"] in ("0s", "1s")
        assert "forming_1m" not in row
        # the next trade moves it, pushed on its own (not on the beat)
        t0 = time_et.elapsed()
        bus.publish("quote.SPY", _trade("SPY", 583.90, clock()))
        msg, row = await _next_row(ws, "SPY", lambda r: r["spot"] == 583.90)
        assert msg["type"] == "quotes"
        assert time_et.elapsed() - t0 < 0.15, "a change must go out immediately, not on the beat"

    asyncio.run(_run(body, feed=_Feed(clock=clock)))


def test_an_unsubscribed_symbol_is_never_sent():
    async def body(bus, ws, _feed, _stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        bus.publish("quote.AAPL", _trade("AAPL", 230.0, time_et.now()))
        bus.publish("quote.SPY", _trade("SPY", 583.0, time_et.now()))
        frames = []
        end = time_et.elapsed() + 1.5 * live_ui.HEARTBEAT_SEC  # the rows, and a beat's rows
        while (left := end - time_et.elapsed()) > 0:
            try:
                frames.append(json.loads(await asyncio.wait_for(ws.recv(), left)))
            except TimeoutError:
                break
        assert any(m["type"] == "feed" for m in frames), "a beat came within the window"
        assert all(
            r["ticker"] == "SPY" for m in frames if m["type"] != "symbols" for r in m["rows"]
        ), frames

    asyncio.run(_run(body))


def test_resubscribing_sends_the_new_symbols_current_rows_at_once():
    """The subscribe's own answer carries the new symbol's row, not a later beat.

    The trade is first held by the program (the daemon's follower applies the bus message on its
    own task), so the row the subscribe answers with is the one that trade made. A "quotes" frame
    is sent only by the pump answering a subscribe or a push, never by a beat ("feed"), and no
    AAPL push follows, so AAPL in a quotes frame is the subscribe's answer: "at once" by cause,
    not by a wall-clock bound a loaded machine can miss.
    """

    async def body(bus, ws, _feed, _stats):
        traded = time_et.now()
        bus.publish("quote.AAPL", _trade("AAPL", 230.5, traded))
        for _ in range(500):  # up to 5 s for the follower to hold it
            if live_price_rows.price_row("AAPL", traded)["spot"] == 230.5:
                break
            await asyncio.sleep(0.01)
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY", "AAPL"]}))
        rows: list = []
        while not rows:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if msg["type"] == "quotes":
                rows = [r for r in msg["rows"] if r["ticker"] == "AAPL"]
        assert [r["spot"] for r in rows] == [230.5]

    asyncio.run(_run(body))


def test_a_subscribe_is_answered_with_what_each_symbol_is_before_its_rows():
    """A subscribe is answered with what each symbol is, before its rows.

    ONE-14 (2026-09-28 audit): the page stripped "$" in eight places to match a row to what it
    asked for, and kept its own list of index roots. The daemon answers each subscribe with
    each asked-for symbol's key (what its rows carry) and display name, from instrument_identity,
    for an index typed bare or with "$", an ETF and a single name alike.
    """

    async def body(_bus, ws, _feed, _stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPX", "$VIX", "spy", "MU"]}))
        # a beat may come before the subscribe is read, carrying no row: no row before the answer
        while (first := json.loads(await asyncio.wait_for(ws.recv(), 2)))["type"] != "symbols":
            assert first["type"] == "feed" and first["rows"] == [], first
        assert first == {
            "type": "symbols",
            "symbols": [
                {"requested": "SPX", "key": "$SPX", "display": "SPX"},
                {"requested": "$VIX", "key": "$VIX", "display": "VIX"},
                {"requested": "spy", "key": "SPY", "display": "SPY"},
                {"requested": "MU", "key": "MU", "display": "MU"},
            ],
        }

    asyncio.run(_run(body))


def test_no_row_reaches_the_page_before_the_page_is_told_what_its_symbol_is():
    """A beat between a subscribe and its answer carried rows the page could not place.

    Seen in CI 2026-11-18 (tests/test_data_path_startup_v1.py): the first frame after a subscribe
    was a beat with SPY's row, ahead of the symbols answer. The page's sender was busy: here it is
    held producing a panel (every worker of the loop's pool waiting, so the panel cannot start)
    when the page asks for a new symbol; the next beat must not carry that symbol's row before the
    page is told what it is.
    """

    async def body(_bus, ws, _feed, _stats):
        gate = threading.Event()
        loop = asyncio.get_running_loop()
        held = [loop.run_in_executor(None, gate.wait, 30) for _ in range(64)]
        known: set[str] = set()
        late: list[tuple[str, str]] = []
        try:
            asked = {"op": "subscribe", "ticker": "SPY", "panels": {"tape": {}}}
            await ws.send(json.dumps({**asked, "symbols": ["SPY"]}))
            await ws.send(json.dumps({**asked, "symbols": ["SPY", "ZZNEW"]}))
            end = loop.time() + 2.5 * live_ui.HEARTBEAT_SEC  # two beats at least
            while (left := end - loop.time()) > 0:
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), left))
                except TimeoutError:
                    break
                if msg["type"] == "symbols":
                    known.update(s["key"] for s in msg["symbols"])
                if msg["type"] in ("feed", "quotes"):  # the frames that carry rows
                    late.extend(
                        (msg["type"], r["ticker"]) for r in msg["rows"] if r["ticker"] not in known
                    )
        finally:
            gate.set()
            await asyncio.gather(*held)
        assert "ZZNEW" in known, known
        assert late == [], late[:5]

    asyncio.run(_run(body))


def test_an_index_typed_bare_is_served_under_its_storage_key():
    """The operator types "SPX"; Schwab keys "$SPX".

    The subscription goes through ticker_storage_key, so the typed form gets the index's rows. In
    regular hours (_RTH).
    """
    clock = clock_from(_RTH)

    async def body(bus, ws, _feed, _stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPX"]}))
        bus.publish("quote.$SPX", _trade("$SPX", 6512.25, clock()))
        _, row = await _next_row(ws, "$SPX", lambda r: r["spot"] == 6512.25)
        assert row["feed_live"] is True

    asyncio.run(_run(body, feed=_Feed(held=("$SPX",), clock=clock)))


#: Wednesday 2026-09-30, 11:00 ET (RTH) and 22:00 ET (Closed), as epoch seconds
_RTH, _CLOSED = 1790780400.0, 1790820000.0


@pytest.mark.parametrize("start", [_RTH, _CLOSED], ids=["rth", "closed"])
def test_a_closed_schwab_socket_reads_feed_down_within_one_beat(start):
    """Nothing from Schwab; only the beat knows (docs/DATA_FLOW.md §2 D5).

    The last price and bid stand, and the row reads OFFLINE and names the outage, the market open
    or closed. Before the socket closes the row is LIVE in regular hours and NOT LIVE at 22:00,
    the market closed. The server's clock runs from `start` so the session is that hour, and time
    still passes.
    """
    clock = clock_from(start)

    async def body(bus, ws, feed, _stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        bus.publish("quote.SPY", _trade("SPY", 583.41, clock()))
        _, row = await _next_row(ws, "SPY", lambda r: r["spot"] == 583.41)
        assert row["feed_label"] == ("LIVE" if start == _RTH else "NOT LIVE")
        feed.open = False
        msg, row = await _next_row(
            ws, "SPY", lambda r: r["feed_label"] == "OFFLINE", timeout=1.5 * live_ui.HEARTBEAT_SEC
        )  # the next beat
        assert msg["type"] == "feed" and msg["feed"]["schwab_socket_open"] is False
        assert row["spot"] == 583.41 and row["bid"] == pytest.approx(583.40)
        assert row["feed_live"] is False and row["outage"].startswith(
            "Schwab LEVELONE_EQUITIES feed down during "
        )

    asyncio.run(_run(body, feed=_Feed(clock=clock)))


def test_a_symbol_the_daemon_does_not_hold_reads_feed_not_live():
    clock = clock_from(_CLOSED)

    async def body(bus, ws, _feed, _stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["TSLA"]}))
        bus.publish("quote.TSLA", _trade("TSLA", 400.0, clock()))
        msg, row = await _next_row(ws, "TSLA", lambda r: r["spot"] == 400.0)
        assert row["feed_live"] is False

    asyncio.run(_run(body, feed=_Feed(clock=clock)))


def test_a_missing_heartbeat_keeps_the_last_watchlist():
    """Carry the daemon's list on a beat, and no status on a beat whose status failed.

    The daemon holds SPY and TSLA: the page's socket carries them on a beat, as the daemon's own
    status. Then the daemon's status fails (induced: the status raises), and the next beat carries
    no status at all, never a list of its own: the page keeps the last list and says the daemon is
    not reporting (tests/e2e/console-watchlist-socket.spec.js).
    """
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY", "TSLA"])
    failing = False

    def status(now: float) -> dict:
        if failing:
            raise RuntimeError("induced: the daemon's status failed")
        return daemon.status(now)

    async def beat(ws) -> dict:
        while (msg := json.loads(await asyncio.wait_for(ws.recv(), 3)))["type"] != "feed":
            pass
        return msg

    async def go():
        nonlocal failing
        sock, url = listener()
        stop, stats = asyncio.Event(), {}
        served = asyncio.create_task(
            serve_page_socket(stop, sock, {"heartbeat_fn": status, "stats": stats})
        )
        try:
            while "clients" not in stats:
                await asyncio.sleep(0.01)
            async with connect(f"{url}/ws") as ws:
                live = await beat(ws)
                failing = True
                down = await beat(ws)
                while down["feed"] is not None:  # a beat already made before the failure
                    down = await beat(ws)
        finally:
            stop.set()
            await asyncio.wait_for(served, 5)
        return live, down

    try:
        live, down = asyncio.run(asyncio.wait_for(go(), 30))
    finally:
        with lmp._lock:
            lmp._feed["status"] = None
    assert live["feed"]["watchlist"] == ["SPY", "TSLA"] and live["feed"]["ts"] is not None
    # the header's time and day: the beat's own instant, in Central Time
    at = datetime.fromtimestamp(live["feed"]["ts"], ZoneInfo("America/Chicago"))
    assert live["feed"]["clock_ct"] == f"{at:%H:%M:%S} CT"
    assert live["feed"]["day_ct"] == f"{at:%a, %b %d}"
    assert down["feed"] is None


def test_every_page_is_sent_the_news_line_on_its_first_beat_then_only_when_it_changes():
    """The daemon's follower and the page's socket, a real WebSocket client, no ticker selected.

    Real data: Schwab's five headlines of the 2026-11-20 open
    (tests/fixtures/real_schwab_news_headlines_2026_11_20.json). The page's first beat carries
    the header's news line, empty; the five reach it on the next beat; the beats after carry no
    line until it changes, and a message given again changes nothing (INDUCED: the second
    arrival); when the Central day turns the line is sent again with yesterday's times written
    whole (INDUCED: the server's clock is the test's, moved past midnight).
    """
    sent = json.loads(
        (
            Path(__file__).resolve().parent
            / "fixtures"
            / "real_schwab_news_headlines_2026_11_20.json"
        ).read_text(encoding="utf-8")
    )["messages"][:5]
    central = ZoneInfo("America/Chicago")
    next_day = datetime.fromtimestamp(sent[0]["ts_recv"], central).date().toordinal() + 1
    midnight = datetime.fromordinal(next_day).replace(tzinfo=central).timestamp()
    at = [midnight - 10.0]

    def status(now: float) -> dict:
        return {"ts": now, "schwab_socket_open": True, "held": {}, "health": {}} | {
            "apply_failures": 0,
            "tick_failures": 0,
        }

    async def beat(ws) -> dict:
        while (msg := json.loads(await asyncio.wait_for(ws.recv(), 5)))["type"] != "feed":
            pass
        return msg

    async def go() -> list[dict]:
        sock, url = listener()
        bus, stop, stats = MessageBus(), asyncio.Event(), {}
        prices = {"heartbeat_fn": status, "stats": stats, "clock": lambda: at[0]}
        served = asyncio.create_task(serve_page_socket(stop, sock, prices))
        follower = asyncio.create_task(
            capture.Daemon(bus, HealthRegistry(), []).follow_market(stop)
        )
        try:
            while "clients" not in stats:
                await asyncio.sleep(0.01)
            async with connect(f"{url}/ws") as ws:
                await ws.send(json.dumps({"op": "subscribe", "symbols": []}))
                got = [await beat(ws)]
                news_on_the_bus(bus, sent)
                news_on_the_bus(bus, sent[:1])
                got += [await beat(ws), await beat(ws), await beat(ws)]
                at[0] = midnight + 1.0
                got += [await beat(ws), await beat(ws)]
        finally:
            stop.set()
            await asyncio.wait_for(asyncio.gather(served, follower, return_exceptions=True), 5)
        return got

    forget_news()
    try:
        first, today, quiet, still_quiet, tomorrow, after = asyncio.run(asyncio.wait_for(go(), 30))
    finally:
        forget_news()
    assert first["news"] == {
        "items": [],
        "left_out": (
            "English only, by Schwab's language field: 0 messages in other languages and 0 "
            "unreadable left out since the program started"
        ),
    }
    assert [i["time_ct"] for i in today["news"]["items"]] == ["08:30 AM CT"] * 5
    assert sorted(i["headline"] for i in today["news"]["items"]) == sorted(
        m["item"]["4"] for m in sent
    )
    assert "news" not in quiet and "news" not in still_quiet, "the unchanged line is not sent again"
    assert [i["time_ct"] for i in tomorrow["news"]["items"]] == ["Fri 11/20 08:30 AM CT"] * 5
    assert [i["headline"] for i in tomorrow["news"]["items"]] == [
        i["headline"] for i in today["news"]["items"]
    ]
    assert "news" not in after


def test_a_burst_is_conflated_to_the_newest_row_per_symbol():
    """A browser that is behind gets the newest value of each symbol, never a stale backlog.

    Latest-value-per-symbol per client.
    """

    async def body(bus, ws, _feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY", "AAPL"]}))
        await _next_row(ws, "SPY")  # the (empty) snapshot
        for i in range(500):
            now = time_et.now()
            bus.publish("quote.SPY", _trade("SPY", 500 + i / 100, now))
            bus.publish("quote.AAPL", _trade("AAPL", 200 + i / 100, now))
        _, spy = await _next_row(ws, "SPY", lambda r: r["spot"] == pytest.approx(504.99))
        _, aapl = await _next_row(ws, "AAPL", lambda r: r["spot"] == pytest.approx(204.99))
        # 1000 messages, far fewer frames: the browser was never handed the backlog
        assert stats["rows_sent"] < 200, stats

    asyncio.run(_run(body))


def test_shutdown_is_not_held_up_by_a_connected_browser():
    async def body(_bus, ws, _feed, _stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        await _next_row(ws, "SPY")

    t0 = time_et.elapsed()
    asyncio.run(_run(body))
    assert time_et.elapsed() - t0 < 5


def test_a_page_before_the_first_schwab_quote_reads_no_price_until_one_comes():
    """A page that subscribes before the daemon holds any quote for its symbol is answered at once.

    It gets the row as it is: no price ("-" on the page), never a filler; Schwab's first quote
    then reaches it.
    """

    async def body(bus, ws, _feed, _stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        assert json.loads(await asyncio.wait_for(ws.recv(), 2))["type"] == "symbols"
        msg, row = await _next_row(ws, "SPY")
        assert msg["type"] == "quotes"
        assert (row["spot"], row["spot_disp"], row["bid"], row["ask"]) == (None, None, None, None)
        assert (row["bid_text"], row["ask_text"]) == (None, None)  # nothing sent: no text
        bus.publish("quote.SPY", _trade("SPY", 583.41, time_et.now()))
        _, row = await _next_row(ws, "SPY", lambda r: r["spot"] == 583.41)
        assert row["spot_disp"] == "583.41"

    asyncio.run(_run(body))


def test_a_page_that_goes_away_mid_send_ends_only_its_own_connection():
    """One page's connection is cut (no close) while rows are being pushed to it.

    Its handler ends, and the other page keeps its rows and its beats.
    """

    async def body(bus, ws, _feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        await _next_row(ws, "SPY")
        url = f"ws://127.0.0.1:{ws.remote_address[1]}/ws"
        gone = await connect(url)
        await gone.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        await asyncio.wait_for(gone.recv(), 2)
        assert stats["clients"] == 2
        for i in range(200):
            bus.publish("quote.SPY", _trade("SPY", 500 + i / 100, time_et.now()))
            if i == 100:
                gone.transport.abort()  # the page's side of the connection cut mid-burst
            await asyncio.sleep(0)
        _, row = await _next_row(ws, "SPY", lambda r: r["spot"] == pytest.approx(501.99))
        end = time_et.elapsed() + 5
        while stats["clients"] != 1 and time_et.elapsed() < end:
            await asyncio.sleep(0.01)
        assert stats["clients"] == 1
        msg, _ = await _next_row(ws, "SPY", timeout=2 * live_ui.HEARTBEAT_SEC)
        while msg["type"] != "feed":  # the beat goes on
            msg, _ = await _next_row(ws, "SPY", timeout=2 * live_ui.HEARTBEAT_SEC)

    asyncio.run(_run(body))


#: what the frozen page subscribed to: its first rows alone outgrow its 1 KB receive window
_WATCHED = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL"]


def _page_that_never_reads(port: int) -> socket.socket:
    """Open a page's connection that subscribes and then never reads (a frozen tab).

    Its receive window is 1 KB.
    """
    page = socket.socket()
    page.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)  # before connecting: the window
    page.connect(("127.0.0.1", port))
    key = base64.b64encode(b"never-read page!").decode()  # 16 bytes, as RFC 6455 4.1 asks
    page.sendall(
        f"GET /ws HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode()
    )
    text = json.dumps({"op": "subscribe", "symbols": _WATCHED}, separators=(",", ":")).encode()
    assert len(text) < 126  # its length in the frame's second byte
    mask = b"\x01\x02\x03\x04"
    page.sendall(  # one masked text frame, as a browser sends it (RFC 6455 section 5.2)
        bytes([0x81, 0x80 | len(text)]) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(text))
    )
    return page


def _held_by_this_program(server_port: int, page: socket.socket) -> bool:
    """Whether the program still holds the server side of `page`'s connection open.

    Once it lets go, the system closes it (FIN_WAIT_1, its unsent bytes still offered to the page,
    which reads them and the end when it thaws, then reconnects), never ESTABLISHED.
    """
    page_port = page.getsockname()[1]
    return any(
        c.laddr.port == server_port
        and c.raddr
        and c.raddr.port == page_port
        and c.status == psutil.CONN_ESTABLISHED
        for c in psutil.net_connections("tcp")
    )


def test_a_page_that_stops_reading_while_little_is_sent_is_dropped_at_the_keepalive_ping(caplog):
    """A page that stops reading while its buffers are not full is dropped at the keepalive ping.

    It is found by the keepalive ping it does not answer, and its connection is aborted
    (live_ui.PageSocket): uvicorn's own close waits for bytes the page never takes, holding the
    connection for as long as the page stays frozen. The program then holds no connection to it,
    its handler has ended, and the stop is not held. Induced test conditions: the program's socket
    buffers no bytes in the kernel (SO_SNDBUF 0) and each beat carries a 15 KB pad, so the page's
    window fills at once and a write it does not take stays pending in the program, short of the
    buffer that pauses writing (64 KiB); and the keepalive ping every 0.5 s, answered within
    0.5 s (production: uvicorn's 20 s and 20 s).
    """
    feed = _Feed()

    def padded(now: float) -> dict:
        return {**feed(now), "pad": "x" * 15_000}

    async def go():
        stop, stats = asyncio.Event(), {}
        sock, _ = listener()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 0)
        port = sock.getsockname()[1]
        served = asyncio.create_task(
            serve_page_socket(
                stop,
                sock,
                {"heartbeat_fn": padded, "stats": stats, "clock": feed.clock},
                ws_ping_interval=0.5,
                ws_ping_timeout=0.5,
            )
        )
        page = _page_that_never_reads(port)
        try:
            end = time_et.elapsed() + 5
            while stats.get("clients") != 1 and time_et.elapsed() < end:
                await asyncio.sleep(0.01)
            assert stats["clients"] == 1 and _held_by_this_program(port, page)
            end = time_et.elapsed() + 5  # a ping, its timeout and a beat's margin
            # the handler ends on the loop's next turns after the connection (connection_lost)
            while (stats["clients"] or _held_by_this_program(port, page)) and (
                time_et.elapsed() < end
            ):
                await asyncio.sleep(0.05)
            assert not _held_by_this_program(port, page), "the frozen page's connection is held"
            assert stats["clients"] == 0
            t0 = time_et.elapsed()
            stop.set()
            await asyncio.wait_for(served, 5)
            return time_et.elapsed() - t0
        finally:
            page.close()

    took = asyncio.run(asyncio.wait_for(go(), 30))
    assert took < 2, f"the stop took {took:.1f} s"
    dropped = [r.getMessage() for r in caplog.records if "stopped reading" in r.getMessage()]
    assert dropped == [
        "live ui: a page stopped reading (the keepalive ping unanswered); dropping it"
    ], dropped


# -- the selected ticker's panels: the expiry list -------------------------------------------

A, B = ticker_storage_key(CRWD.ticker), ticker_storage_key(MRVL.ticker)


def _expected(chain) -> tuple[list[str], dict]:
    """Return the chain's listed expiries and each one's daysToExpiration, as Schwab sent them."""
    dte = {str(c["expirationDate"])[:10]: c["daysToExpiration"] for c in chain}
    return sorted(dte), dte


def _publish(real) -> None:
    """Price `real`'s chain as the stored capture it is, at the price Schwab sent with it."""
    publish_capture(
        ticker_storage_key(real.ticker),
        [dict(c) for c in real.chain],
        real.now.timestamp(),
        real.spot,
        real.now.date().isoformat(),
        real.now,
    )


def _forget_levels() -> None:
    with level_store._lock:
        for tk in (A, B):
            level_store._levels.pop(tk, None)


@pytest.fixture
def no_levels():
    """Each test starts with neither ticker's levels published, and leaves none.

    The pricing thread is held meanwhile, as behind another ticker's chain: the reprice a page's
    selection queues (server.ticker_selected) would price the captured chain at today's clock, so
    it waits and is dropped with the test.
    """
    _forget_levels()
    gate = threading.Event()
    server.chain_pricing.submit(gate.wait, 60)
    yield
    with server._chains_waiting_lock:
        for tk in (A, B):
            server._chains_waiting.pop(tk, None)
    gate.set()
    server.chain_pricing.submit(lambda: None).result(timeout=60)
    _forget_levels()


async def _serve_panels(body) -> None:
    """Serve /ws with the daemon's own heartbeat (capture.Daemon.status); run `body` on its URL."""
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), [])
    sock, url = listener()
    stop, stats = asyncio.Event(), {}
    served = asyncio.create_task(
        serve_page_socket(stop, sock, {"heartbeat_fn": daemon.status, "stats": stats})
    )
    end = time_et.elapsed() + 5
    while "clients" not in stats and time_et.elapsed() < end:
        await asyncio.sleep(0.01)
    assert "clients" in stats  # serving
    try:
        await asyncio.wait_for(body(f"{url}/ws"), 30)
    finally:
        stop.set()
        await asyncio.wait_for(served, 5)


#: the panels a page always shows: the expiry dropdown's list (ed-core.js `_panels`)
LIST = {"expiries": {}}


async def _select(ws, ticker, panels=LIST) -> list[dict]:
    """Subscribe the page on `ticker`, showing `panels`; return the frames up to its answer.

    The answer is the `symbols` frame, included. Every frame the server sent before it is in the
    list: a frame the page was owed before this subscribe arrives ahead of the answer.
    """
    await ws.send(
        json.dumps({"op": "subscribe", "symbols": [], "ticker": ticker, "panels": panels})
    )
    return await _frames_until(ws, lambda m: m["type"] == "symbols")


async def _frames_until(ws, pred, timeout=5.0) -> list[dict]:
    """Return every frame up to and including the first that `pred` accepts."""
    seen, end = [], time_et.elapsed() + timeout
    while time_et.elapsed() < end:
        msg = json.loads(await asyncio.wait_for(ws.recv(), max(0.01, end - time_et.elapsed())))
        seen.append(msg)
        if pred(msg):
            return seen
    raise AssertionError(f"no matching frame within {timeout}s: {seen}")


def _lists(frames) -> list[dict]:
    return [m for m in frames if m["type"] == "expiries"]


async def _next_list(ws) -> dict:
    return (await _frames_until(ws, lambda m: m["type"] == "expiries"))[-1]


def _assert_list(frame, ticker, real) -> None:
    exps, dte = _expected(real.chain)
    assert frame["ticker"] == ticker
    assert frame["expiries"] == exps and frame["dte"] == dte and frame["reason"] is None
    for e in exps:
        y, m, d = e.split("-")
        assert frame["labels"][e] == f"{m}/{d}/{y}"
        assert frame["dte_text"][e] == f"{dte[e]:g}DTE"


@pytest.mark.usefixtures("no_levels")
def test_a_page_gets_its_tickers_expiry_list_at_once_with_no_get():
    _publish(CRWD)

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, CRWD.ticker.lower())  # as typed: the key is the server's
            _assert_list(await _next_list(ws), A, CRWD)

    asyncio.run(_serve_panels(body))
    assert "/api/expiries" not in {r.path for r in server.app.routes}


@pytest.mark.usefixtures("no_levels")
def test_a_ticker_with_no_chain_yet_reads_unknown_with_the_levels_reason():
    async def body(url):
        async with connect(url) as ws:
            await _select(ws, CRWD.ticker)
            frame = await _next_list(ws)
            reason = push_verdict.terrain_staleness(None, A, now=time_et.now())[
                "levels_stale_reason"
            ]
            assert frame["ticker"] == A and frame["expiries"] is None and frame["labels"] is None
            assert frame["dte"] is None and frame["dte_text"] is None
            assert frame["reason"] == reason and reason

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_a_new_chain_reaches_only_the_pages_on_its_ticker():
    async def body(url):
        async with connect(url) as on_a, connect(url) as on_b:
            await _select(on_a, A)
            await _select(on_b, B)
            assert (await _next_list(on_a))["expiries"] is None  # no chain of either yet
            assert (await _next_list(on_b))["expiries"] is None
            await asyncio.to_thread(_publish, CRWD)  # the pricing thread prices A's chain
            _assert_list(await _next_list(on_a), A, CRWD)
            # nothing for B: a frame owed before B's next subscribe arrives ahead of its answer
            assert _lists(await _select(on_b, B)) == []
            await asyncio.to_thread(_publish, MRVL)
            _assert_list(await _next_list(on_b), B, MRVL)  # B's next list is its own chain's
            assert _lists(await _select(on_a, A)) == []
            # a subscribe that changes nothing is owed nothing: the list drawn stands
            assert _lists(await _select(on_a, A)) == []
            await asyncio.to_thread(_publish, CRWD)
            _assert_list(await _next_list(on_a), A, CRWD)

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_switching_ticker_sends_the_new_list_at_once_and_stops_the_old():
    _publish(CRWD)
    _publish(MRVL)

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, A)
            _assert_list(await _next_list(ws), A, CRWD)
            await _select(ws, B)
            _assert_list(await _next_list(ws), B, MRVL)
            await asyncio.to_thread(_publish, CRWD)  # the ticker the page left
            assert _lists(await _select(ws, B)) == []
            await asyncio.to_thread(_publish, MRVL)  # the ticker it is on
            _assert_list(await _next_list(ws), B, MRVL)

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_a_page_that_drops_and_returns_gets_the_list_again():
    _publish(CRWD)

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, A)
            _assert_list(await _next_list(ws), A, CRWD)
        async with connect(url) as ws:  # the page's reconnect, then its subscribe
            await _select(ws, A)
            _assert_list(await _next_list(ws), A, CRWD)

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_a_page_with_no_ticker_gets_no_list():
    _publish(CRWD)

    async def body(url):
        async with connect(url) as ws:
            assert _lists(await _select(ws, None)) == []
            await asyncio.to_thread(_publish, CRWD)
            assert _lists(await _select(ws, None)) == []

    asyncio.run(_serve_panels(body))


# -- the levels' panels: Vanna and Charm by strike, each in the window the page asks -------------


def _kind(frames, kind) -> list[dict]:
    return [m for m in frames if m["type"] == kind]


async def _next(ws, kind) -> dict:
    return (await _frames_until(ws, lambda m: m["type"] == kind))[-1]


def _published_rows(tk, key) -> list:
    """Return the rows the levels producer published for `tk` (the whole book's vanna or charm).

    As the panel serves them: each by name, with its strike as listed and its value as the screen
    shows it (compact_text: delta-shares), and its mark (_marks: the price's strike of these rows).
    """
    rows = level_store.published_levels(tk).snap.per_strike[key]
    marks = _marks(tk, [r.strike for r in rows])
    return [
        {
            "strike": r.strike,
            "value": r.value,
            "strike_text": strike_text(r.strike),
            "text": compact_text(r.value),
            "marks": marks(r.strike),
        }
        for r in rows
    ]


def _marks(tk, listed, **walls):
    """Return a row's marks by its strike, worked out here, each with its name on the screen.

    The listed strike nearest the live price, then the `walls` given (call, put).
    """
    live = lmp.get_quote(tk).spot  # Schwab's last trade as the daemon holds it
    spot = None if live is None else min(listed, key=lambda k: abs(k - live))
    at = {"spot": spot, **walls}
    labels = {
        "spot": "SPOT",
        "call": "Gamma Call",
        "put": "Gamma Put",
    }
    return lambda strike: [
        {"kind": kind, "label": labels[kind]} for kind, k in at.items() if k == strike
    ]


ALL = {"scope": "all", "centre": None, "shift": 0, "expiry": None}


@pytest.mark.usefixtures("no_levels")
def test_a_page_on_the_vanna_and_charm_tabs_gets_each_panel_at_once():
    _publish(CRWD)

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, CRWD.ticker, {**LIST, "vanna": ALL, "charm": ALL})
            seen = {}
            while len(seen) < 3:
                frame = json.loads(await asyncio.wait_for(ws.recv(), 5))
                seen[frame["type"]] = frame
            assert set(seen) == {"expiries", "vanna", "charm"}
            for frame, key in ((seen["vanna"], "vanna"), (seen["charm"], "charm")):
                assert frame["ticker"] == A and frame["available"] is True
                assert frame["rows"] == _published_rows(A, key) and frame["rows"]

    asyncio.run(_serve_panels(body))
    paths = {r.path for r in server.app.routes}
    assert not paths & {"/api/options/vanna-by-strike", "/api/options/charm-by-strike"}


@pytest.mark.usefixtures("no_levels")
def test_the_panel_is_drawn_in_the_window_its_subscribe_asks():
    """The operator's pan: 11 rows (Auto) centred two rows past the strike the drag began on."""
    _publish(MRVL)
    rows = _published_rows(B, "vanna")
    strikes = [r["strike"] for r in rows]
    assert len(strikes) > 30
    asked = {"scope": "auto", "centre": strikes[10], "shift": 2, "expiry": None}

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, B, {"vanna": asked})
            frame = await _next(ws, "vanna")
            assert frame["view"]["centre"] == strikes[12] and frame["scope"] == "auto"
            assert frame["rows"] == rows[7:18]
            await _select(ws, B, {"vanna": {**asked, "scope": "most"}})  # one it cannot draw
            assert await _next(ws, "vanna") == {
                "type": "vanna",
                "ticker": B,
                "available": False,
                "reason": "scope 'most' is not one of auto, wider, all",
            }

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_before_the_tickers_levels_the_panel_is_unavailable_with_its_reason():
    async def body(url):
        async with connect(url) as ws:
            await _select(ws, CRWD.ticker, {"vanna": ALL})
            assert await _next(ws, "vanna") == {
                "type": "vanna",
                "ticker": A,
                "available": False,
                "reason": "no levels published for this ticker yet",
            }  # never an empty list of rows standing for it

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_new_levels_reach_only_the_pages_showing_the_panel_on_that_ticker():
    async def body(url):
        async with connect(url) as on_a, connect(url) as on_b, connect(url) as list_only:
            await _select(on_a, A, {"vanna": ALL})
            await _select(on_b, B, {"vanna": ALL})
            await _select(list_only, A)  # A's page, on a tab with no levels panel
            for ws in (on_a, on_b):
                assert (await _next(ws, "vanna"))["available"] is False  # no levels of either yet
            await _next(list_only, "expiries")
            await asyncio.to_thread(_publish, CRWD)  # the pricing thread publishes A's levels
            frame = await _next(on_a, "vanna")
            assert frame["ticker"] == A and frame["rows"] == _published_rows(A, "vanna")
            # nothing for B's page, nor for A's page not showing it: a frame owed before the next
            # subscribe arrives ahead of its answer
            assert _kind(await _select(on_b, B, {}), "vanna") == []
            assert _kind(await _select(list_only, A), "vanna") == []

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_a_switch_sends_the_new_tickers_panel_and_none_of_the_old():
    _publish(CRWD)
    _publish(MRVL)

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, A, {"charm": ALL})
            assert (await _next(ws, "charm"))["ticker"] == A
            await _select(ws, B, {"charm": ALL})
            frame = await _next(ws, "charm")
            assert frame["ticker"] == B and frame["rows"] == _published_rows(B, "charm")
            await asyncio.to_thread(_publish, CRWD)  # the ticker the page left
            assert _kind(await _select(ws, B, {}), "charm") == []

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_a_page_that_drops_and_returns_gets_its_panels_again():
    _publish(CRWD)

    async def body(url):
        for _ in range(2):  # the page, then its reconnect and its subscribe
            async with connect(url) as ws:
                await _select(ws, A, {**LIST, "vanna": ALL})
                assert (await _next(ws, "vanna"))["rows"] == _published_rows(A, "vanna")

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_a_producer_held_on_the_levels_lock_does_not_stall_the_beat():
    """The beat keeps going while a panel's producer waits; the panel arrives after.

    Induced condition: the levels' lock held 2.5 s by another thread, as the pricing thread holds
    it while it publishes; every panel's producer reads it.
    """
    _publish(CRWD)
    release = threading.Event()

    def hold(held: threading.Event) -> None:
        with level_store._lock:
            held.set()
            release.wait(5)

    async def body(url):
        async with connect(url) as ws:
            held = threading.Event()
            holder = asyncio.create_task(asyncio.to_thread(hold, held))
            await asyncio.to_thread(held.wait, 5)
            await ws.send(
                json.dumps(
                    {"op": "subscribe", "symbols": [], "ticker": A, "panels": {"vanna": ALL}}
                )
            )
            beats, end = 0, time_et.elapsed() + 2.5
            while time_et.elapsed() < end:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 2.5))
                assert msg["type"] != "vanna"  # its producer still waits on the lock
                beats += msg["type"] == "feed"
            assert beats >= 2, beats
            release.set()
            await holder
            assert (await _next(ws, "vanna"))["rows"] == _published_rows(A, "vanna")

    try:
        asyncio.run(_serve_panels(body))
    finally:
        release.set()


@pytest.mark.usefixtures("no_levels")
def test_a_producer_that_raises_fails_its_panel_alone_in_words():
    """The panel says why; the socket stays open, prices and the other panels keep coming.

    Induced condition: CRWD's published levels hold no vanna rows (None), so the vanna producer
    raises reading them, as a defect in a producer would.
    """
    _publish(CRWD)
    held = level_store.published_levels(A)
    broken = replace(held.snap, per_strike={**held.snap.per_strike, "vanna": None})
    level_store.publish(A, replace(held, snap=broken))

    async def body(url):
        async with connect(url) as ws:
            await ws.send(
                json.dumps(
                    {
                        "op": "subscribe",
                        "symbols": [A],
                        "ticker": A,
                        "panels": {**LIST, "vanna": ALL, "charm": ALL},
                    }
                )
            )
            seen = {}
            while {"expiries", "vanna", "charm", "feed"} - set(seen):
                frame = json.loads(await asyncio.wait_for(ws.recv(), 5))
                seen[frame["type"]] = frame
            assert seen["vanna"] == {
                "type": "vanna",
                "ticker": A,
                "failed": "the program could not produce this panel: "
                "TypeError: 'NoneType' object is not iterable",
            }
            assert seen["charm"]["rows"] == _published_rows(A, "charm")
            assert seen["expiries"]["expiries"] == _expected(CRWD.chain)[0]
            assert [r["ticker"] for r in seen["feed"]["rows"]] == [A]  # the beat's price rows
            # the socket is open: a subscribe asking another window is answered, the failure too
            assert _kind(await _select(ws, A, {"vanna": {**ALL, "scope": "auto"}}), "symbols")
            assert "failed" in await _next(ws, "vanna")

    asyncio.run(_serve_panels(body))


# -- the levels themselves: the terrain panel, one per reader (Key Levels, the chart, the desk) ---

#: two readers of the terrain on one page: Key Levels and the Gamma chart (ed-gamma-panels.js,
#: ed-gamma-chart.js), each its own panel of the one producer
TERRAIN_READERS = {"terrain:levels": {}, "terrain:chart": {}}


def _published_terrain(tk) -> dict:
    """Return the levels the producer published for `tk`: what every terrain panel carries."""
    snap = level_store.published_levels(tk).snap
    return {"call_wall": snap.call_wall, "put_wall": snap.put_wall, "gamma_flip": snap.gamma_flip}


def _terrain_of(frame) -> dict:
    return {k: frame[k] for k in ("call_wall", "put_wall", "gamma_flip")}


@pytest.mark.usefixtures("no_levels")
def test_each_terrain_reader_gets_the_published_levels_at_once_with_no_get():
    _publish(CRWD)

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, CRWD.ticker.lower(), {**LIST, **TERRAIN_READERS})
            seen = {}
            while set(TERRAIN_READERS) - set(seen):
                frame = json.loads(await asyncio.wait_for(ws.recv(), 5))
                seen[frame["type"]] = frame
            for name in TERRAIN_READERS:
                assert seen[name]["ticker"] == A and seen[name]["error"] == ""
                assert _terrain_of(seen[name]) == _published_terrain(A)
                assert seen[name]["call_wall"] is not None

    asyncio.run(_serve_panels(body))
    assert "/api/terrain" not in {r.path for r in server.app.routes}


@pytest.mark.usefixtures("no_levels")
def test_before_the_tickers_chain_the_terrain_says_why_with_no_level():
    async def body(url):
        async with connect(url) as ws:
            await _select(ws, A, {"terrain:levels": {}})
            frame = await _next(ws, "terrain:levels")
            assert frame["error"].startswith("terrain_not_ready: no chain from the daemon yet")
            assert frame["regime"] == "UNAVAILABLE"
            # unknown, never an empty or zero level standing for it
            assert frame["call_wall"] is None and frame["gamma_flip"] is None

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_new_levels_reach_only_the_pages_showing_the_terrain_on_that_ticker():
    async def body(url):
        async with connect(url) as on_a, connect(url) as on_b, connect(url) as list_only:
            await _select(on_a, A, {"terrain:desk": {}})
            await _select(on_b, B, {"terrain:desk": {}})
            await _select(list_only, A)  # A's page, on a tab with no levels panel
            for ws in (on_a, on_b):
                assert "error" in await _next(ws, "terrain:desk")  # no levels of either yet
            await _next(list_only, "expiries")
            await asyncio.to_thread(_publish, CRWD)  # the pricing thread publishes A's levels
            frame = await _next(on_a, "terrain:desk")
            assert frame["ticker"] == A and _terrain_of(frame) == _published_terrain(A)
            assert _kind(await _select(on_b, B, {}), "terrain:desk") == []
            assert _kind(await _select(list_only, A), "terrain:desk") == []

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_a_switch_sends_the_new_tickers_terrain_and_none_of_the_old():
    _publish(CRWD)
    _publish(MRVL)

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, A, {"terrain:map": {}})
            assert (await _next(ws, "terrain:map"))["ticker"] == A
            await _select(ws, B, {"terrain:map": {}})
            frame = await _next(ws, "terrain:map")
            assert frame["ticker"] == B and _terrain_of(frame) == _published_terrain(B)
            await asyncio.to_thread(_publish, CRWD)  # new levels on the ticker the page left
            assert _kind(await _select(ws, B, {}), "terrain:map") == []

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_a_page_that_drops_and_returns_gets_its_terrain_again():
    _publish(CRWD)

    async def body(url):
        for _ in range(2):  # the page, then its reconnect and its subscribe
            async with connect(url) as ws:
                await _select(ws, A, {**LIST, "terrain:levels": {}})
                frame = await _next(ws, "terrain:levels")
                assert _terrain_of(frame) == _published_terrain(A)

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_a_terrain_producer_that_raises_fails_its_panel_alone_in_words():
    """The panel says why; the socket stays open and the other panels keep coming.

    INDUCED: CRWD's published snapshot holds a regime the terrain's read has no words for, so
    the terrain raises wording it, as a defect in its producer would.
    """
    _publish(CRWD)
    held = level_store.published_levels(A)
    level_store.publish(A, replace(held, snap=replace(held.snap, regime="NO SUCH REGIME")))

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, A, {**LIST, "terrain:levels": {}, "charm": ALL})
            seen = {}
            while {"expiries", "terrain:levels", "charm"} - set(seen):
                frame = json.loads(await asyncio.wait_for(ws.recv(), 5))
                seen[frame["type"]] = frame
            assert seen["terrain:levels"] == {
                "type": "terrain:levels",
                "ticker": A,
                "failed": "the program could not produce this panel: KeyError: 'NO SUCH REGIME'",
            }
            assert seen["charm"]["rows"] == _published_rows(A, "charm")
            assert seen["expiries"]["expiries"] == _expected(CRWD.chain)[0]
            # the socket is open: a subscribe for another reader is answered, the failure too
            assert _kind(await _select(ws, A, {"terrain:chart": {}}), "symbols")
            assert "failed" in await _next(ws, "terrain:chart")

    asyncio.run(_serve_panels(body))


# -- the per-strike rows: the strikes panel, each reader in its own window ----------------------

AUTO = {"scope": "auto", "centre": None, "shift": 0, "expiry": None}


def _per_strike(tk) -> list:
    """Today's rows (strike, net GEX $ per 1%, volume) the producer published for `tk`.

    As the panel serves them: each by name, with its strike and its two numbers as the screen
    shows them, and its marks (_marks: the price's strike, the published walls).
    """
    snap = level_store.published_levels(tk).snap
    rows = snap.per_strike["gex"]
    marks = _marks(tk, [r.strike for r in rows], call=snap.call_wall, put=snap.put_wall)
    return [
        {
            "strike": r.strike,
            "value": r.value,
            "volume": r.volume,
            "strike_text": strike_text(r.strike),
            "text": dollars_text(r.value),
            "volume_text": count_text(r.volume),
            "marks": marks(r.strike),
        }
        for r in rows
    ]


@pytest.mark.usefixtures("no_levels")
def test_each_strikes_reader_gets_its_own_window_at_once_with_no_get():
    """GEX by Strike's Auto window and the chart's All: each the producer's rows for its window."""
    _publish(MRVL)
    rows = _per_strike(B)
    assert len(rows) > 30

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, B, {**LIST, "strikes:gbs": AUTO, "strikes:chart": ALL})
            seen = {}
            while {"strikes:gbs", "strikes:chart"} - set(seen):
                frame = json.loads(await asyncio.wait_for(ws.recv(), 5))
                seen[frame["type"]] = frame
            assert seen["strikes:chart"]["today"] == rows
            gbs = seen["strikes:gbs"]["today"]
            assert len(gbs) == 11 and gbs == rows[rows.index(gbs[0]) : rows.index(gbs[0]) + 11]
            drawn = max(abs(r["value"]) for r in gbs if r["value"] is not None)
            assert seen["strikes:gbs"]["view"]["max_abs"] == drawn

    asyncio.run(_serve_panels(body))
    assert "/api/terrain/strikes" not in {r.path for r in server.app.routes}


@pytest.mark.usefixtures("no_levels")
def test_before_the_tickers_chain_the_strikes_say_why_with_no_row():
    async def body(url):
        async with connect(url) as ws:
            await _select(ws, A, {"strikes:gbs": AUTO})
            frame = await _next(ws, "strikes:gbs")
            assert frame["today"] == [] and frame["max_abs_row"] is None
            assert frame["levels_stale_reason"]  # why, never empty rows standing alone
            await _select(ws, A, {"strikes:gbs": {**AUTO, "shift": "two"}})  # one it cannot draw
            assert await _next(ws, "strikes:gbs") == {
                "type": "strikes:gbs",
                "ticker": A,
                "available": False,
                "reason": "shift 'two' is not a whole number of rows",
            }

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_new_levels_reach_only_the_pages_showing_the_strikes_on_that_ticker():
    async def body(url):
        async with connect(url) as on_a, connect(url) as on_b, connect(url) as list_only:
            await _select(on_a, A, {"strikes:migration": ALL})
            await _select(on_b, B, {"strikes:migration": ALL})
            await _select(list_only, A)
            for ws in (on_a, on_b):
                assert (await _next(ws, "strikes:migration"))["today"] == []
            await _next(list_only, "expiries")
            await asyncio.to_thread(_publish, CRWD)
            frame = await _next(on_a, "strikes:migration")
            assert frame["ticker"] == A and frame["today"] == _per_strike(A)
            assert _kind(await _select(on_b, B, {}), "strikes:migration") == []
            assert _kind(await _select(list_only, A), "strikes:migration") == []

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_a_switch_sends_the_new_tickers_strikes_and_none_of_the_old():
    _publish(CRWD)
    _publish(MRVL)

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, A, {"strikes:desk": ALL})
            assert (await _next(ws, "strikes:desk"))["ticker"] == A
            await _select(ws, B, {"strikes:desk": ALL})
            frame = await _next(ws, "strikes:desk")
            assert frame["ticker"] == B and frame["today"] == _per_strike(B)
            await asyncio.to_thread(_publish, CRWD)
            assert _kind(await _select(ws, B, {}), "strikes:desk") == []

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_a_page_that_drops_and_returns_gets_its_strikes_again():
    _publish(CRWD)

    async def body(url):
        for _ in range(2):
            async with connect(url) as ws:
                await _select(ws, A, {**LIST, "strikes:gbs": ALL})
                assert (await _next(ws, "strikes:gbs"))["today"] == _per_strike(A)

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_a_strikes_producer_that_raises_fails_its_panel_alone_in_words():
    """Induced condition: CRWD's publication holds a prior day with no rows: the strikes raise."""
    _publish(CRWD)
    level_store.publish(A, replace(level_store.published_levels(A), prior_day=object()))

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, A, {**LIST, "strikes:gbs": ALL, "terrain:levels": {}})
            seen = {}
            while {"expiries", "strikes:gbs", "terrain:levels"} - set(seen):
                frame = json.loads(await asyncio.wait_for(ws.recv(), 5))
                seen[frame["type"]] = frame
            assert seen["strikes:gbs"] == {
                "type": "strikes:gbs",
                "ticker": A,
                "failed": "the program could not produce this panel: "
                "AttributeError: 'object' object has no attribute 'per_strike'",
            }
            assert _terrain_of(seen["terrain:levels"]) == _published_terrain(A)

    asyncio.run(_serve_panels(body))


# -- the heatmap: the surface panel, in the window the page asks (scope, pan, columns, expiry) ---

HEATMAP = {**ALL, "cols": None, "expiry": None}


def _surface_expiries(tk) -> list:
    """Return the expiries of the surface the producer published for `tk`, in column order."""
    return [e["expiry"] for e in level_store.published_levels(tk).gamma_surface["expirations"]]


@pytest.mark.usefixtures("no_levels")
def test_the_heatmap_gets_the_published_surface_in_its_window_at_once_with_no_get():
    _publish(MRVL)
    exps = _surface_expiries(B)
    assert len(exps) > 3

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, B, {**LIST, "surface": HEATMAP})
            frame = await _next(ws, "surface")
            assert frame["available"] is True and frame["ticker"] == B
            assert [e["expiry"] for e in frame["expirations"]] == exps
            await _select(ws, B, {"surface": {**HEATMAP, "expiry": exps[1]}})
            one = await _next(ws, "surface")
            assert [e["expiry"] for e in one["expirations"]] == [exps[1]]
            await _select(ws, B, {"surface": {**HEATMAP, "cols": 0}})  # one it cannot draw
            assert await _next(ws, "surface") == {
                "type": "surface",
                "ticker": B,
                "available": False,
                "reason": "cols 0 is not a whole number of columns",
            }

    asyncio.run(_serve_panels(body))
    assert "/api/options/gamma-surface" not in {r.path for r in server.app.routes}


@pytest.mark.usefixtures("no_levels")
def test_before_the_tickers_chain_the_surface_is_unavailable_with_its_reason():
    async def body(url):
        async with connect(url) as ws:
            await _select(ws, A, {"surface": HEATMAP})
            frame = await _next(ws, "surface")
            assert frame["available"] is False and frame["reason"]  # why, never empty cells
            assert "cells" not in frame

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_new_levels_reach_only_the_pages_showing_the_surface_on_that_ticker():
    async def body(url):
        async with connect(url) as on_a, connect(url) as on_b, connect(url) as list_only:
            await _select(on_a, A, {"surface": HEATMAP})
            await _select(on_b, B, {"surface": HEATMAP})
            await _select(list_only, A)
            for ws in (on_a, on_b):
                assert (await _next(ws, "surface"))["available"] is False
            await _next(list_only, "expiries")
            await asyncio.to_thread(_publish, CRWD)
            frame = await _next(on_a, "surface")
            assert frame["ticker"] == A and frame["available"] is True
            assert [e["expiry"] for e in frame["expirations"]] == _surface_expiries(A)
            assert _kind(await _select(on_b, B, {}), "surface") == []
            assert _kind(await _select(list_only, A), "surface") == []

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_a_switch_and_a_reconnect_send_the_surface_of_the_ticker_on_screen_only():
    _publish(CRWD)
    _publish(MRVL)

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, A, {"surface": HEATMAP})
            assert (await _next(ws, "surface"))["ticker"] == A
            await _select(ws, B, {"surface": HEATMAP})
            assert (await _next(ws, "surface"))["ticker"] == B
            await asyncio.to_thread(_publish, CRWD)  # new levels on the ticker the page left
            assert _kind(await _select(ws, B, {}), "surface") == []
        async with connect(url) as ws:  # the page's reconnect and its subscribe
            await _select(ws, B, {**LIST, "surface": HEATMAP})
            assert (await _next(ws, "surface"))["ticker"] == B

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_a_surface_producer_that_raises_fails_its_panel_alone_in_words():
    """Induced condition: CRWD's published surface holds no strikes (None), so the window raises."""
    _publish(CRWD)
    held = level_store.published_levels(A)
    surface = {**held.gamma_surface, "strikes": None}
    level_store.publish(A, replace(held, gamma_surface=surface))

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, A, {**LIST, "surface": HEATMAP, "terrain:levels": {}})
            seen = {}
            while {"expiries", "surface", "terrain:levels"} - set(seen):
                frame = json.loads(await asyncio.wait_for(ws.recv(), 5))
                seen[frame["type"]] = frame
            assert set(seen["surface"]) == {"type", "ticker", "failed"}
            assert seen["surface"]["failed"].startswith(
                "the program could not produce this panel: TypeError: "
            )
            assert _terrain_of(seen["terrain:levels"]) == _published_terrain(A)

    asyncio.run(_serve_panels(body))


async def _frames_of(ws, kinds) -> dict:
    """Return the next frame of each of `kinds`, by its type."""
    seen = {}
    while set(kinds) - set(seen):
        frame = json.loads(await asyncio.wait_for(ws.recv(), 5))
        seen[frame["type"]] = frame
    return seen


@pytest.mark.usefixtures("no_levels")
def test_each_chain_reader_gets_its_own_expiry_at_once_with_no_get():
    _publish(MRVL)
    exps = level_store.published_levels(B).snap.expiries
    assert len(exps) > 1

    async def body(url):
        async with connect(url) as ws:
            await _select(
                ws, B, {"chain:ladder": {"expiry": None}, "chain:detail": {"expiry": exps[1]}}
            )
            seen = await _frames_of(ws, ("chain:ladder", "chain:detail"))
            front, second = seen["chain:ladder"], seen["chain:detail"]
            assert front["ticker"] == B and front["status"] == "ok" and front["expiry"] == exps[0]
            assert second["status"] == "ok" and second["expiry"] == exps[1]

            def served(frame):
                return {c["symbol"] for r in frame["ladder"] for c in (r["call"], r["put"]) if c}

            assert served(front) and served(second)
            assert served(front).isdisjoint(served(second))
            await _select(ws, B, {"chain:ladder": {}})  # a reader that names no expiry
            assert (await _next(ws, "chain:ladder"))["status"] == "unavailable"

    asyncio.run(_serve_panels(body))
    assert "/api/chain" not in {r.path for r in server.app.routes}


@pytest.mark.usefixtures("no_levels")
def test_before_the_tickers_chain_the_chain_says_why_with_no_contract():
    async def body(url):
        async with connect(url) as ws:
            await _select(ws, A, {"chain:ladder": {"expiry": None}})
            frame = await _next(ws, "chain:ladder")
            assert frame["status"] == "unavailable" and frame["ladder"] == []
            assert frame["scope"]["reason"] == push_chain.NO_CHAIN_YET

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_new_levels_reach_only_the_pages_showing_the_chain_on_that_ticker():
    async def body(url):
        async with connect(url) as on_a, connect(url) as on_b, connect(url) as list_only:
            await _select(on_a, A, {"chain:ladder": {"expiry": None}})
            await _select(on_b, B, {"chain:ladder": {"expiry": None}})
            await _select(list_only, A)
            for ws in (on_a, on_b):
                assert (await _next(ws, "chain:ladder"))["status"] == "unavailable"
            await _next(list_only, "expiries")
            await asyncio.to_thread(_publish, CRWD)
            frame = await _next(on_a, "chain:ladder")
            assert frame["ticker"] == A and frame["status"] == "ok"
            assert frame["expiry"] == level_store.published_levels(A).snap.expiries[0]
            assert _kind(await _select(on_b, B, {}), "chain:ladder") == []
            assert _kind(await _select(list_only, A), "chain:ladder") == []

    asyncio.run(_serve_panels(body))


@pytest.mark.usefixtures("no_levels")
def test_a_chain_producer_that_raises_fails_its_panel_alone_in_words():
    """Induced condition: CRWD's priced chain holds a contract that is None, so the chain raises."""
    _publish(CRWD)
    held = level_store.published_levels(A)
    level_store.publish(A, replace(held, priced_chain=[None, *held.priced_chain]))

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, A, {"chain:ladder": {"expiry": None}, "terrain:levels": {}})
            seen = await _frames_of(ws, ("chain:ladder", "terrain:levels"))
            assert set(seen["chain:ladder"]) == {"type", "ticker", "failed"}
            assert seen["chain:ladder"]["failed"].startswith(
                "the program could not produce this panel: AttributeError: "
            )
            assert _terrain_of(seen["terrain:levels"]) == _published_terrain(A)

    asyncio.run(_serve_panels(body))


def _levels_of(frame) -> dict:
    """Return the gamma levels a levels panel carries, by id."""
    return {r["id"]: r["price"] for r in frame["levels"] if r["family"] == "gamma"}


@pytest.mark.usefixtures("no_levels")
def test_each_levels_reader_gets_its_own_timeframe_at_once_with_no_get():
    _publish(CRWD)

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, A, {"levels:view": {"tf": "1"}, "levels:map": {"tf": "15"}})
            seen = await _frames_of(ws, ("levels:view", "levels:map"))
            assert seen["levels:view"]["tf"] == "1" and seen["levels:map"]["tf"] == "15"
            for frame in seen.values():
                assert frame["ticker"] == A
                assert _levels_of(frame)["call_wall"] == _published_terrain(A)["call_wall"]
            await _select(ws, A, {"levels:view": {"tf": "2"}})  # a timeframe the chart has not
            frame = await _next(ws, "levels:view")
            assert frame["failed"] == (
                "the program could not produce this panel: ValueError: "
                "tf '2' is not one of 1, 3, 5, 15, 30, 60, D"
            )

    asyncio.run(_serve_panels(body))
    assert "/api/levels" not in {r.path for r in server.app.routes}


@pytest.mark.usefixtures("no_levels")
def test_each_price_row_of_the_ticker_sends_its_levels_again_from_that_price():
    _publish(CRWD)
    moved = CRWD.spot + 1.25

    async def body(url):
        async with connect(url) as ws:
            await _select(ws, A, {"levels:desk": {"tf": "1"}})
            await _next(ws, "levels:desk")
            at = time_et.now()
            lmp.record_from_level_one_equity(
                A,
                {"LAST_PRICE": moved, "TRADE_TIME_MILLIS": int(at * 1000)},
                received_ts=at,
            )
            frame = await _next(ws, "levels:desk")
            # its levels' distances are from that price (the price itself is the price row's)
            priced = [r for r in frame["levels"] if r["price"] is not None]
            assert priced and all(r["distance"] == r["price"] - moved for r in priced)
            lmp.record_from_level_one_equity(  # another ticker's price is not this panel's
                B,
                {"LAST_PRICE": MRVL.spot, "TRADE_TIME_MILLIS": int(at * 1000)},
                received_ts=at,
            )
            assert _kind(await _select(ws, A, {"levels:desk": {"tf": "1"}}), "levels:desk") == []

    asyncio.run(_serve_panels(body))
