"""The simple capture daemon (operator 2026-09-25: "simple, simple, simple"): the console sends
one wanted list; the daemon subscribes the difference, logs Schwab's answer, fans every message
out, and reconnects + resubscribes when Schwab goes silent. These tests hold each of those
behaviours with a fake Schwab connection, and the real local sockets where it matters."""
from __future__ import annotations

import asyncio
import json
import socket
import sqlite3
import sys
import time
from collections import defaultdict

import pytest

import stream_spine as ss
from app.market_data.schwab.streaming import capture as cap
from app.market_data.schwab.streaming.live_push import serve_live_push


def _wanted(**kw):
    return {s: frozenset(kw.get(s, ())) for s in cap.SERVICES}


# ------------------------------------------------------------------ the sync decision

def test_first_request_of_a_service_is_subs_later_ones_add():
    empty = _wanted()
    assert cap.plan(_wanted(NYSE_BOOK=["SPY"]), empty, {}) == [("NYSE_BOOK", "SUBS", ["SPY"])]
    held = _wanted(NYSE_BOOK=["SPY"])
    assert cap.plan(_wanted(NYSE_BOOK=["SPY", "QQQ"]), held, {}) == [("NYSE_BOOK", "ADD", ["QQQ"])]


def test_dropped_symbols_are_unsubscribed_before_new_ones_are_added():
    held = _wanted(LEVELONE_EQUITIES=["SPY", "AAPL"])
    got = cap.plan(_wanted(LEVELONE_EQUITIES=["SPY", "MSFT"]), held, {})
    assert got == [("LEVELONE_EQUITIES", "UNSUBS", ["AAPL"]), ("LEVELONE_EQUITIES", "ADD", ["MSFT"])]


def test_replacing_everything_held_starts_the_service_over_with_subs():
    held = _wanted(NYSE_BOOK=["SPY"])
    got = cap.plan(_wanted(NYSE_BOOK=["NVDA"]), held, {})
    assert got == [("NYSE_BOOK", "UNSUBS", ["SPY"]), ("NYSE_BOOK", "SUBS", ["NVDA"])]


def test_refused_symbols_are_not_asked_for_again_and_nothing_to_do_is_nothing():
    want = _wanted(LEVELONE_OPTIONS=["A", "B"])
    assert cap.plan(want, _wanted(LEVELONE_OPTIONS=["A"]), {"LEVELONE_OPTIONS": {"B": "no"}}) == []


def test_requests_are_split_under_schwabs_message_limit():
    syms = [f"SPY   2610{i:02d}C00{i:05d}000" for i in range(4000)]      # ~100 KB of keys
    chunks = cap.split_request(syms)
    assert sum(chunks, []) == syms
    assert len(chunks) > 1
    assert all(len(",".join(c)) <= cap.MAX_REQUEST_BYTES for c in chunks)


# ------------------------------------------------------------------ the wanted list

def test_the_wanted_list_survives_a_restart_and_a_change_clears_that_services_refusals(tmp_path):
    bus, health = ss.MessageBus(), ss.HealthRegistry()
    d = cap.Daemon(bus, health, tmp_path / "w.json")
    assert d.wanted == _wanted(), "no built-in symbol list: the console decides"
    d.set_wanted({"LEVELONE_EQUITIES": ["spy"], "NYSE_BOOK": ["SPY"], "BOGUS": ["X"]})
    assert cap.Daemon(bus, health, tmp_path / "w.json").wanted == _wanted(
        LEVELONE_EQUITIES=["SPY"], NYSE_BOOK=["SPY"])
    d.refused = {s: {} for s in cap.SERVICES}
    d.refused["NYSE_BOOK"] = {"SPY": "x"}
    d.refused["LEVELONE_EQUITIES"] = {"ZZZ": "x"}
    d.set_wanted({"LEVELONE_EQUITIES": ["SPY"], "NYSE_BOOK": ["QQQ"]})
    assert d.refused["NYSE_BOOK"] == {} and d.refused["LEVELONE_EQUITIES"] == {"ZZZ": "x"}


# ------------------------------------------------------------------ sync against a fake Schwab

