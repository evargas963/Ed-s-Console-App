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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from schwab.client import Client
from websockets.asyncio.client import connect

import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import schwab_client as sc
import server
from app.market_data.schwab.streaming import capture, live_push
from calibration.complete_chain_capture import (CAPTURE_BASIS, FAILED_PAUSE_SEC, ChainSweep, chain_messages,
                                                persist_complete_chain_capture)
from liquidity_value_engine import _MATERIALIZED_SNAPSHOTS
from stream_spine import LOG, CaptureWriter, HealthRegistry, MessageBus, bar_msg
from terrain_engine import compute_terrain
from tests.feed_live_helper import (daemon_bars, forget_daemon_bars, mark_feed_down, mark_feed_live,
                                    publish_daemon_rows, record_daemon_bars)
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


def _paced(board: "list[str]", at: str) -> "tuple[ChainSweep, dict]":
    clock = {"now": _et(at)}
    return ChainSweep("unused.db", board, lambda topic, msg: None, clock=lambda: clock["now"]), clock


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
    sweep.set_active("OFF")                              # on screen, off the board
    assert _handed_out(sweep, clock["now"]) == ["OFF", "AAA", "BBB"]
    assert _handed_out(sweep, clock["now"] + 1) == ["OFF", "AAA", "BBB"], "and again, without end"


def test_d5_once_closed_every_board_ticker_is_fetched_once_then_nothing_until_the_next_session():
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
def test_d5_a_daemon_started_while_closed_fetches_the_close_values_once_and_no_ticker_put_on_screen(at):
    """A ticker put on screen while Closed is not fetched, whether its close values were fetched
    (on the board) or not (off it): the close values stand, and none is made up."""
    sweep, clock = _paced(["AAA", "BBB"], at)
    assert _handed_out(sweep, clock["now"]) == ["AAA", "BBB"]
    sweep.set_active("AAA")
    assert sweep._next(clock["now"] + 60) is None
    sweep.set_active("OFF")
    assert sweep._next(clock["now"] + 120) is None


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
    built from that bar stand on the whole history (2026-10-04: 35 board tickers' levels were
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
# Real data: the captured SPY 2026-11-20 chain and Schwab's quotes for it, and Schwab's edge's
# 403 page (Akamai) as it answered on 2026-10-03. Stand-ins, named: the local server playing
# Schwab's host, and the token endpoint's answer to a refresh (no real one is kept: it holds the
# tokens) in the shape Schwab documents. A result that rests on the stand-in token answer is an
# induced test condition, not observed Schwab behavior.

_SPY_1120 = json.loads((FX / "real_spy_2026_11_20_chain_and_quotes.json").read_text(encoding="utf-8"))
_SPY_1120_QUOTES = {s: e for q in _SPY_1120["quotes"] for s, e in q["reply"].items()}
_AKAMAI_403 = json.loads((FX / "real_schwab_akamai_403_2026_10_03.json").read_text(encoding="utf-8"))
_REFRESHED = {"access_token": "new-access", "refresh_token": "r", "token_type": "Bearer",
              "expires_in": 1800, "scope": "api", "id_token": "i"}


def _spy_chain_payload() -> dict:
    payload = {"symbol": "SPY", "underlyingPrice": _SPY_1120["spot"], "callExpDateMap": {},
               "putExpDateMap": {}}
    for ct in _SPY_1120["chain"]:
        side = "callExpDateMap" if ct["putCall"] == "CALL" else "putExpDateMap"
        payload[side].setdefault(f"{ct['expirationDate'][:10]}:{ct['daysToExpiration']}", {}) \
            .setdefault(str(ct["strikePrice"]), []).append(ct)
    return payload


class _ToLocal(httpx.BaseTransport):
    """Every request the client sends, delivered to the local server instead of Schwab's host."""

    def __init__(self, port: int):
        self.port, self.inner = port, httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request.url = request.url.copy_with(scheme="http", host="127.0.0.1", port=self.port)
        return self.inner.handle_request(request)


class _LocalSchwab:
    """Schwab's host, played by a local server. The token endpoint answers `token_answer`
    ("refreshed": _REFRESHED; "akamai": the captured 403 page); chains and quotes answer `chain`
    and `quotes` (the captured SPY chain and its quotes unless given), or the captured 403 page
    while `refuse`. Every request is recorded: (time, method, path, Authorization)."""

    def __init__(self, token_answer: str = "refreshed", refuse: bool = False,
                 chain: "dict | None" = None, quotes: "dict | None" = None):
        self.token_answer, self.refuse = token_answer, refuse
        chain = _spy_chain_payload() if chain is None else chain
        quotes = _SPY_1120_QUOTES if quotes is None else quotes
        self.requests: list = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status, content_type, body: bytes):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                if status == 403:
                    self.send_header("Server", _AKAMAI_403["headers"]["server"])
                self.end_headers()
                self.wfile.write(body)

            def _akamai(self):
                self._send(403, "text/html", _AKAMAI_403["body"].encode())

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.requests.append((time.monotonic(), "POST", urlparse(self.path).path, None))
                if outer.token_answer == "akamai":
                    return self._akamai()
                self._send(200, "application/json", json.dumps(_REFRESHED).encode())

            def do_GET(self):
                url = urlparse(self.path)
                outer.requests.append((time.monotonic(), "GET", url.path, self.headers.get("Authorization")))
                if outer.refuse:
                    return self._akamai()
                if url.path == "/marketdata/v1/chains":
                    return self._send(200, "application/json", json.dumps(chain).encode())
                symbols = parse_qs(url.query).get("symbols", [""])[0].split(",")
                reply = {s: quotes[s] for s in symbols if s in quotes}
                self._send(200, "application/json", json.dumps(reply).encode())

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.transport = _ToLocal(self.server.server_address[1])

    def posts(self) -> "list[float]":
        return [t for t, method, path, _a in self.requests if method == "POST" and path == "/v1/oauth/token"]

    def close(self) -> None:
        self.server.shutdown()


