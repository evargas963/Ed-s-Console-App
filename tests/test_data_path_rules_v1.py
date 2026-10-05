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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from schwab.client import Client
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import schwab_client as sc
import server
from app.market_data.schwab.streaming import capture, live_push
from calibration.complete_chain_capture import FAILED_PAUSE_SEC, ChainSweep, chain_messages
from liquidity_value_engine import _MATERIALIZED_SNAPSHOTS
from stream_spine import LATEST, LOG, CaptureWriter, HealthRegistry, MessageBus, bar_msg
from tests.feed_live_helper import daemon_bars, forget_daemon_bars, record_daemon_bars
from tests.local_schwab import _SPY_1120_QUOTES, _LocalSchwab, _token_file
from time_et import ET, now_et

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
    server = asyncio.create_task(live_push.serve_live_push(bus, stop, port=port, stats=stats))
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
                got.append(json.loads(frame))
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
    server = asyncio.create_task(live_push.serve_live_push(bus, stop, port=port, stats=stats))
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
                got.append(json.loads(frame))
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


# ── D5. Live while the market is open; the close stands while it is closed ──────────────────

#: Wednesday 2026-09-30, 11:00 ET (RTH) and 22:00 ET (Closed), as epoch seconds
_RTH = 1790780400.0
_CLOSED = 1790820000.0


def _served_at(monkeypatch, now: float, feed_live: bool) -> dict:
    """At `now` (the clock pinned), SPY's last trade and a captured option quote of the contract
    in the daemon's memory, the feed live or not (the daemon's heartbeat holding both symbols, or
    none): what the header row, the console's one spot, the equity book's top and the option
    book's top serve."""
    import live_market_plane as lmp
    import live_price_rows
    import server
    from app.options.order_flow import live_payload
    from app.options.order_flow import streaming as ofs
    from app.options.order_flow.state import push_option_top
    monkeypatch.setattr(time, "time", lambda: now)
    then = now - 600
    lmp.record_from_level_one_equity("SPY", {"LAST_PRICE": 767.39, "BID_PRICE": 767.38, "ASK_PRICE": 767.40,
                                             "TRADE_TIME_MILLIS": int(then * 1000),
                                             "QUOTE_TIME_MILLIS": int(then * 1000)}, received_ts=then)
    push_option_top(_CONTRACT, _EVENTS[0]["content"])
    if feed_live:
        lmp.record_feed_heartbeat({"ts": now, "schwab_socket_open": True,
                                   "held": {"LEVELONE_EQUITIES": ["SPY"], "LEVELONE_OPTIONS": [_CONTRACT]}})
    else:
        lmp.record_feed_down()
    try:
        row = live_price_rows.price_row("SPY")
        monkeypatch.setitem(ofs._price_rows, "SPY", row)
        return {"row": row, "spot": server.resolve_spot("SPY"),
                "equity_book": json.loads(server.api_order_flow_microstructure("SPY", "NYSE_BOOK").body),
                "option_book": live_payload.options_live_payload(_CONTRACT, now)}
    finally:
        lmp.record_feed_down()


def test_d5_a_feed_down_in_an_open_session_is_an_outage_shown_absent_with_its_reason(monkeypatch):
    """RTH, the feed down: the price, the equity top of book and the option top of book are
    absent, each with the outage reason; no last value stands in for a live one."""
    s = _served_at(monkeypatch, _RTH, feed_live=False)
    assert s["row"]["spot"] is None and s["row"]["bid"] is None
    assert s["row"]["outage"] == "Schwab LEVELONE_EQUITIES feed down during RTH"
    assert s["spot"] == (None, "Schwab LEVELONE_EQUITIES feed down during RTH", None)
    assert s["equity_book"]["top_of_book"]["bid"] is None
    assert s["equity_book"]["top_outage"] == "Schwab LEVELONE_EQUITIES feed down during RTH"
    assert s["option_book"]["top_of_book"]["ask"] is None
    assert s["option_book"]["top_outage"] == "Schwab LEVELONE_OPTIONS feed down during RTH"


def test_d5_while_closed_the_values_as_of_the_close_stand_feed_up_or_down(monkeypatch):
    """22:00 ET, the feed down: the last price and both tops of book Schwab sent are served,
    with no outage."""
    s = _served_at(monkeypatch, _CLOSED, feed_live=False)
    assert s["row"]["spot"] == 767.39 and s["row"]["outage"] is None
    assert s["spot"][0] == 767.39
    assert s["equity_book"]["top_of_book"]["bid"] == 767.38 and s["equity_book"]["top_outage"] is None
    assert s["option_book"]["top_of_book"]["ask"] == _EVENTS[0]["content"]["ASK_PRICE"]
    assert s["option_book"]["top_outage"] is None


def test_d5_a_live_feed_in_an_open_session_serves_the_newest_values(monkeypatch):
    """RTH, the feed live: the newest price and tops of book Schwab sent are served."""
    s = _served_at(monkeypatch, _RTH, feed_live=True)
    assert s["row"]["spot"] == 767.39 and s["row"]["outage"] is None
    assert s["spot"][0] == 767.39
    assert s["equity_book"]["top_of_book"]["bid"] == 767.38 and s["equity_book"]["top_outage"] is None
    assert s["option_book"]["top_of_book"]["ask"] == _EVENTS[0]["content"]["ASK_PRICE"]


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


# ── D5 for the chains: the sweep paced by the session calendar ─────────────────────────────
# The real ChainSweep, its clock an input; no network: each fetch the sweep hands out is ended
# by the test (delivered or not), as a worker ends it.

def _et(s: str) -> float:
    return datetime.fromisoformat(s).replace(tzinfo=ET).timestamp()


def _paced(universe: "list[str]", at: str) -> "tuple[ChainSweep, dict]":
    clock = {"now": _et(at)}
    return ChainSweep("unused.db", universe, lambda topic, msg: None, clock=lambda: clock["now"]), clock


def _handed_out(sweep: ChainSweep, now: float, delivered: bool = True) -> "list[str]":
    """Every ticker the sweep hands out at `now` until it hands out none; then each fetch ends."""
    out = []
    while (tk := sweep._next(now)) is not None:
        out.append(tk)
        assert len(out) < 50, "the sweep never stopped handing out tickers"
    for tk in out:
        sweep._done(tk, delivered)
    return out


@pytest.mark.parametrize("at", ["2026-10-01 05:00", "2026-10-01 10:00", "2026-10-01 17:00",
                                "2026-11-27 14:00"],
                         ids=["pre-market", "rth", "after-hours", "after-hours-of-an-early-close"])