class FakeSchwab:
    """Records every request; refuses the symbols in `refuse`; can die mid-request."""

    def __init__(self, refuse=(), die_on=None):
        self.calls, self.refuse, self.die_on = [], set(refuse), die_on

    async def request(self, stream, service, command, symbols):
        self.calls.append((service, command, list(symbols)))
        if self.die_on == (service, command):
            raise ConnectionError("socket closed")
        if command != "UNSUBS" and self.refuse & set(symbols):
            raise RuntimeError("code 19 REACHED_SYMBOL_LIMIT")


def _daemon(tmp_path, monkeypatch, fake, **wanted):
    bus = ss.MessageBus()
    log = bus.subscribe("sub.", maxsize=100)
    d = cap.Daemon(bus, ss.HealthRegistry(), tmp_path / "w.json")
    d.set_wanted({k: list(v) for k, v in wanted.items()})
    d.stream = object()
    monkeypatch.setattr(cap, "_request", fake.request)
    return d, log


def test_sync_subscribes_the_difference_and_logs_every_answer(tmp_path, monkeypatch):
    fake = FakeSchwab()
    d, log = _daemon(tmp_path, monkeypatch, fake, LEVELONE_EQUITIES=["SPY", "AAPL"], NYSE_BOOK=["SPY"])
    asyncio.run(d.sync())
    assert fake.calls == [("LEVELONE_EQUITIES", "SUBS", ["AAPL", "SPY"]), ("NYSE_BOOK", "SUBS", ["SPY"])]
    assert d.held["LEVELONE_EQUITIES"] == {"SPY", "AAPL"} and d.held["NYSE_BOOK"] == {"SPY"}
    assert [log.queue.get_nowait()[1]["code"] for _ in range(2)] == [0, 0]
    fake.calls.clear()
    asyncio.run(d.sync())
    assert fake.calls == [], "nothing changed, nothing sent"


def test_a_refused_symbol_is_recorded_and_retried_only_after_the_list_changes(tmp_path, monkeypatch):
    fake = FakeSchwab(refuse={"BAD"})
    d, log = _daemon(tmp_path, monkeypatch, fake, NYSE_BOOK=["BAD"])
    asyncio.run(d.sync())
    assert "BAD" in d.refused["NYSE_BOOK"] and d.held["NYSE_BOOK"] == set()
    assert log.queue.get_nowait()[1]["code"] != 0
    fake.calls.clear()
    asyncio.run(d.sync())
    assert fake.calls == [], "a refused symbol is not asked for again"
    d.set_wanted({"NYSE_BOOK": ["BAD", "SPY"]})
    fake.refuse.clear()
    asyncio.run(d.sync())
    assert fake.calls == [("NYSE_BOOK", "SUBS", ["BAD", "SPY"])]


def test_a_dead_socket_during_sync_ends_the_connection(tmp_path, monkeypatch):
    fake = FakeSchwab(die_on=("NYSE_BOOK", "SUBS"))
    d, _ = _daemon(tmp_path, monkeypatch, fake, NYSE_BOOK=["SPY"])
    with pytest.raises(ConnectionError):
        asyncio.run(d.sync())
    assert d.refused["NYSE_BOOK"] == {}, "a dead socket is not Schwab refusing a symbol"


def test_request_sends_schwabs_fields_and_never_fields_on_unsubs():
    sent = []

    class S:
        LevelOneEquityFields = LevelOneOptionFields = ChartEquityFields = BookFields = \
            type("E", (), {"__iter__": lambda self: iter([type("F", (), {"value": 0})(),
                                                         type("F", (), {"value": 3})()])})()
        _lock = asyncio.Lock()

        def _make_request(self, *, service, command, parameters):
            sent.append((service, command, parameters))
            return {}, 1

        async def _send(self, obj):
            pass

        async def _await_response(self, rid, service, command):
            pass

    async def go():
        S._lock = asyncio.Lock()
        await cap._request(S(), "NYSE_BOOK", "SUBS", ["SPY"])
        await cap._request(S(), "NEWS_HEADLINE", "ADD", ["SPY"])
        await cap._request(S(), "NYSE_BOOK", "UNSUBS", ["SPY"])
    asyncio.run(go())
    assert sent[0][2] == {"keys": "SPY", "fields": "0,3"}
    assert sent[1][2]["fields"] == ",".join(str(i) for i in cap.NEWS_FIELDS)
    assert sent[2][2] == {"keys": "SPY"}


