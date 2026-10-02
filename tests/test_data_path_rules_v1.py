"""docs/DATA_FLOW.md §2, the data rules D1-D6, through the real code.

Each Schwab frame enters where Schwab hands it to the daemon (capture._publisher, the
schwab-py handler) and is read where the console reads it: a WebSocket client of the daemon's
real push server (live_push.serve_live_push), the console's own intake, and the console's
routes. Real data: captured TSLA option quotes (tests/fixtures/real_options_stream_history_
samples.json), SPY equity books and the SPY 0DTE chain. Stand-ins are named where used.
"""
from __future__ import annotations

import asyncio
import json
import socket
import sqlite3
import time
from pathlib import Path

import pytest
from websockets.asyncio.client import connect

from app.market_data.schwab.streaming import capture, live_push
from calibration.complete_chain_capture import chain_messages
from stream_spine import LOG, CaptureWriter, HealthRegistry, MessageBus

FX = Path(__file__).resolve().parent / "fixtures"
_OPT = json.loads((FX / "real_options_stream_history_samples.json").read_text(encoding="utf-8"))
_EVENTS = [e for e in _OPT["contracts"][0]["events"] if e["kind"] == "l1"]
_CONTRACT = _OPT["contracts"][0]["symbol"]
_CHAIN = json.loads((FX / "real_spy_0dte_chain.json").read_text(encoding="utf-8"))


# ── the real daemon, from Schwab's handler to a connected console ────────────────────────────

def _frame(service: str, items: list[dict], ts_ms: int) -> dict:
    """A Schwab streamer data block as schwab-py hands it to the handler: service, Schwab's own
    frame timestamp, command, and the labeled items."""
    return {"service": service, "timestamp": ts_ms, "command": "SUBS", "content": items}


def _port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def _daemon_then_console(publish, *, read_for: float = 1.0,
                               connected: bool = False) -> list[dict]:
    """Start the daemon's real push server on its real bus and let `publish(handler_for)` hand it
    Schwab frames, with a console connected before (`connected`) or connecting after; return
    every message the console receives within `read_for` s: [{"topic": ..., "msg": ...}]."""
    bus, health, stop, stats, port = MessageBus(), HealthRegistry(), asyncio.Event(), {}, _port()
    server = asyncio.create_task(live_push.serve_live_push(
        bus, stop, port=port, stats=stats,
        heartbeat_fn=lambda: {"ts": time.time(), "schwab_socket_open": True, "held": {}}))
    try:
        for _ in range(500):
            if stats.get("listening"):
                break
            await asyncio.sleep(0.01)
        if not connected:
            publish(lambda service: capture._publisher(service, bus, health))
        got: list[dict] = []
        async with connect(f"ws://127.0.0.1:{port}", max_size=None) as ws:
            if connected:
                for _ in range(500):
                    if stats.get("clients"):
                        break
                    await asyncio.sleep(0.01)
                publish(lambda service: capture._publisher(service, bus, health))
            end = time.monotonic() + read_for
            while time.monotonic() < end:
                try:
                    frame = await asyncio.wait_for(ws.recv(), timeout=end - time.monotonic())
                except (asyncio.TimeoutError, TimeoutError):
                    break
                m = json.loads(frame)
                if m.get("topic") != "daemon.heartbeat":
                    got.append(m)
        return got
    finally:
        stop.set()
        await asyncio.gather(server, return_exceptions=True)