def test_d5_in_every_open_session_the_sweep_fetches_without_end(at):
    sweep, clock = _paced(["AAA", "BBB"], at)
    sweep.set_active("OFF")                              # on screen, not in the universe
    assert _handed_out(sweep, clock["now"]) == ["OFF", "AAA", "BBB"]
    assert _handed_out(sweep, clock["now"] + 1) == ["OFF", "AAA", "BBB"], "and again, without end"


def test_d5_once_closed_every_universe_ticker_is_fetched_once_then_nothing_until_the_next_session():
    sweep, _ = _paced(["AAA", "BBB", "CCC"], "2026-10-02 19:59")
    sweep.set_active("OFF")
    assert sweep._next(_et("2026-10-02 19:59")) == "OFF"        # in flight when the market closes
    assert _handed_out(sweep, _et("2026-10-02 20:00")) == ["AAA", "BBB", "CCC"]   # the close values
    sweep._done("OFF", True)
    for later in ("2026-10-02 20:01", "2026-10-03 12:00", "2026-10-04 23:59", "2026-10-05 03:59"):
        assert sweep._next(_et(later)) is None, later
    assert _handed_out(sweep, _et("2026-10-05 04:00")) == ["OFF", "AAA", "BBB", "CCC"], "Monday pre-market"


@pytest.mark.parametrize("at", ["2026-10-03 12:00", "2026-11-26 12:00", "2026-10-01 02:00"],
                         ids=["saturday", "thanksgiving", "a-weeknight"])
def test_d5_a_daemon_started_while_closed_fetches_the_close_values_once_and_a_ticker_joining_the_universe_once(at):
    """While Closed every universe ticker's close values are fetched once: a universe ticker put
    on screen is not fetched again (its close values stand); a ticker that joins the universe
    (Daemon.join, once Schwab lists it) is fetched once, like every universe ticker."""
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), universe=["AAA", "BBB"])
    sweep, clock = _paced(daemon.universe, at)
    daemon.chains = sweep
    assert _handed_out(sweep, clock["now"]) == ["AAA", "BBB"]
    sweep.set_active("AAA")
    assert sweep._next(clock["now"] + 60) is None
    sweep.set_active("OFF")
    assert sweep._next(clock["now"] + 90) is None, "not fetched until it joins"
    daemon.join("OFF")
    assert _handed_out(sweep, clock["now"] + 120) == ["OFF"]
    assert sweep._next(clock["now"] + 180) is None


# ── The universe: every ticker recorded, and every ticker a screen shows that Schwab lists ────
# Real data: Schwab's single-symbol symbol-search replies of 2026-10-05
# (tests/fixtures/real_schwab_instruments_symbol_search_2026_10_05.json: SPY, $SPX and TSLA
# answered with an `instruments` list holding each; NOTREAL answered `{}`); QQQ's FUNDAMENTAL
# answer of 2026-08-20 (tests/fixtures/real_schwab_instruments_2026_08_20.json: the same
# `instruments` list, holding QQQ); the daemon's recorded SPY and TSLA bars; Schwab's refusal of
# 2026-10-04 (code 19). Stand-ins, named: the local servers playing Schwab's host and streamer
# (tests/local_schwab.py; every streamer request answered code 0 unless a test says otherwise);
# for a symbol whose reply was never captured ($NDX, $VIX) the host answers `{}`, Schwab's
# reply for NOTREAL; every chain is the captured SPY 2026-11-20 chain.

_LOOKUP = {s: r["body"] for s, r in json.loads((FX / "real_schwab_instruments_symbol_search_2026_10_05.json")
                                               .read_text(encoding="utf-8"))["replies"].items()}
_QQQ = json.loads((FX / "real_schwab_instruments_2026_08_20.json").read_text(encoding="utf-8"))[
    "answers"]["qqq_fundamental"]["body"]
_REFUSAL = json.loads((FX / "real_schwab_stream_refusal_2026_10_04.json").read_text(encoding="utf-8"))


def test_every_ticker_stored_or_shown_joins_the_universe_only_when_schwab_lists_it(tmp_path):
    """One rule for every ticker. Stored: SPY and TSLA (their bars, as the daemon recorded
    them), read off the event loop after the daemon starts (load_stored) and in the universe
    from then while their lookups are pending. Shown: the browser's watchlist QQQ and NOTREAL
    (the watchlist route), NOTREAL on screen (a page open on it) and the header's context -- the
    console's own wanted frame (streaming.current_wanted), sent by the console's own sender
    over the daemon's socket. The daemon asks Schwab's instrument lookup once per ticker, on its
    one client (the same frame again asks nothing). SPY, TSLA, QQQ and $SPX, listed, are in the
    universe: held on every universe service through the daemon's streamer connection; SPY's
    and QQQ's chains are fetched. NOTREAL (Schwab answers `{}`), $NDX and $VIX (not listed only
    by the stand-in's `{}`: their real replies were not captured), shown and not listed, never
    join, and the console shows Schwab's answer. The answers are recorded by the
    daemon's writer: a restart reads the four back as listed."""
    import push_changes
    from fastapi.testclient import TestClient
    console_db, stream_db = tmp_path / "ed_console.db", tmp_path / "stream_capture.db"
    writer = CaptureWriter(stream_db)
    with sqlite3.connect(stream_db) as con:
        for tk in ("SPY", "TSLA"):
            for r in daemon_bars("real_daemon_bars_spy_tsla_2026_09_29_30.json", tk)[:5]:
                writer.insert(f"bar1m.{r['symbol']}", bar_msg(
                    symbol=r["symbol"], bar_start_ms=r["bar_start_ms"], open=r["open"], high=r["high"],
                    low=r["low"], close=r["close"], volume=r["volume"], src=r["src"], ts_recv=r["ts_recv"],
                    native=r["native"], schwab_ts=r["schwab_ts"]), conn=con)
    listed, unconfirmed = capture.recorded_tickers(console_db, stream_db)
    assert (listed, unconfirmed) == ([], ["SPY", "TSLA"]), "stored, not yet confirmed by Schwab"

    daemon = capture.Daemon(MessageBus(), HealthRegistry())
    schwab = _LocalSchwab(instruments={**_LOOKUP, "QQQ": _QQQ}, unlisted=_LOOKUP["NOTREAL"])
    client = sc.client_from_token_file_atomic(str(_token_file(tmp_path, 3600)), "k", "s", transport=schwab.transport)
    TestClient(server.app).post("/api/streaming/watchlist-symbols", json={"symbols": ["QQQ", "NOTREAL"]})
    page = push_changes.subscribe("NOTREAL")                       # a page open on NOTREAL
    shown = {"QQQ", "NOTREAL", *ofs.MARKET_CONTEXT_SYMBOLS}
    joined = ["$SPX", "QQQ", "SPY", "TSLA"]
    out = {"NOTREAL", "$NDX", "$VIX"}
    reached: list = []

    def there() -> bool:
        return (sorted(daemon.universe) == joined
                and all(set(joined) <= daemon.held[svc] for svc in capture.UNIVERSE_SERVICES)
                and {"SPY", "QQQ"} <= set(schwab.chains_asked)
                and out <= set(daemon.not_joined))

    async def run() -> None:
        stop, stats, port = asyncio.Event(), {}, _port()
        tasks = [asyncio.create_task(capture.load_stored(daemon, console_db, stream_db)),
                 asyncio.create_task(writer.run(daemon.bus.subscribe("", policy=LOG), stop=stop)),
                 asyncio.create_task(live_push.serve_live_push(daemon.bus, stop, port=port, stats=stats,
                                                               on_wanted=daemon.set_wanted)),
                 asyncio.create_task(capture.run_joins(daemon, lambda: client, stop)),
                 asyncio.create_task(capture.run_chains(daemon, console_db, lambda: client, stop)),
                 asyncio.create_task(daemon.run(lambda: client, stop))]
        try:
            for _ in range(500):
                if stats.get("listening"):
                    break
                await asyncio.sleep(0.01)
            async with connect(f"ws://127.0.0.1:{port}") as ws:
                console = asyncio.create_task(ofs._send_wanted(ws))     # the console's own sender
                end = time.monotonic() + 30.0
                while not there() and time.monotonic() < end:
                    await asyncio.sleep(0.05)
                reached.append(there())
                before = len(schwab.instruments_asked)
                ofs.declare_watchlist(["QQQ", "NOTREAL"])               # the same list again
                await asyncio.sleep(0.5)
                reached.append(len(schwab.instruments_asked) == before)  # asks nothing
                console.cancel()
                await asyncio.gather(console, return_exceptions=True)
        finally:
            stop.set()
            await asyncio.gather(*tasks, return_exceptions=True)
    try:
        asyncio.run(run())
    finally:
        schwab.close()
        push_changes.unsubscribe("NOTREAL", page)
        ofs.declare_watchlist([])

    assert reached == [True, True], (daemon.universe, daemon.not_joined, sorted(set(schwab.chains_asked)))
    assert set(schwab.instruments_asked) == {"SPY", "TSLA"} | shown
    assert sorted(daemon.status()["universe"]) == joined
    with sqlite3.connect(stream_db) as con:
        rows = dict(con.execute("SELECT symbol, listed FROM stream_instruments_raw"))
    assert rows == {**{s: 1 for s in joined}, **{s: 0 for s in out}}

    status = daemon.status()
    lmp.record_feed_heartbeat(status)                          # the console's record of the daemon
    try:
        assert sorted(server._universe()) == joined
        assert "Schwab's instrument lookup does not list NOTREAL (HTTP 200: {})" in \
            server.terrain_staleness(None, "NOTREAL")["levels_stale_reason"]
    finally:
        lmp.record_feed_down()
    listed, unconfirmed = capture.recorded_tickers(console_db, stream_db)
    assert listed == joined, "the next start reads the four back as listed"
    assert out <= set(unconfirmed), "and asks Schwab about the others again"