def test_a_request_schwab_never_answers_is_a_dead_connection(monkeypatch):
    monkeypatch.setattr(cap, "REQUEST_TIMEOUT_SEC", 0.05)

    class S:
        LevelOneEquityFields = LevelOneOptionFields = ChartEquityFields = BookFields = []

        def _make_request(self, **_):
            return {}, 1

        async def _send(self, obj):
            pass

        async def _await_response(self, *a):
            await asyncio.sleep(10)

    async def go():
        s = S()
        s._lock = asyncio.Lock()
        await cap._request(s, "NYSE_BOOK", "SUBS", ["SPY"])
    with pytest.raises(ConnectionError):
        asyncio.run(go())


# ------------------------------------------------------------------ connection lifecycle

class FakeStream:
    """schwab-py StreamClient's surface as the daemon uses it."""
    live = 0            # logged-in sessions right now
    most_live = 0
    logins = 0

    def __init__(self, client):
        self.client = client
        self._handlers = defaultdict(list)
        self.last_frame_ts = time.time()
        self.frames: "asyncio.Queue | None" = None

    async def login(self):
        FakeStream.logins += 1
        FakeStream.live += 1
        FakeStream.most_live = max(FakeStream.most_live, FakeStream.live)
        self.frames = asyncio.Queue()

    async def logout(self):
        FakeStream.live -= 1

    def __getattr__(self, name):
        if name.startswith("add_") and name.endswith("_handler"):
            return lambda h: self._handlers[name].append(h)
        raise AttributeError(name)

    async def handle_message(self):
        item = await self.frames.get()
        if isinstance(item, BaseException):
            raise item
        self.last_frame_ts = time.time()
        for h in self._handlers.get(item["handler"], []):
            h(item["msg"])


def test_a_dying_connection_is_replaced_and_everything_wanted_is_resubscribed(tmp_path, monkeypatch):
    """Reconnect = a new session that holds nothing, then the same sync. At most ONE live
    Schwab session at any instant (the old stream is logged out before the new one logs in)."""
    from websockets.exceptions import ConnectionClosedError
    FakeStream.live = FakeStream.most_live = FakeStream.logins = 0
    monkeypatch.setattr(cap, "_open_stream", FakeStream)
    monkeypatch.setattr(cap, "RECONNECT_BACKOFF_SEC", (0.01,))
    fake = FakeSchwab()
    monkeypatch.setattr(cap, "_request", fake.request)
    bus = ss.MessageBus()
    d = cap.Daemon(bus, ss.HealthRegistry(), tmp_path / "w.json")
    d.set_wanted({"LEVELONE_EQUITIES": ["SPY"], "NYSE_BOOK": ["SPY"]})
    stop = asyncio.Event()

    async def go():
        client = type("State", (), {"ok": True, "client": object(), "message": ""})()
        task = asyncio.create_task(d.run(lambda: client, stop))
        while FakeStream.logins < 1 or not d.held["NYSE_BOOK"]:
            await asyncio.sleep(0.01)
        d.stream.frames.put_nowait(ConnectionClosedError(None, None))      # Schwab drops us
        while FakeStream.logins < 2 or not d.held["NYSE_BOOK"]:
            await asyncio.sleep(0.01)
        stop.set()
        await asyncio.wait_for(task, 5)
    asyncio.run(go())
    subs = [c for c in fake.calls if c[1] == "SUBS"]
    assert subs.count(("NYSE_BOOK", "SUBS", ["SPY"])) == 2, "resubscribed after the reconnect"
    assert FakeStream.most_live == 1 and FakeStream.live == 0


def test_silence_from_schwab_ends_the_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(cap, "_open_stream", FakeStream)
    monkeypatch.setattr(cap, "DEAD_SEC", 0.2)
    monkeypatch.setattr(cap, "_request", FakeSchwab().request)
    d = cap.Daemon(ss.MessageBus(), ss.HealthRegistry(), tmp_path / "w.json")

    async def go():
        await d.run_connection(object(), asyncio.Event())
    with pytest.raises(ConnectionError, match="no frame from Schwab"):
        asyncio.run(asyncio.wait_for(go(), 5))
    assert d.stream is None, "the dead session is logged out and dropped"


# ------------------------------------------------------------------ Schwab's messages

