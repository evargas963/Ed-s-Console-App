"""Option messages, Schwab to the console, through the real code: the daemon's push socket
(live_push.serve_live_push) and the console's side of it (streaming.serve_push), the console's
state (app.options.order_flow.state), and the daemon's status (live_market_plane).

Real data: every message received 2026-10-05 14:00:00-14:00:03 CT, as Schwab sent them
(tests/fixtures/real_stream_mix_2026_10_05_1400ct.json: 7,420 LEVELONE_OPTIONS, 152
LEVELONE_EQUITIES and 4 OPTIONS_BOOK messages). STAND-IN (named): the daemon's status, holding a
contract or not.
"""
from __future__ import annotations

import asyncio
import json
import socket
import time
from pathlib import Path

import app.options.order_flow.state as ofls
import live_market_plane as lmp
from app.market_data.schwab.streaming import live_push
from app.options.order_flow import streaming as ofs
from stream_spine import MessageBus, book_msg, options_quote_msg, quote_msg

_MIX = json.loads((Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json")
                  .read_text(encoding="utf-8"))["messages"]
BOOK_CONTRACT = "SPY   261005C00774000"


def _message(m: dict) -> "tuple[str, dict]":
    """One fixture row as the daemon publishes it on its bus."""
    sym, svc, ts = m["item"]["key"], m["service"], m["ts_recv"]
    if svc == "LEVELONE_OPTIONS":
        return f"optquote.{sym}", options_quote_msg(symbol=sym, content=m["item"], src="schwab_options_l1", ts_recv=ts)
    if svc == "LEVELONE_EQUITIES":
        return f"quote.{sym}", quote_msg(symbol=sym, src="schwab_l1", ts_recv=ts, native=m["item"])
    return f"book.{sym}", book_msg(symbol=sym, service=svc, content=m["item"], src="schwab_book", ts_recv=ts)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_every_option_and_equity_message_on_the_one_push_reaches_the_console():
    """The daemon publishes each message Schwab sent; the console's one connection receives them
    and keeps each contract's newest values as sent: every option contract's last BID_PRICE and
    ASK_PRICE (its top of book), and the option book Schwab sent last."""
    from websockets.asyncio.client import connect
    rows = [m for m in _MIX if m["service"] in ("LEVELONE_OPTIONS", "LEVELONE_EQUITIES", "OPTIONS_BOOK")]
    want = {}
    for m in rows:
        if m["service"] == "LEVELONE_OPTIONS":
            top = want.setdefault(m["item"]["key"], {})
            top.update({name: m["item"][f] for f, name in (("BID_PRICE", "bid"), ("ASK_PRICE", "ask")) if f in m["item"]})
    want = {s: t for s, t in want.items() if t}
    newest_book = [m["item"] for m in rows if m["service"] == "OPTIONS_BOOK"][-1]

    def top(sym):
        t = ofls.option_top(sym) or {}
        return {k: t[k] for k in want[sym] if k in t}

    async def go():
        bus, stop, port = MessageBus(), asyncio.Event(), _free_port()
        stats: dict = {}
        pushing = asyncio.create_task(live_push.serve_live_push(bus, stop, port=port, stats=stats))
        while stats.get("listening") is None:
            await asyncio.sleep(0.02)
        ws = await connect(f"ws://127.0.0.1:{port}", max_size=None)
        console = asyncio.create_task(ofs.serve_push(ws))
        for m in rows:
            bus.publish(*_message(m))
        deadline = time.monotonic() + 30
        while any(top(s) != t for s, t in want.items()) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        await ws.close()
        await asyncio.wait_for(console, 5)
        stop.set()
        await pushing

    ofls.clear_all_live_state()
    try:
        asyncio.run(go())
        tops = {s: top(s) for s in want}
        book = next(i for i in reversed(ofls.get_content_for_symbol(BOOK_CONTRACT)) if "BIDS" in i)
    finally:
        ofls.clear_all_live_state()
    assert want and tops == want
    assert book["BIDS"] == newest_book["BIDS"] and book["ASKS"] == newest_book["ASKS"]


def test_a_contract_the_daemon_stops_streaming_no_longer_shows_as_current():
    """The option rule moves off a contract (the daemon's status no longer holds it): the
    console forgets its live values, so no screen shows its last message as current."""
    m = next(m for m in _MIX if m["service"] == "LEVELONE_OPTIONS" and "BID_PRICE" in m["item"])
    sym = m["item"]["key"]
    ofls.clear_all_live_state()
    try:
        lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True,
                                   "held": {"LEVELONE_OPTIONS": [sym], "OPTIONS_BOOK": []}})
        ofs._drop_released_options()
        ofs._ingest_pushed(*_message(m))
        held = ofls.option_top(sym)
        lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True,
                                   "held": {"LEVELONE_OPTIONS": [], "OPTIONS_BOOK": []}})
        ofs._drop_released_options()
        released = ofls.option_top(sym)
    finally:
        ofls.clear_all_live_state()
        lmp.record_feed_down()
    assert held["bid"] == m["item"]["BID_PRICE"]
    assert released is None
