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

import push_changes
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

def test_the_wanted_list_is_the_consoles_now_and_a_change_clears_that_services_refusals():
    """The list is what the console says now: a daemon starts with none (2026-10-01 review: a
    restarted daemon streamed the books and contracts last asked for before any console said
    so), and a list withdrawn (the console gone) is none."""
    bus, health = ss.MessageBus(), ss.HealthRegistry()
    d = cap.Daemon(bus, health)
    assert d.wanted == _wanted() and d.active is None, "no built-in symbol list: the console decides"
    d.set_wanted({"active": "spy", "NYSE_BOOK": ["spy"], "LEVELONE_OPTIONS": ["SPY   261120C00875000"],
                  "BOGUS": ["X"]})
    assert d.wanted == _wanted(NYSE_BOOK=["SPY"], LEVELONE_OPTIONS=["SPY   261120C00875000"])
    assert d.active == "SPY"
    assert cap.Daemon(bus, health).wanted == _wanted(), "a daemon that starts holds no earlier list"
    d.set_wanted(None)                                   # the console's connection ended
    assert d.wanted == _wanted() and d.active is None
    d.set_wanted({"NYSE_BOOK": ["spy"], "LEVELONE_OPTIONS": ["SPY   261120C00875000"]})
    d.refused = {s: {} for s in cap.SERVICES}
    d.refused["NYSE_BOOK"] = {"SPY": "x"}
    d.refused["LEVELONE_OPTIONS"] = {"ZZZ": "x"}
    d.set_wanted({"NYSE_BOOK": ["QQQ"], "LEVELONE_OPTIONS": ["SPY   261120C00875000"]})
    assert d.refused["NYSE_BOOK"] == {} and d.refused["LEVELONE_OPTIONS"] == {"ZZZ": "x"}


def test_every_board_ticker_and_every_equity_the_screens_show_is_streamed(tmp_path):
    """Every board ticker is streamed on LEVELONE_EQUITIES, CHART_EQUITY and NEWS_HEADLINE beside
    every equity the console's screens show (the watchlist, the header's context, the ticker on
    screen)."""
    d = cap.Daemon(ss.MessageBus(), ss.HealthRegistry(), board=["$SPX", "SPY"])
    d.set_wanted({"LEVELONE_EQUITIES": ["AMD"], "CHART_EQUITY": ["AMD"], "NEWS_HEADLINE": ["AMD"],
                  "NYSE_BOOK": ["SPY"]})
    w = d.all_wanted()
    assert w["LEVELONE_EQUITIES"] == w["CHART_EQUITY"] == w["NEWS_HEADLINE"] == {"$SPX", "SPY", "AMD"}
    assert w["NYSE_BOOK"] == {"SPY"}
    assert d.status()["board"] == ["$SPX", "SPY"]


def test_the_ticker_on_screen_is_the_chain_sweeps_active_ticker(tmp_path):
    """Operator 2026-10-01: the ticker on screen's chain is fetched ahead of the board. The
    console names it (`active`); the daemon never works it out from another list (2026-10-01
    audit: it was read back out of the books list)."""
    d = cap.Daemon(ss.MessageBus(), ss.HealthRegistry(), board=["SPY"])
    d.chains = cap.ChainSweep(tmp_path / "x.db", d.board, lambda t, m: None)
    d.set_wanted({"active": "MU", "NYSE_BOOK": ["MU"], "NASDAQ_BOOK": ["MU"]})
    assert d.chains._next(0.0) == "MU"
    d.set_wanted({"active": "TSLA", "NYSE_BOOK": ["AAPL"], "NASDAQ_BOOK": ["AAPL"]})
    assert d.chains._next(0.0) == "TSLA", "the named ticker, not the books"


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


def _daemon(tmp_path, monkeypatch, fake, board=(), **wanted):
    bus = ss.MessageBus()
    log = bus.subscribe("sub.", maxsize=100)
    d = cap.Daemon(bus, ss.HealthRegistry(), board=list(board))
    d.set_wanted({k: list(v) for k, v in wanted.items()})
    d.stream = object()
    monkeypatch.setattr(cap, "_request", fake.request)
    return d, log