_STORED_ANSWERS = {   # (stored ticker, reply served for it, outcome)
    "Schwab lists TSLA": ("TSLA", _LOOKUP["TSLA"], "listed"),
    "Schwab answers NOTREAL {}": ("NOTREAL", _LOOKUP["NOTREAL"], "not listed"),
    "a list without the ticker": ("TSLA", _LOOKUP["SPY"], "not listed"),    # stand-in: SPY's reply
    "a 200 that is not JSON": ("TSLA", (200, "<html>Service Unavailable</html>"), "no answer"),   # INDUCED
    "a 429": ("TSLA", (429, '{"errors": [{"status": "429"}]}'), "no answer"),                      # INDUCED
}


@pytest.mark.parametrize("answer", list(_STORED_ANSWERS))
def test_a_stored_ticker_is_streamed_until_schwab_answers_and_only_not_listed_takes_it_out(tmp_path, answer):
    """A stored ticker is streamed on every universe service from the first sync, its lookup
    pending. The lookup runs through the daemon's real instrument_answer on schwab-py's client,
    answered with Schwab's replies of 2026-10-05. Listed (TSLA): it stays, confirmed. Schwab's
    "not listed" -- `{}`, its reply for NOTREAL, or an `instruments` list without the ticker --
    unsubscribes it on every universe service at the next sync, shows the answer, and a later
    read of the stored tickers does not put it back this run. No answer -- a 200 that is not
    JSON, any other status -- changes nothing, and it is asked again on the next connection.
    INDUCED CONDITION: the non-JSON 200 and the 429."""
    symbol, served, outcome = _STORED_ANSWERS[answer]
    schwab = _LocalSchwab(instruments={symbol: served})
    client = sc.client_from_token_file_atomic(str(_token_file(tmp_path, 3600)), "k", "s", transport=schwab.transport)
    daemon = capture.Daemon(MessageBus(), HealthRegistry())
    daemon.load([], [symbol])
    assert daemon.joins.get_nowait() == symbol
    held: list = []

    async def run() -> None:
        await daemon.connect(client)
        try:
            await daemon.sync()
            held.append({svc: set(daemon.held[svc]) for svc in capture.UNIVERSE_SERVICES})
            daemon.answered(await asyncio.to_thread(capture.instrument_answer, client, symbol, time.time()))
            await daemon.sync()
            held.append({svc: set(daemon.held[svc]) for svc in capture.UNIVERSE_SERVICES})
        finally:
            await daemon.disconnect()
    try:
        asyncio.run(run())
    finally:
        schwab.close()
    assert held[0] == {svc: {symbol} for svc in capture.UNIVERSE_SERVICES}, "streamed while pending"
    if outcome != "not listed":
        assert held[1] == held[0] and daemon.universe == [symbol], "it stays"
        assert symbol not in daemon.not_joined
        assert (symbol in daemon.listed) is (outcome == "listed")
        daemon.reconnected()                                     # the next connection to Schwab
        assert daemon.joins.empty() is (outcome == "listed"), "no answer: asked again"
        return
    assert held[1] == {svc: set() for svc in capture.UNIVERSE_SERVICES}
    assert {s for s, c, keys in schwab.stream_requests if c == "UNSUBS"} == set(capture.UNIVERSE_SERVICES)
    assert daemon.universe == []
    assert daemon.not_joined[symbol].startswith(f"Schwab's instrument lookup does not list {symbol} (HTTP 200: ")
    daemon.load([], [symbol])                                    # the stored tickers read again
    assert daemon.universe == [], "Schwab's 'not listed' stands for the run"


