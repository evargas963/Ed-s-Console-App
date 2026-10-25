"""The Flow panel's contract (/api/order-flow/options-microstructure), Schwab to the screen, through
the real code: the daemon's pushed messages applied by the console (streaming._ingest_pushed), the
daemon's status (live_market_plane.record_feed_heartbeat), the route.

Real data: every message of SPY 2026-10-05 774 call received 2026-10-05 14:00:00-14:00:03 CT, as
Schwab sent them (tests/fixtures/real_stream_mix_2026_10_05_1400ct.json: four OPTIONS_BOOK
messages). STAND-IN (named): the daemon's status, holding the contract or not.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import app.options.order_flow.state as ofls
import live_market_plane as lmp
import server
from app.options.order_flow import streaming as ofs
from stream_spine import book_msg

CONTRACT = "SPY   261005C00774000"
_MIX = json.loads((Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json")
                  .read_text(encoding="utf-8"))
BOOKS = [m for m in _MIX["messages"] if m["service"] == "OPTIONS_BOOK" and m["item"]["key"] == CONTRACT]


def _daemon_holds(*services: str, now: "float | None" = None) -> None:
    """The daemon's heartbeat stamped `now` (the wall clock when not given), holding CONTRACT on `services`."""
    lmp.record_feed_heartbeat({"ts": time.time() if now is None else now, "schwab_socket_open": True,
                               "held": {svc: [CONTRACT] for svc in services}})


def _route() -> dict:
    return json.loads(server.api_order_flow_options_microstructure(contract=CONTRACT).body)


def test_the_flow_panel_shows_schwabs_newest_option_book_as_sent():
    """Each OPTIONS_BOOK message the daemon pushes reaches the Flow panel: its top level's sizes
    are Schwab's newest book's, as sent."""
    ofls.clear_all_live_state()
    _daemon_holds("LEVELONE_OPTIONS", "OPTIONS_BOOK")
    try:
        for m in BOOKS:
            ofs._ingest_pushed(f"book.{CONTRACT}", book_msg(symbol=CONTRACT, service="OPTIONS_BOOK", content=m["item"],
                                                            src="schwab_book", ts_recv=m["ts_recv"]))
        body = _route()
    finally:
        ofls.clear_all_live_state()
        lmp.record_feed_down()
    newest = BOOKS[-1]["item"]
    assert len(BOOKS) == 4 and body["status"] == "ok"
    assert (body["depth"]["1"]["bid_total"], body["depth"]["1"]["ask_total"]) == (
        newest["BIDS"][0]["TOTAL_VOLUME"], newest["ASKS"][0]["TOTAL_VOLUME"])


def test_with_no_book_from_schwab_the_flow_panel_says_so():
    ofls.clear_all_live_state()
    assert _route()["status"] == "no_book"


def test_the_flow_panel_says_whether_the_daemon_streams_the_contract():
    """SUBSCRIBED while the daemon holds the contract on LEVELONE_OPTIONS; NOT STREAMED when it
    does not, and when its status is gone (a daemon that stopped reporting holds nothing). A contract
    of SPY's 2026-10-07 0DTE chain, served at that chain's capture (12:32 ET, the option market open).
    The contract's market is that of the chain that lists it: with no chain held that lists it, its
    market is not known and it is not live; once the levels producer publishes SPY's chain, SPY's."""
    from tests.real_chains import SPY_0DTE
    contract, at = SPY_0DTE.chain[0]["symbol"], SPY_0DTE.now.timestamp()

    def holds(*services: str) -> None:
        lmp.record_feed_heartbeat({"ts": at, "schwab_socket_open": True,
                                   "held": {svc: [contract] for svc in services}})

    def served() -> dict:
        return server.options_microstructure(contract, at)
    with server._terrain_cache_lock:
        server._terrain_cache.pop("SPY", None)
    try:
        holds("LEVELONE_OPTIONS", "OPTIONS_BOOK")
        unlisted = served()
        server._publish_levels("SPY", captures=[{"contracts": [dict(c) for c in SPY_0DTE.chain], "ts_utc": at,
                                                 "spot": SPY_0DTE.spot, "spot_ts": None, "spot_from_chain": False,
                                                 "et_date": SPY_0DTE.now.date().isoformat(),
                                                 "basis": server.CAPTURE_BASIS}], now=SPY_0DTE.now)
        held = served()["streaming_plane"]
        holds()
        not_held = served()["streaming_plane"]
        lmp.record_feed_down()
        down = served()["streaming_plane"]
    finally:
        lmp.record_feed_down()
        with server._terrain_cache_lock:
            server._terrain_cache.pop("SPY", None)
    assert (unlisted["top_feed_label"], unlisted["top_outage"]) == ("NOT LIVE", "the contract's option market is not known")
    assert held["subscription_state"] == "SUBSCRIBED"
    assert (held["feed_health"]["l1"]["state"], held["feed_health"]["book"]["state"]) == ("LIVE", "LIVE")
    assert not_held["subscription_state"] == down["subscription_state"] == "NOT STREAMED"
    assert not_held["feed_health"]["l1"]["state"] == "NOT LIVE"
