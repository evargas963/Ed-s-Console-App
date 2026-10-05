"""The capture daemon's own decisions and its process: the console's wanted list, the sync plan,
the board, the console socket, the console's side of the list, the owner lock, the start refusal
and the log. Its Schwab connection (subscribe, refuse, reconnect, silence) is tested through
schwab-py and a stand-in streamer in tests/test_data_path_schwab_stream_v1.py."""
from __future__ import annotations

import asyncio
import json
import socket
import sqlite3
import time

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
    """The list is what the console says now: a daemon starts with none (it never streams books or
    contracts no console asked for since it started), and a list withdrawn (the console gone) is
    none."""
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
    """The ticker on screen's chain is fetched ahead of the board. The console names it
    (`active`); the daemon never works it out from another list (such as the books)."""
    d = cap.Daemon(ss.MessageBus(), ss.HealthRegistry(), board=["SPY"])
    d.chains = cap.ChainSweep(tmp_path / "x.db", d.board, lambda t, m: None)
    rth = 1790863200.0                                   # 2026-10-01 10:00 ET, an open session
    d.set_wanted({"active": "MU", "NYSE_BOOK": ["MU"], "NASDAQ_BOOK": ["MU"]})
    assert d.chains._next(rth) == "MU"
    d.set_wanted({"active": "TSLA", "NYSE_BOOK": ["AAPL"], "NASDAQ_BOOK": ["AAPL"]})
    assert d.chains._next(rth) == "TSLA", "the named ticker, not the books"


# ------------------------------------------------------------------ Schwab's messages