def test_with_the_daemon_silent_every_ticker_says_so_first():
    """With no current heartbeat no chain is coming and the universe is unknown: no ticker reads
    warming, and each reason starts with the daemon not reporting, whatever else it says.
    INDUCED CONDITION: the daemon's last heartbeat is 100 s old."""
    import push_changes
    silent = "the capture daemon is not reporting (no current heartbeat): its universe is unknown"
    with_levels, first_view = "ZZQX", "ZZQY"                   # arbitrary symbols
    with server._terrain_cache_lock:
        server._terrain_cache[with_levels] = {"computed_ts_utc": time.time(), "spot": 100.0}   # levels, no surface
    pages = [(tk, push_changes.subscribe(tk)) for tk in (with_levels, first_view)]   # pages open on both
    lmp.record_feed_heartbeat({"ts": time.time() - 100, "schwab_socket_open": True, "universe": [with_levels]})
    try:
        d = json.loads(server.get_options_gamma_surface(with_levels).body)
        assert d["warming"] is False and d["reason"] == silent
        first = json.loads(server.get_options_gamma_surface(first_view).body)
        assert first["warming"] is False
        assert first["reason"] == silent + " — no terrain snapshot has been computed yet"
    finally:
        for tk, page in pages:
            push_changes.unsubscribe(tk, page)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(with_levels, None)
        lmp.record_feed_down()


def test_schwabs_refusal_of_a_subscription_is_recorded_with_its_own_code_and_message(tmp_path):
    """The daemon logs in to Schwab's streamer (stand-in) and subscribes what the console's list
    names; Schwab answers the option contracts' requests with code 19, REACHED_SYMBOL_LIMIT,
    and its message (2026-10-04, as sent: it kept up to 3000 and discarded the rest, naming
    none). The record carries Schwab's code and message, not our exception text. The symbols
    are not called refused: they are held -- so they are unsubscribed when no longer wanted,
    and no slot Schwab kept is left behind -- and Schwab's message is the service's state.
    Nothing unchanged is sent again; a new contract on the list is asked for."""
    schwab = _LocalSchwab(stream_refusal={"LEVELONE_OPTIONS": (_REFUSAL["schwab_code"], _REFUSAL["schwab_msg"])})
    client = sc.client_from_token_file_atomic(str(_token_file(tmp_path, 3600)), "k", "s", transport=schwab.transport)
    bus = MessageBus()
    subs = bus.subscribe("sub.", policy=LOG)
    daemon = capture.Daemon(bus, HealthRegistry(), universe=["TSLA"])
    contracts = _REFUSAL["first_symbols"]
    daemon.set_wanted({"LEVELONE_OPTIONS": contracts[:2]})
    sent: list = []
    state: dict = {}

    async def subscribe() -> None:
        await daemon.connect(client)
        try:
            await daemon.sync()
            sent.append(len(schwab.stream_requests))
            await daemon.sync()                                  # nothing changed: nothing sent
            sent.append(len(schwab.stream_requests))
            daemon.set_wanted({"LEVELONE_OPTIONS": contracts})   # the console's list changed
            await daemon.sync()
            sent.append(len(schwab.stream_requests))
            state.update(status=daemon.status(), held=set(daemon.held["LEVELONE_OPTIONS"]))
            daemon.set_wanted({"LEVELONE_OPTIONS": []})          # the screen moved on
            await daemon.sync()
        finally:
            await daemon.disconnect()
    try:
        asyncio.run(subscribe())
    finally:
        schwab.close()
    answers = []
    while not subs.queue.empty():
        answers.append(subs.queue.get_nowait()[1])
    options = [(a["command"], a["code"], a["reason"], a["symbols"]) for a in answers
               if a["service"] == "LEVELONE_OPTIONS"]
    assert options[:2] == [("SUBS", 19, _REFUSAL["schwab_msg"], contracts[:2]),
                           ("ADD", 19, _REFUSAL["schwab_msg"], contracts[2:])]
    assert options[2][:2] == ("UNSUBS", 0) and sorted(options[2][3]) == sorted(contracts), \
        "every contract held is unsubscribed when the screen moves on"
    assert all(a["code"] == 0 for a in answers if a["service"] != "LEVELONE_OPTIONS")
    assert sorted(a["service"] for a in answers if a["code"] == 0 and a["command"] != "UNSUBS") == \
        sorted(capture.UNIVERSE_SERVICES), "TSLA on every universe service, once"
    assert sent[1] == sent[0] and sent[2] == sent[1] + 1
    assert state["held"] == set(contracts)
    assert "LEVELONE_OPTIONS" not in state["status"]["refused"]
    limit = f"code 19: {_REFUSAL['schwab_msg']}"
    assert state["status"]["limits"] == {"LEVELONE_OPTIONS": limit}
    # on screen: tests/test_recorded_universe_v1.py
    # (test_schwabs_symbol_limit_is_what_the_heatmap_serves_for_its_contracts)


@pytest.mark.parametrize("ahead", ["another request's answer", "a frame that is not JSON"])
def test_only_schwabs_answer_to_this_request_decides_it(tmp_path, ahead):
    """Ahead of its answer to the NYSE_BOOK request, Schwab's streamer sends another request's
    answer (production, 2026-10-01 to 10-04: 1,068 such requests were recorded as refused) or a
    frame that is not JSON (schwab-py: "This often happens with unknown symbols"). Neither is
    this request's answer: the request's own answer (code 0) is recorded, nothing is refused,
    and the connection goes on. INDUCED CONDITION: the frames sent ahead (stand-in)."""
    frame = (json.dumps({"response": [{"service": "NYSE_BOOK", "requestid": "9999", "command": "SUBS",
                                       "SchwabClientCorrelId": "stand-in", "timestamp": 1,
                                       "content": {"code": 0, "msg": "stand-in: another request's answer"}}]})
             if ahead == "another request's answer" else "not json {")
    schwab = _LocalSchwab(stream_before={"NYSE_BOOK": [frame]})
    client = sc.client_from_token_file_atomic(str(_token_file(tmp_path, 3600)), "k", "s", transport=schwab.transport)
    bus = MessageBus()
    subs = bus.subscribe("sub.", policy=LOG)
    daemon = capture.Daemon(bus, HealthRegistry(), universe=["TSLA"])
    held: dict = {}

    async def subscribe() -> None:
        await daemon.connect(client)
        try:
            await daemon.sync()
            held.update(daemon.held)
        finally:
            await daemon.disconnect()
    try:
        asyncio.run(subscribe())
    finally:
        schwab.close()
    answers = []
    while not subs.queue.empty():
        answers.append(subs.queue.get_nowait()[1])
    assert sorted((a["service"], a["code"], a["reason"]) for a in answers) == sorted(
        (svc, 0, "stand-in: accepted") for svc in capture.UNIVERSE_SERVICES)
    assert daemon.status()["refused"] == {}
    assert all(held[svc] == {"TSLA"} for svc in capture.UNIVERSE_SERVICES)