def _token_file(tmp_path, expires_in_sec: float) -> Path:
    """A token file in schwab-py's shape (stand-in for schwab_token.json)."""
    tok = tmp_path / "schwab_token.json"
    tok.write_text(json.dumps({"creation_timestamp": int(time.time()), "token": {
        "access_token": "old-access", "refresh_token": "r", "token_type": "Bearer",
        "expires_in": 1800, "expires_at": int(time.time() + expires_in_sec)}}))
    return tok


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


# ── The chain, from the daemon's sweep to the console's levels, valued at Schwab's time ──────
# Real data: MRVL's full chain (strike_range=ALL) and its 20-strike window, captured from Schwab
# at the same moment on 2026-09-25 15:47 ET (tests/fixtures/real_mrvl_full_chain_vs_strike_window
# .json). Stand-ins, named: the local server playing Schwab's host; its quotes answer carries each
# contract's Greeks as the captured chain sent them (no quotes were captured with this chain); the
# chain's underlying last stands in for the LAST_PRICE the stream sent; the daemon's push socket
# and the console's feed loop are replaced by handing each bus message's frame to the console's
# chain assembly and chain callback, as the feed loop does.

_MRVL = json.loads((FX / "real_mrvl_full_chain_vs_strike_window.json").read_text(encoding="utf-8"))
_LEVEL_KEYS = ("call_wall", "put_wall", "gamma_flip", "absolute_gamma_strike", "net_gex_peak",
               "max_pain", "expiries", "contracts_used")


def _forget_chain(tk: str) -> None:
    """The console's and the price plane's memory of `tk` that these tests created, removed."""
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    with server._chains_waiting_lock:
        server._chains_delivered.discard(tk)
    server._terrain_refresh_last_error.pop(tk, None)
    with lmp._lock:
        lmp._by_ticker.pop(tk, None)
        lmp._fields_by_ticker.pop(tk, None)
    ofs._price_rows.pop(tk, None)


def _greeks_as_the_chain_sent(payload: dict) -> dict:
    return {c["symbol"]: {"quote": {f: c.get(f) for f in sc.GREEK_FIELDS}}
            for c in sc.flatten_chain_contracts(payload)}