def test_every_service_is_published_verbatim_and_only_delivered_data_counts_as_alive():
    bus, health = ss.MessageBus(), ss.HealthRegistry()
    sub = bus.subscribe("", policy=ss.LOG)
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
    withdraws it, and another connection ending (an old one noticed closed after the console
    reconnected) does not."""
    from websockets.asyncio.client import connect
    port, stats = _free_port(), {}
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
            ss.MessageBus(), stop, port=port, stats=stats, on_wanted=d.set_wanted))
        for _ in range(100):
            try:
                a = await connect(f"ws://127.0.0.1:{port}")
                break
            except OSError:
                await asyncio.sleep(0.05)
        await a.send(json.dumps({"op": "wanted", "wanted": {"active": "SPY", "NYSE_BOOK": ["SPY"]}}))
        await until(lambda: d.active == "SPY")
        b = await connect(f"ws://127.0.0.1:{port}")               # the console reconnects
        await b.send(json.dumps({"op": "wanted", "wanted": {"active": "MU", "NYSE_BOOK": ["MU"]}}))
        await until(lambda: d.active == "MU")
        await a.close()                                           # the old connection's end is noticed
        await until(lambda: stats["clients"] == 1)                # the server has handled it
        kept = (d.active, d.wanted["NYSE_BOOK"])
        await b.close()                                           # the console's own connection ends
        await until(lambda: d.active is None)
        stop.set()
        await asyncio.wait_for(server, 5)
        return kept
    kept = asyncio.run(go())
    assert kept == ("MU", frozenset({"MU"})), "another connection's end leaves the live list"
    assert d.wanted["NYSE_BOOK"] == frozenset(), "withdrawn when the connection that sent it ended"


# ------------------------------------------------------------------ the console side

@pytest.fixture
def console():
    """The console with no option contract and the daemon's feed down, set through its own
    calls; the pages a test opens (`pages`) and its contracts are closed after it."""
    import live_market_plane as lmp
    from app.options.order_flow import streaming as ofs
    ofs.clear_active_option_contract(reason="test start")
    ofs.set_active_option_contracts([])
    lmp.record_feed_down()
    pages: list = []
    yield ofs, pages
    for tk, c in pages:
        push_changes.unsubscribe(tk, c)
    ofs.clear_active_option_contract(reason="test end")
    ofs.set_active_option_contracts([])


def test_the_console_wants_the_tickers_equity_book_and_contracts(console):
    ofs, pages = console
    pages.append(("NVDA", push_changes.subscribe("NVDA")))          # a page open on NVDA
    assert ofs.set_active_option_contract("NVDA  261016C00200000")
    assert ofs.set_active_option_contracts(["NVDA  261016C00210000"])
    w = ofs.current_wanted()
    assert w["LEVELONE_EQUITIES"] == w["CHART_EQUITY"] == w["NEWS_HEADLINE"]
    assert w["LEVELONE_EQUITIES"][:4] == ["NVDA", *ofs.MARKET_CONTEXT_SYMBOLS]
    assert w["active"] == "NVDA" and w["NYSE_BOOK"] == w["NASDAQ_BOOK"] == ["NVDA"]
    assert w["OPTIONS_BOOK"] == ["NVDA  261016C00200000"]
    assert w["LEVELONE_OPTIONS"] == ["NVDA  261016C00200000", "NVDA  261016C00210000"]


def test_every_desired_state_change_is_sent_once(console):
    ofs, pages = console
    sent = []

    class WS:
        async def send(self, text):
            sent.append(json.loads(text))

    async def go():
        t = asyncio.create_task(ofs._send_wanted(WS()))
        await asyncio.sleep(0.05)
        pages.append(("AMD", push_changes.subscribe("AMD")))        # a page opens on AMD
        await asyncio.sleep(0.05)
        t.cancel()
    asyncio.run(go())
    assert len(sent) == 2 and sent[1]["wanted"]["NYSE_BOOK"] == ["AMD"]


def test_one_live_rule_every_reader_agrees_and_all_fail_closed_at_one_limit(console):
    """One rule for "is it live", every reader alike: the daemon's heartbeat is under
    FEED_HEARTBEAT_MAX_AGE_SEC, its Schwab socket is open, and it holds the symbol on that
    service. A service quiet for 45 s on that feed is live (Schwab sends changes)."""
    import live_market_plane as lmp
    ofs, _pages = console
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
    lmp.record_feed_heartbeat({**status, "ts": time.time() - limit + 0.5})
    assert readers() == (True, True, "LIVE", True)
    assert diag("A")["feed_health"]["book"]["age_sec"] == 45.0
    assert not lmp.feed_live_for("B", "OPTIONS_BOOK")               # held on L1 only
    assert held("B") == ("B", "A")                                  # B held on L1, the book holds A
    assert ofs.read_producer_rejected_option_contracts() == {"C": "code 19"}
    lmp.record_feed_heartbeat({**status, "ts": time.time() - limit - 0.5})
    assert readers() == (False, False, "NOT LIVE", False)
    assert held("B") == (None, None)
    lmp.record_feed_heartbeat({**status, "schwab_socket_open": False, "ts": time.time()})
    assert readers() == (False, False, "NOT LIVE", True)             # the daemon is up, Schwab is not


# ------------------------------------------------------------------ the process

def test_one_daemon_at_a_time_and_a_dead_owners_lock_is_reclaimed(tmp_path):
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


def test_a_checkout_whose_runtime_is_another_checkout_may_not_start_the_daemon(tmp_path):
    """The binding runtime_layout reports for a checkout whose runtime is another git checkout
    refuses the start (main exits 2 on it before the log, the lock or the daemon); so does any
    argument. Stand-ins: the two checkouts are temporary directories, the other one with .git."""
    import runtime_layout
    this, other = tmp_path / "worktree", tmp_path / "production"
    (other / ".git").mkdir(parents=True)
    this.mkdir()
    binding = runtime_layout.live_binding_error(source_root=this, runtime_root=other)
    assert binding is not None
    assert cap.start_refusal([], binding) == f"CAPTURE DAEMON REFUSED: {binding}"
    assert cap.start_refusal(["--db", "fork.db"], None) == \
        "the capture daemon takes no arguments (got ['--db', 'fork.db'])"
    assert cap.start_refusal([], runtime_layout.live_binding_error(source_root=this, runtime_root=this)) is None


def test_the_daemons_log_is_kept_on_disk_with_times(tmp_path):
    """Under pythonw there is no console: every line reaches logs/stream_capture.log with its
    wall time."""
    import logging

    root = logging.getLogger()
    saved = root.handlers[:]
    root.handlers = []
    try:
        cap.start_log(tmp_path, to_console=False)
        cap.log.warning("schwab: connection ended (socket closed)")
        for h in root.handlers:
            h.flush()
        text = (tmp_path / "stream_capture.log").read_text(encoding="utf-8")
        assert "connection ended" in text and text[:4].isdigit()
    finally:
        for h in root.handlers:
            h.close()
        root.handlers = saved