def test_a_symbol_schwab_refused_is_asked_for_again_each_session():
    """Every ticker gets the same services, every session: a new market session
    (time_et.session_label) clears every refusal; the same session changes nothing. The code is
    Schwab's 22, FAILED_COMMAND_SUBS (Streamer Guide §1.4), as a refusal of one symbol."""
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), universe=["TSLA"])
    daemon.new_session("After-Hours")
    daemon.refused["NYSE_BOOK"] = {"TSLA": "code 22: stand-in"}
    daemon.new_session("After-Hours")
    assert daemon.refused["NYSE_BOOK"], "the same session: no new try"
    daemon.new_session("Closed")
    assert daemon.refused["NYSE_BOOK"] == {}


def test_a_lookup_schwab_never_answers_is_shown_and_asked_again_and_our_own_error_ends_the_daemon(
        tmp_path, caplog):
    """Schwab's host cannot be reached (the stand-in closed): the lookup of ZZZZ, a ticker a
    screen shows, has no answer, which is shown as its reason; a stored ticker (MU) stays in
    the universe; both are asked again on the next connection. An error of ours (no client at
    all) is not labeled as Schwab's: wired as capture.run wires the daemon's parts (supervise),
    it ends the daemon with exit 1 and its traceback in the log, and start_capture_daemon.bat
    starts it again. INDUCED CONDITION: the stand-in closed before the lookup."""
    schwab = _LocalSchwab()
    client = sc.client_from_token_file_atomic(str(_token_file(tmp_path, 3600)), "k", "s", transport=schwab.transport)
    schwab.close()
    daemon = capture.Daemon(MessageBus(), HealthRegistry())
    daemon.load([], ["MU"])
    daemon.ask(["ZZZZ"])

    async def look_up(schwab_client) -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(capture.run_joins(daemon, schwab_client, stop))
        end = time.monotonic() + 15
        while daemon.unanswered != {"MU", "ZZZZ"} and not task.done() and time.monotonic() < end:
            await asyncio.sleep(0.02)
        stop.set()
        await asyncio.wait_for(task, 10)
    asyncio.run(look_up(lambda: client))
    assert daemon.not_joined["ZZZZ"].startswith("Schwab's instrument lookup did not answer for ZZZZ: ")
    assert daemon.universe == ["MU"] and "MU" not in daemon.not_joined, "an unknown never removes"
    daemon.reconnected()
    assert sorted(daemon.joins.get_nowait() for _ in range(2)) == ["MU", "ZZZZ"], "asked again"
    fresh = capture.Daemon(MessageBus(), HealthRegistry())     # a daemon's one event loop
    fresh.ask(["ZZZZ"])

    async def wired() -> int:                                   # no client: our error, not Schwab's
        stop = asyncio.Event()
        return await asyncio.wait_for(capture.supervise(stop, [
            capture.run_joins(fresh, lambda: None, stop), stop.wait()]), 10)
    with caplog.at_level("ERROR", logger="capture"):
        assert asyncio.run(wired()) == 1
    failed = [r for r in caplog.records if r.getMessage() == "daemon: a part ended with an error; the daemon exits"]
    assert failed and failed[0].exc_info[0] is AttributeError


def test_a_request_schwab_never_answers_is_a_dead_connection(tmp_path):
    """Schwab's streamer never answers the NYSE_BOOK request: after REQUEST_TIMEOUT_SEC the
    connection is dead (ConnectionError; the daemon reconnects), and nothing is refused.
    INDUCED CONDITION: the stand-in streamer stays silent. Runs REQUEST_TIMEOUT_SEC (15 s)."""
    schwab = _LocalSchwab(stream_silent={"NYSE_BOOK"})
    client = sc.client_from_token_file_atomic(str(_token_file(tmp_path, 3600)), "k", "s", transport=schwab.transport)
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), universe=["TSLA"])

    async def subscribe() -> None:
        await daemon.connect(client)
        try:
            await daemon.sync()
        finally:
            await daemon.disconnect()
    try:
        with pytest.raises(ConnectionError, match="no answer to NYSE_BOOK SUBS"):
            asyncio.run(subscribe())
    finally:
        schwab.close()
    assert daemon.status()["refused"] == {}


def test_a_socket_that_dies_during_a_subscription_ends_the_connection_and_refuses_nothing(tmp_path):
    """Schwab's streamer closes the socket on the NYSE_BOOK request: the connection ends (the
    daemon reconnects), and no symbol is recorded as refused -- a dead socket is not Schwab
    refusing a symbol."""
    schwab = _LocalSchwab(stream_drop={"NYSE_BOOK"})
    client = sc.client_from_token_file_atomic(str(_token_file(tmp_path, 3600)), "k", "s", transport=schwab.transport)
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), universe=["TSLA"])

    async def subscribe() -> None:
        await daemon.connect(client)
        try:
            await daemon.sync()
        finally:
            await daemon.disconnect()
    try:
        with pytest.raises(ConnectionClosed):
            asyncio.run(subscribe())
    finally:
        schwab.close()
    assert daemon.status()["refused"] == {}


def test_a_dropped_connection_is_replaced_and_everything_wanted_is_resubscribed(tmp_path):
    """Schwab drops the streamer connection: the daemon logs in again on a new session that
    holds nothing, and subscribes the universe and the console's list again. At most one
    session is logged in at any instant."""
    schwab = _LocalSchwab()
    client = sc.client_from_token_file_atomic(str(_token_file(tmp_path, 3600)), "k", "s", transport=schwab.transport)
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), universe=["TSLA"])
    daemon.set_wanted({"NYSE_BOOK": ["SPY"]})

    async def until(cond) -> None:
        end = time.monotonic() + 15
        while not cond():
            assert time.monotonic() < end, "the daemon did not get there in 15 s"
            await asyncio.sleep(0.02)

    async def run() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(daemon.run(lambda: client, stop))
        try:
            await until(lambda: schwab.logins == 1 and "SPY" in daemon.held["NYSE_BOOK"])
            # no receive cap of ours: Schwab's frames are taken whole, whatever their size
            # (operator 2026-10-01: no caps); the websockets default refuses a frame over 1 MiB
            assert daemon.stream._socket.max_size is None
            schwab.drop()
            await until(lambda: schwab.logins == 2 and "SPY" in daemon.held["NYSE_BOOK"])
        finally:
            stop.set()
            await asyncio.wait_for(task, 10)
    try:
        asyncio.run(run())
    finally:
        schwab.close()
    subs = [(s, c, k) for s, c, k in schwab.stream_requests if c == "SUBS"]
    assert subs.count(("NYSE_BOOK", "SUBS", "SPY,TSLA")) == 2, subs
    assert schwab.most_live == 1