def _values(obj) -> list:
    """Every (key, value) pair anywhere inside a received message, but the times the daemon
    keeps for each field (`field_ts`), which are not Schwab's fields."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "field_ts":
                continue
            out.append((k, v))
            out.extend(_values(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_values(v))
    return out


def _holds(msg, key, value) -> bool:
    return any(k == key and v == value for k, v in _values(msg))


# ── D1. Newest by Schwab's time wins ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("connected", [True, False], ids=["console-connected", "console-reconnects"])
def test_d1_a_quote_that_arrives_late_never_replaces_a_newer_one(connected):
    """Two captured quotes of one contract, Schwab's QUOTE_TIME_MILLIS apart; the newer reaches
    the daemon first and the older arrives after it. What the console holds as current is the
    newer, whether it was connected or connects after: arrival order never decides."""
    older, newer = (e["content"] for e in _EVENTS[:2])
    assert older["QUOTE_TIME_MILLIS"] < newer.get("QUOTE_TIME_MILLIS", older["QUOTE_TIME_MILLIS"] + 1)
    newer = {**newer, "QUOTE_TIME_MILLIS": newer.get("QUOTE_TIME_MILLIS", older["QUOTE_TIME_MILLIS"] + 1000)}
    shared = [k for k in newer if k in older and k != "key" and older[k] != newer[k]]
    assert shared, "the two captured quotes share a field with different values"

    def publish(handler_for):
        h = handler_for("LEVELONE_OPTIONS")
        h(_frame("LEVELONE_OPTIONS", [newer], newer["QUOTE_TIME_MILLIS"]))
        h(_frame("LEVELONE_OPTIONS", [older], older["QUOTE_TIME_MILLIS"]))   # late
    got = asyncio.run(_daemon_then_console(publish, connected=connected))
    current: dict = {}
    for m in got:
        if m["topic"] == f"optquote.{_CONTRACT}":
            for k in shared:
                for key, v in _values(m["msg"]):
                    if key == k:
                        current[k] = v
    assert current == {k: newer[k] for k in shared}, "the late, older quote replaced the newer one"


# ── D2. Everything Schwab sends is kept ─────────────────────────────────────────────────────

def test_d2_every_field_and_schwabs_own_timestamp_reach_the_console():
    """A CHART_EQUITY bar with every field Schwab's Streamer Guide lists (SEQUENCE, CHART_DAY
    included) and the frame's own timestamp: each reaches the console as sent. Stand-in: the
    bar's values are SPY's captured 1-minute bar; SEQUENCE and CHART_DAY are named stand-ins."""
    bars = json.loads((FX / "real_spy_1m_bars_2026_09_24_25.json").read_text(encoding="utf-8"))
    bar = bars["bars"][0]
    item = {"key": "SPY", "SEQUENCE": 1042, "OPEN_PRICE": bar["open"], "HIGH_PRICE": bar["high"],
            "LOW_PRICE": bar["low"], "CLOSE_PRICE": bar["close"], "VOLUME": bar["volume"],
            "CHART_TIME_MILLIS": bar["timestamp"], "CHART_DAY": 20356}
    frame_ts = bar["timestamp"] + 59_000

    got = asyncio.run(_daemon_then_console(
        lambda handler_for: handler_for("CHART_EQUITY")(_frame("CHART_EQUITY", [item], frame_ts))))
    sent = [m["msg"] for m in got if m["topic"] == "bar1m.SPY"]
    assert sent, "the bar never reached the console"
    missing = [k for k, v in item.items() if not _holds(sent[-1], k, v)]
    assert not missing, f"fields Schwab sent that the console never got: {missing}"
    assert any(v == frame_ts for _k, v in _values(sent[-1])), "Schwab's frame timestamp was dropped"


# ── D3. The live path holds only the newest ─────────────────────────────────────────────────

def test_d3_a_burst_leaves_one_current_record_per_symbol_not_every_message():
    """50 contracts each quoted 200 times (captured quote fields, a newer QUOTE_TIME each time)
    before the console reads: the daemon holds and sends one current record per contract, never
    10,000 old messages waiting in line."""
    base = _EVENTS[0]["content"]
    t0 = base["QUOTE_TIME_MILLIS"]
    keys = [f"TSLA  260831C{367500 + 2500 * i:08d}" for i in range(50)]   # stand-in strikes

    def publish(handler_for):
        h = handler_for("LEVELONE_OPTIONS")
        for n in range(200):
            h(_frame("LEVELONE_OPTIONS", [{**base, "key": k, "QUOTE_TIME_MILLIS": t0 + n, "MARK": n}
                                          for k in keys], t0 + n))
    got = asyncio.run(_daemon_then_console(publish, read_for=3.0, connected=True))
    quotes = [m for m in got if m["topic"].startswith("optquote.")]
    assert len(quotes) <= 2 * len(keys), f"{len(quotes)} quote messages for {len(keys)} symbols"
    last = {}
    for m in quotes:
        for k, v in _values(m["msg"]):
            if k == "MARK":
                last[m["topic"]] = v
    assert set(last.values()) == {199}, "a contract's current record is not its newest quote"


def test_d3_an_older_chain_never_waits_behind_a_newer_one():
    """Ten SPY chains fetched (the captured SPY 0DTE chain, ten fetch times) before the console
    reads: only the newest chain is sent; an older one never queues ahead of it."""
    contracts = _CHAIN["chain"]
    fetched = [1790346600.0 + 10 * i for i in range(10)]
    got = asyncio.run(_chains_then_console(contracts, fetched))
    times = sorted({m["msg"]["ts_recv"] for m in got if m["topic"] == "chain.SPY"})
    assert times == [fetched[-1]], f"chains sent: {times}"


async def _chains_then_console(contracts, fetched) -> list[dict]:
    """A connected console, then the daemon's chain sweep publishing `fetched` chains on the
    daemon's bus as it does (capture.run_chains: chain_messages, each part published) before the
    console reads."""
    bus, stop, stats, port = MessageBus(), asyncio.Event(), {}, _port()
    server = asyncio.create_task(live_push.serve_live_push(
        bus, stop, port=port, stats=stats,
        heartbeat_fn=lambda: {"ts": time.time(), "schwab_socket_open": True, "held": {}}))
    try:
        for _ in range(500):
            if stats.get("listening"):
                break
            await asyncio.sleep(0.01)
        async with connect(f"ws://127.0.0.1:{port}", max_size=None) as ws:
            for _ in range(500):
                if stats.get("clients"):
                    break
                await asyncio.sleep(0.01)
            for ts in fetched:
                for topic, msg in chain_messages("SPY", contracts, ts):
                    bus.publish(topic, msg)
            got = []
            end = time.monotonic() + 3.0
            while time.monotonic() < end:
                try:
                    frame = await asyncio.wait_for(ws.recv(), timeout=end - time.monotonic())
                except (asyncio.TimeoutError, TimeoutError):
                    break
                m = json.loads(frame)
                if m.get("topic") != "daemon.heartbeat":
                    got.append(m)
            return got
    finally:
        stop.set()
        await asyncio.gather(server, return_exceptions=True)


# ── D4. The database is the memory ──────────────────────────────────────────────────────────

def test_d4_the_one_writer_records_every_message_schwab_sends(tmp_path):
    """Every captured quote of the contract is written to the history database, each with every
    field Schwab sent."""
    db = tmp_path / "stream_capture.db"

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        h = capture._publisher("LEVELONE_OPTIONS", bus, health)
        for e in _EVENTS:
            h(_frame("LEVELONE_OPTIONS", [e["content"]], e["content"].get("QUOTE_TIME_MILLIS", 0)))
        await asyncio.sleep(0.3)
        stop.set()
        await task
    asyncio.run(go())
    con = sqlite3.connect(db)
    rows = [json.loads(r[0]) for r in con.execute("SELECT native_json FROM stream_options_quotes_raw")]
    con.close()
    assert len(rows) == len(_EVENTS)
    for e, row in zip(_EVENTS, rows):
        assert all(_holds(row, k, v) for k, v in e["content"].items())


# ── D5. Nothing old is served as current ────────────────────────────────────────────────────

def test_d5_a_price_whose_feed_is_down_is_not_served_as_the_current_price(monkeypatch):
    """SPY's last price from the daemon's price row, its feed no longer live (no daemon
    heartbeat): the console's one spot (server.resolve_spot) serves no current price."""
    import live_market_plane as lmp
    import live_price_rows
    import server
    from app.options.order_flow import streaming as ofs
    then = time.time() - 600
    lmp.record_from_level_one_equity("SPY", {"LAST_PRICE": 767.39, "TRADE_TIME_MILLIS": int(then * 1000),
                                             "QUOTE_TIME_MILLIS": int(then * 1000)}, received_ts=then)
    row = live_price_rows.price_row("SPY")
    assert row["feed_live"] is False
    monkeypatch.setitem(ofs._price_rows, "SPY", row)
    spot, _source, _ts = server.resolve_spot("SPY")
    assert spot is None, "a price from a feed that is down was served as the current price"