def _to_console(topic: str, msg: dict) -> None:
    for done in ofs.assemble_chain_part(json.loads(msg["frame"])["msg"]):
        server._on_chain(*done)


def test_the_daemons_full_chain_is_priced_by_the_console_at_schwabs_quote_time(tmp_path):
    """The daemon's one fetcher asks Schwab for MRVL's whole chain; the console prices what
    reaches it at the time Schwab says the chain describes, its newest quoteTimeInLong
    (2026-09-25 15:46:58 ET), never the console's clock: valued at today's clock, the expiries
    that have passed since drop out of the gamma profile and the flip moves (230.53 -> 230.30
    on 2026-10-05). The levels are the full chain's, not the window's."""
    tk = server.ticker_storage_key("MRVL")
    full = sc.flatten_chain_contracts(_MRVL["full"])
    window = sc.flatten_chain_contracts(_MRVL["window"])
    quoted = datetime.fromtimestamp(max(c["quoteTimeInLong"] for c in full) / 1000, ET)
    spot = float(_MRVL["full"]["underlying"]["last"])
    sqlite3.connect(tmp_path / "ed_console.db").close()           # the daemon's database exists
    schwab = _LocalSchwab(chain=_MRVL["full"], quotes=_greeks_as_the_chain_sent(_MRVL["full"]))
    sweep = ChainSweep(tmp_path / "ed_console.db", [tk], _to_console, clock=lambda: _MRVL["captured_utc"])
    client = Client("k", httpx.Client(transport=schwab.transport), enforce_enums=False)   # as the daemon's
    lmp.record_from_level_one_equity(tk, {"LAST_PRICE": spot,
                                          "TRADE_TIME_MILLIS": int(_MRVL["captured_utc"] * 1000)},
                                     received_ts=time.time())
    try:
        mark_feed_live(tk)
        publish_daemon_rows(tk)
        assert sweep.fetch_one(client, tk)
        server._chain_pricing.submit(lambda: None).result(timeout=120)      # the chain is priced
        delivered = dict(server.terrain_cache_get(tk) or {})
        server._chain_pricing.submit(server._publish_levels, tk).result(timeout=120)   # a tick: the kept chain
        repriced = dict(server.terrain_cache_get(tk) or {})
    finally:
        schwab.close()
        mark_feed_down()
        _forget_chain(tk)
    assert [p for _t, _m, p, _a in schwab.requests if p == "/marketdata/v1/chains"] == \
        ["/marketdata/v1/chains"], "one request for the ticker's whole chain"
    expected = compute_terrain(tk, full, spot, now=quoted).to_dict()
    assert expected["gamma_flip"] is not None, "the full chain has a flip for MRVL"
    in_window = compute_terrain(tk, window, spot, now=quoted).to_dict()
    for published in (delivered, repriced):
        got = {k: published.get(k) for k in _LEVEL_KEYS}
        assert published.get("spot") == spot
        assert got == {k: expected[k] for k in _LEVEL_KEYS}, (got, quoted)
        levels = [k for k in _LEVEL_KEYS if k != "contracts_used"]   # the count differs by construction
        assert {k: got[k] for k in levels} != {k: in_window[k] for k in levels}, \
            "the full chain's levels, not the window's"


def test_a_chain_without_schwabs_quote_time_is_not_priced_and_the_screen_says_why():
    """A chain that carries no quoteTimeInLong has no time Schwab says it describes: it is not
    priced at the fetch time or the clock; /api/terrain shows no levels, with the reason. Real
    data with the induced condition named: MRVL's captured full chain with quoteTimeInLong removed
    from every contract (never seen: 0 of 555,759 stored contracts lacked it, 2026-10-05)."""
    tk = server.ticker_storage_key("MRVL")
    unquoted = [{k: v for k, v in c.items() if k != "quoteTimeInLong"}
                for c in sc.flatten_chain_contracts(_MRVL["full"])]
    try:
        server._on_chain(tk, unquoted, _MRVL["captured_utc"])
        server._chain_pricing.submit(lambda: None).result(timeout=120)      # the pricing thread ran
        published = server.terrain_cache_get(tk)
        served = server.get_terrain(ticker=tk)
    finally:
        _forget_chain(tk)
    assert published is None, "nothing was published from a chain without its time"
    assert served["gamma_flip"] is None and served["call_wall"] is None and served["put_wall"] is None
    assert "no Schwab quote time (quoteTimeInLong)" in served["error"], served["error"]
    assert served["levels_stale"] is True
    assert "no Schwab quote time (quoteTimeInLong)" in served["levels_stale_reason"]