def test_d5_a_close_fetch_that_fails_is_tried_again_after_the_pause_until_it_lands():
    sweep, clock = _paced(["AAA", "BBB"], "2026-10-03 12:00")
    sat = clock["now"]
    assert _handed_out(sweep, sat, delivered=False) == ["AAA", "BBB"]
    assert sweep._paused_until == sat + FAILED_PAUSE_SEC
    assert _handed_out(sweep, sat + FAILED_PAUSE_SEC) == ["AAA", "BBB"]
    assert sweep._next(sat + 60) is None


def test_d5_while_closed_levels_as_of_the_close_stand_and_older_ones_are_absent_with_the_reason():
    """Levels are as of the chain they were computed from (computed_ts_utc). Ticker ZZCLOSED has
    no chain failure recorded."""
    sat, monday_early = _et("2026-10-03 12:00"), _et("2026-10-05 03:00")
    for now in (sat, monday_early):
        st = server.terrain_staleness(_et("2026-10-02 20:00") + 30, "ZZCLOSED", now=now)
        assert st["levels_stale"] is False and st["levels_stale_reason"] == "", st
        st = server.terrain_staleness(_et("2026-10-02 15:59"), "ZZCLOSED", now=now)
        assert st["levels_stale"] is True and st["levels_stale_reason"] == (
            "the market is closed and this ticker's close values have not been fetched"), st
        st = server.terrain_staleness(None, "ZZCLOSED", now=now)
        assert st["levels_stale"] is True and st["levels_age_sec"] is None    # absent, not zero
    st = server.terrain_staleness(_et("2026-10-01 10:00"), "ZZCLOSED", now=_et("2026-10-01 11:00"))
    assert st["levels_stale"] is True and "has not delivered this ticker" in st["levels_stale_reason"], \
        "in session, an hour-old chain is a gap"


#: Schwab's SPY and TSLA bars as the capture daemon recorded them, Mon 2026-09-29 and Tue 09-30
_DAEMON_0929 = daemon_bars("real_daemon_bars_spy_tsla_2026_09_29_30.json")
_PAIR = ("SPY", "TSLA")


def _newest(rows: list[dict], tk: str) -> list[dict]:
    """Schwab's newest receipt of each minute of `tk`, in time order."""
    out = {}
    for r in sorted(rows, key=lambda r: r["ts_recv"]):
        if r["symbol"] == tk:
            out[r["bar_start_ms"]] = r
    return [out[ms] for ms in sorted(out)]


def _rth(rows: list[dict], tk: str, day: str) -> list[dict]:
    at = [(datetime.fromtimestamp(r["bar_start_ms"] / 1000, ET), r) for r in _newest(rows, tk)]
    return [r for d, r in at if d.date().isoformat() == day and 570 <= d.hour * 60 + d.minute < 960]


def _forget(*tickers: str) -> None:
    """No bar in memory or published level of `tickers` is left behind."""
    for tk in tickers:
        server._bars.pop(tk, None)
        for key in [k for k in _MATERIALIZED_SNAPSHOTS if k[0] == tk]:
            del _MATERIALIZED_SNAPSHOTS[key]


def test_d5_while_closed_the_price_levels_are_the_last_sessions():
    """Schwab's SPY and TSLA bars of Mon 2026-09-29 and Tue 09-30 as the capture daemon recorded
    them, loaded at the console's start, valued at Wed 10-01 03:00 ET (Closed): the levels served
    are Tuesday's session's, its VWAP, value area and opening range, never an empty day's
    (2026-10-04: every ticker showed "no RTH volume" all weekend)."""
    closed = datetime(2026, 10, 1, 3, 0, tzinfo=ET)
    _forget(*_PAIR)
    record_daemon_bars(_DAEMON_0929)
    try:
        server._load_bars()
        for tk in _PAIR:
            server._publish_price_levels(tk, closed)
            body = server.levels_payload(tk, "1", closed)
            served = {r["id"]: r["price"] for r in body["levels"]}
            assert {"VWAP", "TODAY_POC", "TODAY_VAH", "TODAY_VAL", "ORB_HIGH", "ORB_LOW"} <= set(served), (tk, body["families_absent"])
            assert not {"vwap", "value_area", "opening_range"} & {f["family"] for f in body["families_absent"]}, tk
            assert body["snapshot_as_of_ts_utc"] == _newest(_DAEMON_0929, tk)[-1]["bar_start_ms"] / 1000, tk
            assert served["PDH"] == max(r["high"] for r in _rth(_DAEMON_0929, tk, "2026-09-29")), tk
    finally:
        forget_daemon_bars(_DAEMON_0929)
        _forget(*_PAIR)


def test_d6_a_bar_pushed_before_the_stored_bars_load_builds_levels_on_the_whole_history():
    """The console's start: the daemon pushes each ticker's current bar the moment the console
    connects, before the recorded bars are loaded. The bar writer loads them first, so the levels
    built from that bar stand on the whole history (2026-10-04: 35 tickers' levels were
    built from their one pushed bar, every prior-day level absent). Schwab's SPY and TSLA bars of
    2026-09-29/30 as the daemon recorded them; each ticker's newest receipt pushed, the rest loaded."""
    pushed = [_newest(_DAEMON_0929, tk)[-1] for tk in _PAIR]
    loaded = [r for r in _DAEMON_0929 if r not in pushed]
    _forget(*_PAIR)
    while not ofs.streamed_bars.empty():
        ofs.streamed_bars.get_nowait()
    record_daemon_bars(loaded)
    try:
        for r in pushed:
            ofs._ingest_pushed(f"bar1m.{r['symbol']}", bar_msg(
                symbol=r["symbol"], bar_start_ms=r["bar_start_ms"], open=r["open"], high=r["high"], low=r["low"],
                close=r["close"], volume=r["volume"], src=r["src"], ts_recv=r["ts_recv"], native=r["native"],
                schwab_ts=r["schwab_ts"]))
        writer = threading.Thread(target=server._bar_writer, daemon=True)
        writer.start()
        server.stop_bar_writer(writer)
        assert not writer.is_alive()
        for r in pushed:
            tk = r["symbol"]
            snap = server.canonical_price_level_snapshot(tk, now_et())
            tuesday = _rth(_DAEMON_0929, tk, "2026-09-30")
            assert snap.as_of_ts_utc == r["bar_start_ms"] / 1000, tk
            assert (snap.levels["PDL"].price, snap.levels["PDH"].price) == (
                min(b["low"] for b in tuesday), max(b["high"] for b in tuesday)), tk
            assert snap.degraded == [], tk
    finally:
        forget_daemon_bars(loaded)
        _forget(*_PAIR)


