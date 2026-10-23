"""Schwab -> the Flow panel. A contract's quote time and book time stay when the feed is down; its
side is the CONTRACT_TYPE Schwab sent in its first message (real SPY 2026-10-23 761 call and 762 put:
the stored message carrying CONTRACT_TYPE and the three after it,
tests/fixtures/real_spy_option_contract_type_2026_10_23.json, read from stream_capture.db)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import live_market_plane as lmp
import server
from app.options.order_flow import state as of_state
from app.options.order_flow import streaming as ofs
from app.options.order_flow.history import TAPE
from stream_spine import options_quote_msg

_SYM = "ZZOPT  261016C00100000"
_WHEN = 1790380799830  # Fri 09/25 06:59 PM CT
_SIDES = json.loads((Path(__file__).parent / "fixtures" / "real_spy_option_contract_type_2026_10_23.json")
                    .read_text(encoding="utf-8"))["contracts"]


def test_the_flow_panel_shows_the_side_schwab_sent_in_the_contracts_first_message():
    """After the messages that leave CONTRACT_TYPE out, the Flow panel still shows CALL and PUT.
    Before Schwab sends it, the side is unknown."""
    sides = {}
    try:
        for sym, msgs in _SIDES.items():
            ofs._ingest_pushed(f"optquote.{sym}", options_quote_msg(symbol=sym, content=msgs[1]["item"], src="schwab",
                                                                    ts_recv=msgs[1]["ts_recv"]))
            before = server.options_microstructure(sym, time.time())["put_call"]
            for m in msgs:
                ofs._ingest_pushed(f"optquote.{sym}", options_quote_msg(symbol=sym, content=m["item"], src="schwab",
                                                                        ts_recv=m["ts_recv"]))
            sides[sym] = (before, server.options_microstructure(sym, time.time())["put_call"])
    finally:
        for sym in _SIDES:
            TAPE.forget(sym)
            ofs._option_contract_last_update_ts.pop(sym, None)
        of_state.clear_all_live_state()
    assert [len(m) for m in _SIDES.values()] == [4, 4]
    assert all("CONTRACT_TYPE" not in m["item"] for msgs in _SIDES.values() for m in msgs[1:])
    assert sides == {"SPY   261023C00761000": (None, "CALL"), "SPY   261023P00762000": (None, "PUT")}


def test_a_down_feed_keeps_the_contracts_quote_time_and_book_time():
    """QUOTE_TIME_MILLIS stays on the option top, and BOOK_TIME stays on the book. The Flow
    panel still shows the last bid, with both times."""
    of_state.push_option_top(_SYM, {
        "BID_PRICE": 1.25, "ASK_PRICE": 1.40, "QUOTE_TIME_MILLIS": _WHEN,
    })
    of_state.push_book(_SYM, {
        "BIDS": [{"BID_PRICE": 1.25, "TOTAL_VOLUME": 10}],
        "ASKS": [{"ASK_PRICE": 1.40, "TOTAL_VOLUME": 8}],
        "BOOK_TIME": _WHEN,
    }, "OPTIONS_BOOK")
    try:
        lmp.record_feed_down()
        body = server.options_microstructure(_SYM, time.time())
    finally:
        of_state._LIVE_STATE._top.pop(_SYM, None)
        of_state._LIVE_STATE._book.pop(_SYM, None)
        lmp.record_feed_down()
    assert body["top_of_book"]["bid"] == 1.25
    assert body["top_outage"] is not None
    assert body["quote_time_ct"] == "Fri 09/25 06:59 PM CT"
    assert body["book_time_ct"] == "Fri 09/25 06:59 PM CT"