def test_every_service_is_published_verbatim_and_only_delivered_data_counts_as_alive():
    bus, health = ss.MessageBus(), ss.HealthRegistry()
    sub = bus.subscribe("", maxsize=100)
    item = {"key": "SPY", "BID_PRICE": 1.0, "LAST_PRICE": 2.0, "LAST_MIC_ID": "XADF", "TOTAL_VOLUME": 9}
    cap._publish_equity("LEVELONE_EQUITIES", bus, health)({"content": [item]})
    topic, q = sub.queue.get_nowait()
    assert topic == "quote.SPY" and q["bid"] == 1.0 and q["last"] == 2.0 and q["native"] == item
    book = {"key": "SPY", "BOOK_TIME": 1, "BIDS": [], "ASKS": []}
    cap._publish_book("NYSE_BOOK", bus, health)({"content": [book, {"BIDS": []}]})
    topic, b = sub.queue.get_nowait()
    assert topic == "book.SPY" and b["content"] == book and b["service"] == "NYSE_BOOK"
    assert sub.queue.empty(), "an item with no symbol is skipped"
    news = {"key": "SPY", "4": "headline"}
    cap._publish_news(bus, health)({"content": [news]})
    assert sub.queue.get_nowait()[1]["content"] == news
    cap._publish_option_quote(bus, health)({"content": [{"BIDS": []}]})
    assert health.state("LEVELONE_OPTIONS") == "DOWN", "a frame that delivered nothing is not life"
    assert health.state("NYSE_BOOK") == "RUNNING"


def test_the_daemon_never_asks_for_a_trade_tape():
    """TIMESALE_* answers code 11 (probed live 2026-09-25): no service the daemon streams is one."""
    assert not [s for s in cap.SERVICES if "TIMESALE" in s or "ACTIVES" in s]


# ------------------------------------------------------------------ the database

def test_news_and_every_subscription_answer_are_written(tmp_path):
    w = ss.CaptureWriter(tmp_path / "s.db")
    w.insert("news.SPY", ss.news_msg(symbol="SPY", content={"4": "headline"}, src="schwab_news"))
    w.insert("sub.NYSE_BOOK", ss.subscription_msg(service="NYSE_BOOK", command="ADD",
                                                   symbols=["SPY"], code=19, reason="limit"))
    con = sqlite3.connect(tmp_path / "s.db")
    assert json.loads(con.execute("SELECT native_json FROM stream_news_raw").fetchone()[0]) == {"4": "headline"}
    assert con.execute("SELECT service, command, symbols_json, code FROM stream_subscriptions").fetchone() \
        == ("NYSE_BOOK", "ADD", '["SPY"]', 19)


# ------------------------------------------------------------------ the console socket

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_console_socket_carries_the_wanted_list_in_and_the_status_out():
    from websockets.asyncio.client import connect
    got, port = [], _free_port()

    async def go():
        stop = asyncio.Event()
        server = asyncio.create_task(serve_live_push(
            ss.MessageBus(), stop, port=port, heartbeat_fn=lambda: {"schwab_socket_open": True},
            on_wanted=got.append))
        for _ in range(100):
            try:
                ws = await connect(f"ws://127.0.0.1:{port}")
                break
            except OSError:
                await asyncio.sleep(0.05)
        async with ws:
            await ws.send(json.dumps({"op": "wanted", "wanted": {"NYSE_BOOK": ["SPY"]}}))
            env = json.loads(await asyncio.wait_for(ws.recv(), 5))
            for _ in range(50):
                if got:
                    break
                await asyncio.sleep(0.02)
        stop.set()
        await asyncio.wait_for(server, 5)
        return env
    env = asyncio.run(go())
    assert env == {"topic": "daemon.heartbeat", "msg": {"schwab_socket_open": True}}
    assert got == [{"NYSE_BOOK": ["SPY"]}]


# ------------------------------------------------------------------ the console side

@pytest.fixture
def console(monkeypatch):
    from app.options.order_flow import streaming as ofs
    monkeypatch.setattr(ofs, "_active_ticker", None)
    monkeypatch.setattr(ofs, "_active_option_contract", None)
    monkeypatch.setattr(ofs, "_active_option_contracts", [])
    monkeypatch.setattr(ofs, "_equity_demand", {"context": list(ofs.MARKET_CONTEXT_SYMBOLS),
                                                "watchlist": [], "board": []})
    monkeypatch.setattr(ofs, "_daemon_status", None)
    monkeypatch.setattr(ofs, "_daemon_status_rx", None)
    return ofs