#: price_bars_1m as production holds it: the console's old bar store, which its quote accumulator
#: and price-history re-seeds wrote before 2026-09-26 (no code writes or reads it now)
_OLD_STORE_DDL = ("CREATE TABLE IF NOT EXISTS price_bars_1m (ticker TEXT NOT NULL, bar_start_ts_utc REAL NOT NULL, "
                  "bar_end_ts_utc REAL NOT NULL, open REAL, high REAL, low REAL, close REAL NOT NULL, volume REAL, "
                  "source TEXT NOT NULL DEFAULT 'schwab_1m_accumulator_sqlite', PRIMARY KEY (ticker, bar_start_ts_utc))")


def test_d6_only_schwabs_recorded_bars_reach_the_chart_and_the_levels_never_the_old_store():
    """2026-10-04 audit: the console's old bar store holds bars our quote accumulator built (one
    sampled price a minute, no volume) and history re-seeds, and the console loaded them at its
    start. Real data from production for SPY and TSLA on 2026-09-24: the old store's rows (its
    built rows included) beside the daemon's record of Schwab's bars. With both present, every
    bar the chart and the levels read is Schwab's recorded bar; a minute only the old store holds
    is absent."""
    fx = json.loads((FX / "real_console_store_vs_daemon_spy_tsla_2026_09_24.json").read_text(encoding="utf-8"))
    store, daemon = fx["console_store"], fx["daemon"]
    con = sqlite3.connect(server.get_db().db_path)
    try:
        con.execute(_OLD_STORE_DDL)
        con.executemany("INSERT OR REPLACE INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)",
                        [(r["ticker"], r["bar_start_ts_utc"], r["bar_end_ts_utc"], r["open"], r["high"], r["low"],
                          r["close"], r["volume"], r["source"]) for r in store])
        con.commit()
    finally:
        con.close()
    _forget(*_PAIR)
    record_daemon_bars(daemon)
    try:
        server._load_bars()
        for tk in _PAIR:
            recorded = {r["bar_start_ms"] / 1000: (r["open"], r["high"], r["low"], r["close"], r["volume"])
                        for r in _newest(daemon, tk)}
            old = {r["bar_start_ts_utc"]: (r["open"], r["high"], r["low"], r["close"], r["volume"])
                   for r in store if r["ticker"] == tk}
            differs = [t for t in old if t in recorded and old[t] != recorded[t]]
            old_only = [t for t in old if t not in recorded]
            assert differs and old_only, (tk, "the captured day must hold built rows and old-store-only minutes")
            served = {b["t"]: (b["o"], b["h"], b["l"], b["c"], b["v"])
                      for b in _chart_bars(tk) if b["t"] in recorded or b["t"] in old}
            levels_input = {b["timestamp"] / 1000: (b["open"], b["high"], b["low"], b["close"], b["volume"])
                            for b in server._liquidity_1m_bars(tk) if b["timestamp"] / 1000 in recorded or b["timestamp"] / 1000 in old}
            assert served == recorded == levels_input, tk
            assert not set(old_only) & set(served), tk
    finally:
        forget_daemon_bars(daemon)
        _forget(*_PAIR)
        con = sqlite3.connect(server.get_db().db_path)
        con.execute("DROP TABLE IF EXISTS price_bars_1m")
        con.commit()
        con.close()


def _chart_bars(tk: str) -> list[dict]:
    """The bars the chart reads: /api/bars1m through the app."""
    return TestClient(server.app).get(f"/api/bars1m?ticker={tk}&limit=12000&tf=1").json()["bars"]


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


def test_every_schwab_error_is_logged_as_sent_without_tokens(tmp_path, caplog):
    """A Schwab error answer reaches the log with its status, body and headers, through the
    client the daemon and the console build. Stand-ins: a local server answering as Schwab
    does (the error body's shape is Schwab's documented {"errors": [...]}), and a token file."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    import schwab_client as sc

    class Schwab(BaseHTTPRequestHandler):
        def do_GET(self):
            body = (b'{"access_token": "never-logged"}' if "oauth" in self.path else
                    b'{"errors": [{"id": "x1", "status": "403", "title": "Forbidden"}]}')
            self.send_response(403)
            self.send_header("Schwab-Client-CorrelId", "corr-123")
            self.send_header("Set-Cookie", "session=never-logged")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Schwab)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tok = tmp_path / "schwab_token.json"
    tok.write_text(json.dumps({"creation_timestamp": int(time.time()), "token": {
        "access_token": "secret-access", "refresh_token": "secret-refresh", "token_type": "Bearer",
        "expires_in": 3600, "expires_at": int(time.time()) + 3600}}))
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        client = sc.client_from_token_file_atomic(str(tok), "k", "s")
        with caplog.at_level("WARNING", logger="schwab_client"):
            for _ in range(3):
                client.session.get(f"{base}/marketdata/v1/chains?symbol=SPY")
            client.session.get(f"{base}/trader/v1/accounts/HASH123/orders")
            client.session.get(f"{base}/v1/oauth/token")
    finally:
        srv.shutdown()
    lines = [r.getMessage() for r in caplog.records]
    chain = [m for m in lines if "/marketdata/v1/chains?symbol=SPY" in m]
    assert len(chain) == 1, "one line a minute per status and path"
    assert "-> 403" in chain[0] and '"title": "Forbidden"' in chain[0]
    assert "corr-123" in chain[0]
    assert any("/trader/v1/accounts/(account)/orders" in m for m in lines)
    assert any("/v1/oauth/token -> 403" in m and "not logged" in m for m in lines)
    text = "\n".join(lines)
    for secret in ("secret-access", "secret-refresh", "never-logged", "HASH123", "Bearer"):
        assert secret not in text


# ── The daemon's one Schwab client, against a local stand-in for Schwab's host ───────────────
# (tests/local_schwab.py: its real data and its stand-ins are named there)

def test_twenty_requests_at_a_refresh_send_one_refresh_and_all_carry_the_new_token(tmp_path):
    """The token inside its refresh window (100 s left; the client refreshes inside 300 s) and
    20 requests at once: one refresh reaches the token endpoint, and every request carries the
    token it returned. Live on 2026-10-03 one renewal went out as 8 POSTs in one second. INDUCED
    CONDITION: the token endpoint's answer is the stand-in."""
    schwab = _LocalSchwab()
    try:
        client = sc.client_from_token_file_atomic(str(_token_file(tmp_path, 100)), "k", "s",
                                                  transport=schwab.transport)
        symbols = sorted(_SPY_1120_QUOTES)[:5]
        with ThreadPoolExecutor(max_workers=20) as pool:
            codes = list(pool.map(lambda _: client.get_quotes(symbols).status_code, range(20)))
    finally:
        schwab.close()
    assert codes == [200] * 20
    assert len(schwab.posts()) == 1, f"{len(schwab.posts())} refreshes for one renewal"
    assert {a for _t, m, _p, a in schwab.requests if m == "GET"} == {"Bearer new-access"}