def test_d5_a_daemon_status_that_waited_in_a_queue_is_not_current():
    """The daemon's status, stamped by the daemon two minutes ago, arrives now: the console
    judges it by the daemon's own time, not by when it arrived."""
    import live_market_plane as lmp
    old = time.time() - 120
    lmp.record_feed_heartbeat({"ts": old, "schwab_socket_open": True,         # arrives now
                               "held": {"LEVELONE_EQUITIES": ["SPY"]}})
    try:
        assert lmp.daemon_status() is None, "a two-minute-old daemon status counted as live"
    finally:
        lmp.record_feed_down()


# ── D6. No live screen reads the database ───────────────────────────────────────────────────

def test_d6_no_live_route_opens_a_database(monkeypatch):
    """Every live GET route of the console, with both databases present and holding SPY's data
    (the stream database written by the real writer: a captured SPY book and the captured option
    quote; the console database), then SQLite made to refuse: none opens a database. The routes
    are read from the app itself; /api/changes is the push stream (it never ends)."""
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient
    import server
    from db import get_db
    from stream_spine import book_msg, options_quote_msg
    books = json.loads((FX / "real_spy_nyse_nasdaq_books.json").read_text(encoding="utf-8"))["books"]
    writer = CaptureWriter()                                 # the canonical stream database
    for service, b in books.items():
        writer.insert("book.SPY", book_msg(symbol="SPY", service=service, content=b["content"],
                                           src="schwab_book", ts_recv=time.time()))
    writer.insert(f"optquote.{_CONTRACT}", options_quote_msg(
        symbol=_CONTRACT, content=_EVENTS[0]["content"], src="schwab_options_l1", ts_recv=time.time()))
    get_db()                                                 # the console database
    opened: list = []

    def refuse(*a, **k):
        opened.append(str(a[0]) if a else "")
        raise sqlite3.OperationalError("a live screen read the database")
    monkeypatch.setattr(sqlite3, "connect", refuse)
    client = TestClient(server.app, raise_server_exceptions=False)
    routes = [r.path for r in server.app.routes if isinstance(r, APIRoute) and "GET" in r.methods
              and r.path.startswith("/api/") and "{" not in r.path and r.path != "/api/changes"]
    assert routes
    # what the page sends: every route must run, not answer "invalid request"
    params = {"ticker": "SPY", "contract": _CONTRACT, "venue": "NYSE_BOOK", "tf": "5", "minutes": "60"}
    readers, refused = [], []
    for path in routes:
        opened.clear()
        if client.get(path, params=params).status_code == 422:
            refused.append(path)
        if opened:
            readers.append(path)
    assert not refused, f"routes the test did not run (invalid request): {refused}"
    assert not readers, f"live routes that read the database: {readers}"