def test_sync_subscribes_the_difference_and_logs_every_answer(tmp_path, monkeypatch):
    fake = FakeSchwab()
    d, log = _daemon(tmp_path, monkeypatch, fake, board=["SPY", "AAPL"], NYSE_BOOK=["SPY"])
    asyncio.run(d.sync())
    assert fake.calls == [("LEVELONE_EQUITIES", "SUBS", ["AAPL", "SPY"]), ("CHART_EQUITY", "SUBS", ["AAPL", "SPY"]),
                          ("NYSE_BOOK", "SUBS", ["SPY"]), ("NEWS_HEADLINE", "SUBS", ["AAPL", "SPY"])]
    assert d.held["LEVELONE_EQUITIES"] == {"SPY", "AAPL"} and d.held["NYSE_BOOK"] == {"SPY"}
    assert [log.queue.get_nowait()[1]["code"] for _ in range(4)] == [0, 0, 0, 0]
    fake.calls.clear()
    asyncio.run(d.sync())
    assert fake.calls == [], "nothing changed, nothing sent"


def test_a_refused_symbol_is_recorded_and_retried_only_after_the_list_changes(tmp_path, monkeypatch):
    fake = FakeSchwab(refuse={"BAD"})
    d, log = _daemon(tmp_path, monkeypatch, fake, OPTIONS_BOOK=["BAD"])
    asyncio.run(d.sync())
    assert "BAD" in d.refused["OPTIONS_BOOK"] and d.held["OPTIONS_BOOK"] == set()
    assert log.queue.get_nowait()[1]["code"] != 0
    fake.calls.clear()
    asyncio.run(d.sync())
    assert fake.calls == [], "a refused symbol is not asked for again"
    d.set_wanted({"OPTIONS_BOOK": ["BAD", "SPY"]})
    fake.refuse.clear()
    asyncio.run(d.sync())
    assert fake.calls == [("OPTIONS_BOOK", "SUBS", ["BAD", "SPY"])]


def test_a_dead_socket_during_sync_ends_the_connection(tmp_path, monkeypatch):
    fake = FakeSchwab(die_on=("OPTIONS_BOOK", "SUBS"))
    d, _ = _daemon(tmp_path, monkeypatch, fake, OPTIONS_BOOK=["SPY"])
    with pytest.raises(ConnectionError):
        asyncio.run(d.sync())
    assert d.refused["OPTIONS_BOOK"] == {}, "a dead socket is not Schwab refusing a symbol"


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
    connect_args: "list[dict | None]" = []

    def __init__(self, client):
        self.client = client
        self._handlers = defaultdict(list)
        self.last_frame_ts = time.time()
        self.frames: "asyncio.Queue | None" = None

    async def login(self, websocket_connect_args=None):
        FakeStream.connect_args.append(websocket_connect_args)
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
    FakeStream.connect_args = []
    monkeypatch.setattr(cap, "_open_stream", FakeStream)
    monkeypatch.setattr(cap, "RECONNECT_BACKOFF_SEC", (0.01,))
    fake = FakeSchwab()
    monkeypatch.setattr(cap, "_request", fake.request)
    bus = ss.MessageBus()
    d = cap.Daemon(bus, ss.HealthRegistry(), board=["SPY"])
    d.set_wanted({"NYSE_BOOK": ["SPY"]})
    stop = asyncio.Event()

    async def until(cond):
        deadline = time.monotonic() + 10
        while not cond():
            assert time.monotonic() < deadline, "the daemon did not get there in 10 s"
            await asyncio.sleep(0.01)

    async def go():
        client = type("State", (), {"ok": True, "client": object(), "message": ""})()
        task = asyncio.create_task(d.run(lambda: client, stop))
        try:
            await until(lambda: FakeStream.logins >= 1 and d.held["NYSE_BOOK"])
            d.stream.frames.put_nowait(ConnectionClosedError(None, None))      # Schwab drops us
            await until(lambda: FakeStream.logins >= 2 and d.held["NYSE_BOOK"])
        finally:
            stop.set()
            await asyncio.wait_for(task, 5)
    asyncio.run(go())
    subs = [c for c in fake.calls if c[1] == "SUBS"]
    assert subs.count(("NYSE_BOOK", "SUBS", ["SPY"])) == 2, "resubscribed after the reconnect"
    assert FakeStream.most_live == 1 and FakeStream.live == 0
    # no receive cap of ours: Schwab's frames are taken whole, whatever their size (operator
    # 2026-10-01: no caps); the websockets default refuses a frame over 1 MiB
    assert FakeStream.connect_args == [{"max_size": None}] * 2