def test_the_daemon_builds_one_schwab_client_and_a_refused_refresh_never_rebuilds_it(tmp_path):
    """The stream and every chain worker ask one holder (capture.one_schwab_client). Schwab's
    edge refuses the token refresh with its 403 page (as at 19:53:55 on 2026-10-03): the client
    is never rebuilt, and after the first failures the sweep sends one refresh per
    FAILED_PAUSE_SEC (the probe), not one per worker. Runs about 6.5 s."""
    schwab = _LocalSchwab(token_answer="akamai")
    built = []

    def build():
        built.append(1)
        client = sc.client_from_token_file_atomic(str(_token_file(tmp_path, 100)), "k", "s",
                                                  transport=schwab.transport)
        return sc.SchwabClientState(ok=True, message="", client=client)

    schwab_client = capture.one_schwab_client(build)
    assert schwab_client() is schwab_client(), "the stream and the chains are handed one client"
    sweep = ChainSweep(tmp_path / "ed_console.db", ["AAA", "BBB", "CCC", "DDD", "EEE"],
                       lambda topic, msg: None)
    halt = threading.Event()
    workers = [threading.Thread(target=sweep.work, args=(schwab_client, halt), daemon=True)
               for _ in range(4)]
    try:
        for w in workers:
            w.start()
        halt.wait(FAILED_PAUSE_SEC + 1.5)
    finally:
        halt.set()
        for w in workers:
            w.join(10)
        schwab.close()
    posts = schwab.posts()
    assert built == [1], f"the client was built {len(built)} times"
    assert posts, "the refresh was never tried"
    after_first = [t for t in posts if t - posts[0] > 1.0]
    assert len(after_first) == 1, f"{len(after_first)} refreshes after the first failures, not one probe"


def test_a_403_from_schwabs_edge_pauses_the_sweep_then_one_chain_at_a_time_until_one_lands(tmp_path):
    """Schwab's edge answers the captured 403 page: no chain request for FAILED_PAUSE_SEC, then
    one chain alone; once it lands the sweep goes on. The clock is 2026-10-01 08:00 ET
    (pre-market, outside every capture window, so nothing is written)."""
    schwab = _LocalSchwab(refuse=True)
    published = []
    now = 1790856000.0                                    # 2026-10-01 08:00 ET
    sweep = ChainSweep(tmp_path / "ed_console.db", ["AAA", "BBB", "CCC", "DDD"],
                       lambda topic, msg: published.append(msg), clock=lambda: now)
    client = Client("k", httpx.Client(transport=schwab.transport), enforce_enums=False)   # as the daemon's
    try:
        assert sweep._next(now) == "AAA"
        sweep.fetch_one(client, "AAA")                    # the 403 page
        sweep._fetching.discard("AAA")
        assert sweep._paused_until == now + FAILED_PAUSE_SEC, "a 403 pauses every chain request"
        assert "HTTP 403" in published[-1]["failed"]
        assert sweep._next(now + FAILED_PAUSE_SEC) == "BBB"   # the probe
        assert sweep._next(now + FAILED_PAUSE_SEC) is None, "nothing else while the probe is out"
        schwab.refuse = False
        sweep.fetch_one(client, "BBB")                    # the probe lands
        sweep._fetching.discard("BBB")
        assert [sweep._next(now + FAILED_PAUSE_SEC), sweep._next(now + FAILED_PAUSE_SEC)] == ["CCC", "DDD"], \
            "two at once again"
    finally:
        schwab.close()


def test_the_chain_sweeps_threads_never_take_the_threads_the_daemons_other_work_needs(tmp_path):
    """The chain sweep's CHAIN_WORKERS threads are its own. CI's 2-core runner gives the event
    loop's shared pool min(32, 2 + 4) = 6 threads, fewer than the 8 workers: the workers held
    every one, and the stored-ticker read and the instrument lookups (asyncio.to_thread) waited
    behind them -- on 2026-10-05 the first lookup went out 40 s late. With the sweep running, the
    daemon's other off-loop work still runs at once. INDUCED CONDITION: the loop's shared pool
    set to 2 threads."""
    from concurrent.futures import ThreadPoolExecutor as Pool
    daemon = capture.Daemon(MessageBus(), HealthRegistry())

    async def go() -> str:
        asyncio.get_running_loop().set_default_executor(Pool(max_workers=2))
        stop = asyncio.Event()
        task = asyncio.create_task(capture.run_chains(daemon, tmp_path / "ed_console.db", lambda: None, stop))
        await asyncio.sleep(0.2)                                 # the workers are up, idle
        try:
            return await asyncio.wait_for(asyncio.to_thread(lambda: "ran"), 5)
        finally:
            stop.set()
            await asyncio.wait_for(task, 10)
    assert asyncio.run(go()) == "ran"


def test_d3_the_daemons_chain_is_the_current_record_whole_once_all_its_parts_are_in(tmp_path):
    """The daemon's chain sweep (capture.run_chains) fetches the universe's MRVL chain on the
    daemon's client and publishes it in parts on its bus; the chain becomes MRVL's current
    record only once every part is in, and a console that connects later starts with that whole
    chain, every part in order -- never a partial one. Real data: Schwab's MRVL strike_range=ALL
    chain of 2026-09-25 (2,432 contracts, five parts). Stand-in, named: no quote of those
    contracts was captured, so Schwab's quotes answer holds none of them."""
    full = json.loads((FX / "real_mrvl_full_chain_vs_strike_window.json").read_text(encoding="utf-8"))
    schwab = _LocalSchwab(chains={"MRVL": {"symbol": "MRVL", **full["full"]}})
    client = Client("k", httpx.Client(transport=schwab.transport), enforce_enums=False)
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), universe=["MRVL"])
    sqlite3.connect(tmp_path / "ed_console.db").close()

    async def go():
        stop = asyncio.Event()
        sub = daemon.bus.subscribe("chain.", policy=LATEST)
        task = asyncio.create_task(capture.run_chains(daemon, tmp_path / "ed_console.db", lambda: client, stop))
        topic, record = await asyncio.wait_for(sub.get(), timeout=30)
        stop.set()
        await asyncio.wait_for(task, timeout=30)
        late = daemon.bus.subscribe("chain.", policy=LATEST)
        return topic, record, await asyncio.wait_for(late.get(), timeout=5)
    try:
        topic, record, (late_topic, late_record) = asyncio.run(go())
    finally:
        schwab.close()
    assert topic == late_topic == "chain.MRVL"
    assert [m["part"] for m in record] == list(range(record[0]["parts"])) and len(record) > 1
    assert [m["part"] for m in late_record] == list(range(late_record[0]["parts"]))
    ofs._chain_parts.clear()
    (tk, contracts, _ts, reason), = [o for m in late_record
                                     for o in ofs.assemble_chain_part(json.loads(m["frame"])["msg"])]
    assert tk == "MRVL" and reason is None and len(contracts) == full["n_full"]