def test_the_console_wants_the_ticker_its_book_the_context_and_its_contracts(console):
    ofs = console
    ofs._active_ticker = "NVDA"
    ofs._equity_demand["watchlist"] = ["AAPL"]
    ofs._active_option_contract = "NVDA  261016C00200000"
    ofs._active_option_contracts = ["NVDA  261016C00210000"]
    w = ofs.current_wanted()
    assert w["LEVELONE_EQUITIES"] == ["NVDA", "$SPX", "$NDX", "$VIX", "AAPL"]
    assert w["CHART_EQUITY"] == w["NEWS_HEADLINE"] == w["LEVELONE_EQUITIES"]
    assert w["NYSE_BOOK"] == w["NASDAQ_BOOK"] == ["NVDA"]
    assert w["OPTIONS_BOOK"] == ["NVDA  261016C00200000"]
    assert w["LEVELONE_OPTIONS"] == ["NVDA  261016C00200000", "NVDA  261016C00210000"]


def test_every_desired_state_change_is_sent_once(console):
    ofs = console
    sent = []

    class WS:
        async def send(self, text):
            sent.append(json.loads(text))

    async def go():
        t = asyncio.create_task(ofs._send_wanted(WS()))
        await asyncio.sleep(0.05)
        ofs.declare_equity_symbols("watchlist", ["AMD"])
        await asyncio.sleep(ofs.WANTED_SEND_SEC * 3)
        t.cancel()
    asyncio.run(go())
    assert len(sent) == 2 and "AMD" in sent[1]["wanted"]["LEVELONE_EQUITIES"]


def test_health_and_holdings_come_from_the_daemons_status_and_fail_closed_when_it_stops(console):
    ofs = console
    assert ofs._read_daemon_upstream_health(("NYSE_BOOK",)) == {"NYSE_BOOK": {"state": "UNKNOWN", "age_sec": None}}
    assert ofs.is_option_producer_daemon_available() is False
    ofs._note_daemon_status({"schwab_socket_open": True,
                             "health": {"NYSE_BOOK": {"state": "RUNNING", "age_sec": 0.4}},
                             "held": {"LEVELONE_OPTIONS": ["B", "A"], "OPTIONS_BOOK": ["A"]},
                             "refused": {"LEVELONE_OPTIONS": {"C": "code 19"}}})
    assert ofs._read_daemon_upstream_health(("NYSE_BOOK",))["NYSE_BOOK"]["state"] == "RUNNING"
    assert ofs.read_producer_admitted_option_contracts() == {"LEVELONE_OPTIONS": ["A", "B"], "OPTIONS_BOOK": ["A"]}
    assert ofs.read_producer_rejected_option_contracts() == {"C": "code 19"}
    ofs._daemon_status_rx = time.time() - ofs.DAEMON_STATUS_STALE_SEC - 1
    assert ofs.is_option_producer_daemon_available() is False
    assert ofs.read_producer_admitted_option_contracts() == {"LEVELONE_OPTIONS": [], "OPTIONS_BOOK": []}


# ------------------------------------------------------------------ the process

def test_one_daemon_at_a_time_and_a_dead_owners_lock_is_reclaimed(tmp_path, monkeypatch):
    db = tmp_path / "stream_capture.db"
    fd, lock = cap.acquire_owner_lock(db)
    try:
        with pytest.raises(SystemExit) as e:
            cap.acquire_owner_lock(db)
        assert e.value.code == cap.EXIT_OWNER_LOCK_HELD
    finally:
        cap.release_owner_lock(fd, lock)
    lock.write_text("999999999")                       # a pid that is not running
    fd, lock = cap.acquire_owner_lock(db)
    cap.release_owner_lock(fd, lock)
    assert not lock.exists()


def test_a_checkout_that_may_not_run_live_refuses_before_opening_anything(monkeypatch):
    import runtime_layout
    monkeypatch.setattr(runtime_layout, "live_binding_error", lambda *a, **k: "bound elsewhere")
    ran = []
    monkeypatch.setattr(cap, "run", lambda *a, **k: ran.append(a))
    monkeypatch.setattr(sys, "argv", ["capture"])
    assert cap.main() == 2
    assert ran == [], "no lock, no Schwab socket, no stream database"