def test_silence_from_schwab_ends_the_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(cap, "_open_stream", FakeStream)
    monkeypatch.setattr(cap, "DEAD_SEC", 0.2)
    monkeypatch.setattr(cap, "_request", FakeSchwab().request)
    d = cap.Daemon(ss.MessageBus(), ss.HealthRegistry())

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
    cap._publisher("LEVELONE_EQUITIES", bus, health)({"content": [item]})
    topic, q = sub.queue.get_nowait()
    assert topic == "quote.SPY" and q["bid"] == 1.0 and q["last"] == 2.0 and q["native"] == item
    book = {"key": "SPY", "BOOK_TIME": 1, "BIDS": [], "ASKS": []}
    cap._publisher("NYSE_BOOK", bus, health)({"content": [book, {"BIDS": []}]})
    topic, b = sub.queue.get_nowait()
    assert topic == "book.SPY" and b["content"] == book and b["service"] == "NYSE_BOOK"
    assert sub.queue.empty(), "an item with no symbol is skipped"
    news = {"key": "SPY", "4": "headline"}
    cap._publisher("NEWS_HEADLINE", bus, health)({"content": [news]})
    assert sub.queue.get_nowait()[1]["content"] == news
    cap._publisher("LEVELONE_OPTIONS", bus, health)({"content": [{"BIDS": []}]})
    assert health.last("LEVELONE_OPTIONS") is None, "a frame that delivered nothing is not data"
    assert health.last("NYSE_BOOK") is not None


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
    """The daemon holds the list of the connection that sent it last; that connection ending
    withdraws it, and another connection ending does not (2026-10-01 review: an old connection
    noticed closed after the console reconnected wiped the live console's list)."""
    from websockets.asyncio.client import connect
    port = _free_port()
    d = cap.Daemon(ss.MessageBus(), ss.HealthRegistry())

    async def until(cond):
        for _ in range(250):
            if cond():
                return
            await asyncio.sleep(0.02)
        raise AssertionError("not reached")

    async def go():
        stop = asyncio.Event()
        server = asyncio.create_task(serve_live_push(
            ss.MessageBus(), stop, port=port, heartbeat_fn=lambda: {"schwab_socket_open": True},
            on_wanted=d.set_wanted))
        for _ in range(100):
            try:
                a = await connect(f"ws://127.0.0.1:{port}")
                break
            except OSError:
                await asyncio.sleep(0.05)
        env = json.loads(await asyncio.wait_for(a.recv(), 5))
        await a.send(json.dumps({"op": "wanted", "wanted": {"active": "SPY", "NYSE_BOOK": ["SPY"]}}))
        await until(lambda: d.active == "SPY")
        b = await connect(f"ws://127.0.0.1:{port}")               # the console reconnects
        await b.send(json.dumps({"op": "wanted", "wanted": {"active": "MU", "NYSE_BOOK": ["MU"]}}))
        await until(lambda: d.active == "MU")
        await a.close()                                           # the old connection's end is noticed
        await asyncio.sleep(0.3)
        kept = (d.active, d.wanted["NYSE_BOOK"])
        await b.close()                                           # the console's own connection ends
        await until(lambda: d.active is None)
        stop.set()
        await asyncio.wait_for(server, 5)
        return env, kept
    env, kept = asyncio.run(go())
    assert env == {"topic": "daemon.heartbeat", "msg": {"schwab_socket_open": True}}
    assert kept == ("MU", frozenset({"MU"})), "another connection's end leaves the live list"
    assert d.wanted["NYSE_BOOK"] == frozenset(), "withdrawn when the connection that sent it ended"


# ------------------------------------------------------------------ the console side

@pytest.fixture
def console(monkeypatch):
    from app.options.order_flow import streaming as ofs
    monkeypatch.setattr(push_changes, "_open", [])
    monkeypatch.setattr(ofs, "_active_option_contract", None)
    monkeypatch.setattr(ofs, "_active_option_contracts", [])
    import live_market_plane as lmp
    lmp.record_feed_down()
    return ofs


