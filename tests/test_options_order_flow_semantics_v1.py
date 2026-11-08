"""Option messages, Schwab to the console, through the real code: the daemon's bus
(capture.Daemon) and the console's reader of it in the same program
(streaming.start_order_flow_stream), the console's state (app.options.order_flow.state), and the
daemon's status (live_market_plane).

Real data: every message received 2026-10-05 14:00:00-14:00:03 CT, as Schwab sent them
(tests/fixtures/real_stream_mix_2026_10_05_1400ct.json: 7,420 LEVELONE_OPTIONS, 152
LEVELONE_EQUITIES and 4 OPTIONS_BOOK messages). STAND-IN (named): the daemon's status, holding a
contract or not.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import app.options.order_flow.state as ofls
import live_market_plane as lmp
import time_et
from app.market_data.schwab.streaming import capture
from app.options.order_flow import streaming as ofs
from app.options.order_flow.engine import Book, read_book
from stream_spine import HealthRegistry, MessageBus, book_msg, quote_msg, verbatim_msg

_MIX = json.loads(
    (Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json").read_text(
        encoding="utf-8"
    )
)["messages"]
BOOK_CONTRACT = "SPY   261005C00774000"


def _message(m: dict) -> tuple[str, dict]:
    """One fixture row as the daemon publishes it on its bus."""
    sym, svc, ts = m["item"]["key"], m["service"], m["ts_recv"]
    if svc == "LEVELONE_OPTIONS":
        return f"optquote.{sym}", verbatim_msg(
            symbol=sym, content=m["item"], src="schwab_options_l1", ts_recv=ts
        )
    if svc == "LEVELONE_EQUITIES":
        return f"quote.{sym}", quote_msg(symbol=sym, src="schwab_l1", ts_recv=ts, native=m["item"])
    return f"book.{sym}", book_msg(
        symbol=sym, service=svc, content=m["item"], src="schwab_book", ts_recv=ts
    )


def test_every_option_and_equity_message_on_the_one_push_reaches_the_console():
    """The daemon publishes each message Schwab sent on its bus; the console, in the same
    program, reads that bus and keeps each contract's newest values as sent: every option
    contract's last BID_PRICE and ASK_PRICE (its top of book), and the option book Schwab sent
    last."""
    rows = [
        m for m in _MIX if m["service"] in ("LEVELONE_OPTIONS", "LEVELONE_EQUITIES", "OPTIONS_BOOK")
    ]
    want = {}
    for m in rows:
        if m["service"] == "LEVELONE_OPTIONS":
            top = want.setdefault(m["item"]["key"], {})
            top.update(
                {
                    name: m["item"][f]
                    for f, name in (("BID_PRICE", "bid"), ("ASK_PRICE", "ask"))
                    if f in m["item"]
                }
            )
    want = {s: t for s, t in want.items() if t}
    newest_book = [m["item"] for m in rows if m["service"] == "OPTIONS_BOOK"][-1]

    def top(sym):
        t = ofls.option_top(sym) or {}
        return {k: t[k] for k in want[sym] if k in t}

    async def go():
        daemon = capture.Daemon(MessageBus(), HealthRegistry())
        ofs.bind_daemon(daemon)
        assert ofs.start_order_flow_stream()
        try:
            for m in rows:
                daemon.bus.publish(*_message(m))
            deadline = time_et.elapsed() + 30
            while any(top(s) != t for s, t in want.items()) and time_et.elapsed() < deadline:
                await asyncio.sleep(0.05)
            books = ofls.get_content_for_symbol(BOOK_CONTRACT)
            return {s: top(s) for s in want}, next(
                i for i in reversed(books) if isinstance(i, Book)
            )
        finally:
            ofs.stop_order_flow_stream()
            ofs._daemon = None

    ofls.clear_all_live_state()
    try:
        tops, book = asyncio.run(go())
    finally:
        ofls.clear_all_live_state()
    assert want and tops == want
    assert book == read_book(newest_book, "OPTIONS_BOOK")  # every level Schwab sent, as read


def test_a_contract_the_daemon_stops_streaming_keeps_its_last_bid():
    """The option rule moves off a contract (the daemon's status no longer holds it): the last
    bid stays, and the Flow panel marks the contract NOT STREAMED."""
    m = next(m for m in _MIX if m["service"] == "LEVELONE_OPTIONS" and "BID_PRICE" in m["item"])
    sym = m["item"]["key"]
    ofls.clear_all_live_state()
    try:
        lmp.record_feed_heartbeat(
            {
                "ts": time_et.now(),
                "schwab_socket_open": True,
                "held": {"LEVELONE_OPTIONS": [sym], "OPTIONS_BOOK": []},
            }
        )
        ofs._ingest_pushed(*_message(m))
        held = ofls.option_top(sym)
        lmp.record_feed_heartbeat(
            {
                "ts": time_et.now(),
                "schwab_socket_open": True,
                "held": {"LEVELONE_OPTIONS": [], "OPTIONS_BOOK": []},
            }
        )
        released = ofls.option_top(sym)
    finally:
        ofls.clear_all_live_state()
        lmp.record_feed_down()
    assert held["bid"] == m["item"]["BID_PRICE"]
    assert released["bid"] == m["item"]["BID_PRICE"]
    assert (
        ofs.get_option_contract_streaming_diagnostics(sym, time_et.now())["subscription_state"]
        == ofs.NOT_STREAMED
    )