#: MRVL's full chain (newest quoteTimeInLong 2026-09-25 15:46:58 ET) stored as the daemon stores a
#: capture, at the close capture slot 2026-09-25 16:15 ET: the stored time is the induced
#: condition (the single names' 16:15 captures are dated 15-16 min after their newest quote).
#: Valued at the stored time, the 2026-09-25 expiry (20:00 UTC, 16:00 ET) drops out of the flip's
#: gamma profile and the flip is 229.21; at Schwab's quote time it is 230.53. Stand-in, named: the fixture has no
#: `underlyingPrice` (what the daemon stores as the capture's spot), so the chain's underlying
#: `last` stands in for it.
_MRVL_TAKEN = datetime(2026, 9, 25, 16, 15, tzinfo=ET).timestamp()


def test_a_stored_capture_is_priced_with_its_own_price_dated_at_its_time_and_valued_at_schwabs():
    """DATA_FLOW decision 7, the console's start: a board ticker's newest full chain capture is
    priced once, with Schwab's underlying price from that capture, dated at the capture's time and
    valued at the time Schwab says the chain describes (its newest quoteTimeInLong). Rows the
    console wrote before the daemon captured (not CAPTURE_BASIS) are never loaded."""
    tk = server.ticker_storage_key("MRVL")
    chain, spot = sc.flatten_chain_contracts(_MRVL["full"]), float(_MRVL["full"]["underlying"]["last"])
    quoted = datetime.fromtimestamp(max(c["quoteTimeInLong"] for c in chain) / 1000, ET)
    by_expiry: dict = {}
    for c in chain:
        by_expiry.setdefault(c["expirationDate"][:10], []).append(c)
    db = server.get_db().db_path
    for expiry, contracts in by_expiry.items():
        persist_complete_chain_capture(db, ticker=tk, expiry=expiry, contracts=contracts, spot=spot,
                                       completeness_basis=CAPTURE_BASIS, ts_utc=_MRVL_TAKEN)
    persist_complete_chain_capture(db, ticker=tk, expiry=next(iter(by_expiry)), contracts=chain[:2],
                                   spot=1.0, completeness_basis="strike_range=ALL", ts_utc=_MRVL_TAKEN + 60)
    try:
        assert server._load_stored_levels([tk]) == 1
        server._chain_pricing.submit(lambda: None).result(timeout=120)      # priced on the pricing thread
        loaded = dict(server.terrain_cache_get(tk) or {})
    finally:
        con = sqlite3.connect(db)
        con.execute("DELETE FROM complete_chain_captures WHERE ticker=?", (tk,))
        con.commit()
        con.close()
        _forget_chain(tk)
    assert loaded["computed_ts_utc"] == _MRVL_TAKEN
    assert loaded["spot"] == spot and loaded["spot_source"] == server.SPOT_SOURCE_CAPTURE
    expected = compute_terrain(tk, chain, spot, now=quoted).to_dict()
    assert expected["gamma_flip"] is not None, "the capture must price"
    assert {k: loaded[k] for k in _LEVEL_KEYS} == {k: expected[k] for k in _LEVEL_KEYS}
    # the induced condition: at the stored time the 09-25 expiry, settled at 16:00, drops out of
    # the flip's gamma profile
    at_stored = datetime.fromtimestamp(_MRVL_TAKEN, ET)
    unsettled = [c for c in chain if not c["expirationDate"].startswith("2026-09-25")]
    assert compute_terrain(tk, chain, spot, now=at_stored).gamma_flip == \
        compute_terrain(tk, unsettled, spot, now=at_stored).gamma_flip != expected["gamma_flip"]