def test_the_console_wants_the_tickers_equity_book_and_contracts(console):
    ofs = console
    push_changes.subscribe("NVDA")                       # a page open on NVDA
    ofs._active_option_contract = "NVDA  261016C00200000"
    ofs._active_option_contracts = ["NVDA  261016C00210000"]
    w = ofs.current_wanted()
    assert w["LEVELONE_EQUITIES"] == w["CHART_EQUITY"] == w["NEWS_HEADLINE"]
    assert w["LEVELONE_EQUITIES"][:4] == ["NVDA", *ofs.MARKET_CONTEXT_SYMBOLS]
    assert w["active"] == "NVDA" and w["NYSE_BOOK"] == w["NASDAQ_BOOK"] == ["NVDA"]
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
        push_changes.subscribe("AMD")                    # a page opens on AMD
        await asyncio.sleep(0.05)
        t.cancel()
    asyncio.run(go())
    assert len(sent) == 2 and sent[1]["wanted"]["NYSE_BOOK"] == ["AMD"]


def test_one_live_rule_every_reader_agrees_and_all_fail_closed_at_one_limit(console):
    """ONE-15 (2026-09-28 audit): "is it live" had four limits -- 3 s (price), 5 s (daemon
    status), 10 s (option greeks), 25 s (book) -- plus the daemon's 5 s/30 s message-age states,
    so one moment could read live on one card and dead on the next. One rule now: the daemon's
    heartbeat is under FEED_HEARTBEAT_MAX_AGE_SEC, its Schwab socket is open, and it holds the
    symbol on that service. A service quiet for 45 s on that feed is live (Schwab sends changes)."""
    import live_market_plane as lmp
    ofs = console
    status = {"schwab_socket_open": True,
              "health": {"OPTIONS_BOOK": {"age_sec": 45.0}},
              "held": {"LEVELONE_EQUITIES": ["MU"], "LEVELONE_OPTIONS": ["B", "A"], "OPTIONS_BOOK": ["A"]},
              "refused": {"LEVELONE_OPTIONS": {"C": "code 19"}}}

    def diag(sym):     # the served option-contract diagnostics for `sym`
        return ofs.get_option_contract_streaming_diagnostics(sym)

    def readers():
        return (lmp.feed_live_for("MU", "LEVELONE_EQUITIES"), lmp.feed_live_for("A", "LEVELONE_OPTIONS"),
                diag("A")["feed_health"]["book"]["state"], ofs.is_option_producer_daemon_available())

    def held(sym):
        return diag(sym)["producer_l1_contract"], diag(sym)["producer_book_contract"]

    assert readers() == (False, False, "NOT LIVE", False)
    limit = lmp.FEED_HEARTBEAT_MAX_AGE_SEC
    lmp.record_feed_heartbeat(status, time.time() - limit + 0.5)
    assert readers() == (True, True, "LIVE", True)
    assert diag("A")["feed_health"]["book"]["age_sec"] == 45.0
    assert not lmp.feed_live_for("B", "OPTIONS_BOOK")               # held on L1 only
    assert held("B") == ("B", "A")                                  # B held on L1, the book holds A
    assert ofs.read_producer_rejected_option_contracts() == {"C": "code 19"}
    lmp.record_feed_heartbeat(status, time.time() - limit - 0.5)
    assert readers() == (False, False, "NOT LIVE", False)
    assert held("B") == (None, None)
    lmp.record_feed_heartbeat({**status, "schwab_socket_open": False}, time.time())
    assert readers() == (False, False, "NOT LIVE", True)             # the daemon is up, Schwab is not


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


def test_the_daemons_log_is_kept_on_disk_with_times(monkeypatch, tmp_path):
    """Under pythonw there is no console: every line must reach logs/stream_capture.log with
    its wall time (2026-09-23: 42 socket deaths, not one reason on disk)."""
    import logging

    import runtime_layout
    monkeypatch.setattr(runtime_layout, "logs_dir", lambda: tmp_path)
    monkeypatch.setattr(sys, "stderr", None)
    root = logging.getLogger()
    saved = root.handlers[:]
    root.handlers = []
    try:
        cap._start_log()
        cap.log.warning("schwab: connection ended (socket closed)")
        for h in root.handlers:
            h.flush()
        text = (tmp_path / "stream_capture.log").read_text(encoding="utf-8")
        assert "connection ended" in text and text[:4].isdigit()
    finally:
        for h in root.handlers:
            h.close()
        root.handlers = saved
