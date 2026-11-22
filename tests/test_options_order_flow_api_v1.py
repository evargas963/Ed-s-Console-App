"""The Flow panel's contract (the `contract` panel), Schwab to the screen.

Through the real code: the daemon's pushed messages applied by the console
(streaming._ingest_pushed), the daemon's status (live_market_plane.record_feed_heartbeat), the
route.

Real data: every message of SPY 2026-10-05 774 call received 2026-10-05 14:00:00-14:00:03 CT, as
Schwab sent them (tests/fixtures/real_stream_mix_2026_10_05_1400ct.json: four OPTIONS_BOOK
messages). STAND-IN (named): the daemon's status, holding the contract or not.
"""

from __future__ import annotations

import json
from pathlib import Path

import app.options.order_flow.state as ofls
import live_market_plane as lmp
import time_et
from app.options.order_flow import streaming as ofs
from push import contract as push_contract
from state import level_store
from stream_spine import book_msg
from tests.feed_live_helper import daemon_status, publish_capture
from tests.real_chains import SPY_0DTE

CONTRACT = "SPY   261005C00774000"
_MIX = json.loads(
    (Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json").read_text(
        encoding="utf-8"
    )
)
BOOKS = [
    m for m in _MIX["messages"] if m["service"] == "OPTIONS_BOOK" and m["item"]["key"] == CONTRACT
]


def _daemon_holds(*services: str, now: float | None = None) -> None:
    """Record the daemon's heartbeat stamped `now`, holding CONTRACT on `services`.

    `now` is the wall clock when not given.
    """
    lmp.record_feed_heartbeat(
        daemon_status(
            time_et.now() if now is None else now,
            schwab_socket_open=True,
            held={svc: [CONTRACT] for svc in services},
        )
    )


def _route() -> dict:
    return json.loads(json.dumps(push_contract.options_microstructure(CONTRACT, time_et.now())))


def test_the_flow_panel_shows_schwabs_newest_option_book_as_sent():
    """Each OPTIONS_BOOK message the daemon pushes reaches the Flow panel.

    Its top level's sizes are Schwab's newest book's, as sent.
    """
    ofls.clear_all_live_state()
    _daemon_holds("LEVELONE_OPTIONS", "OPTIONS_BOOK")
    try:
        for m in BOOKS:
            ofs._ingest_pushed(
                f"book.{CONTRACT}",
                book_msg(
                    symbol=CONTRACT,
                    service="OPTIONS_BOOK",
                    content=m["item"],
                    src="schwab_book",
                    ts_recv=m["ts_recv"],
                ),
            )
        body = _route()
    finally:
        ofls.clear_all_live_state()
        lmp.record_feed_down()
    newest = BOOKS[-1]["item"]
    assert len(BOOKS) == 4 and body["status"] == "ok"
    assert (body["depth"]["1"]["bid_total"], body["depth"]["1"]["ask_total"]) == (
        newest["BIDS"][0]["TOTAL_VOLUME"],
        newest["ASKS"][0]["TOTAL_VOLUME"],
    )


def test_with_no_book_from_schwab_the_flow_panel_says_so():
    ofls.clear_all_live_state()
    assert _route()["status"] == "no_book"


def test_the_flow_panel_says_whether_the_daemon_streams_the_contract():
    """SUBSCRIBED while the daemon holds the contract on LEVELONE_OPTIONS; else NOT STREAMED.

    NOT STREAMED when it does not, and when its status is gone (a daemon that stopped reporting
    holds nothing). A contract of SPY's 2026-10-07 0DTE chain, served at that chain's capture
    (12:32 ET, the option market open).
    """
    contract, at = SPY_0DTE.chain[0]["symbol"], SPY_0DTE.now.timestamp()

    def holds(*services: str) -> None:
        lmp.record_feed_heartbeat(
            daemon_status(at, schwab_socket_open=True, held={svc: [contract] for svc in services})
        )

    def served() -> dict:
        return push_contract.options_microstructure(contract, at)

    with level_store._lock:
        level_store._levels.pop("SPY", None)
    try:
        holds("LEVELONE_OPTIONS", "OPTIONS_BOOK")
        publish_capture(
            "SPY",
            SPY_0DTE.chain,
            at,
            SPY_0DTE.spot,
            SPY_0DTE.now.date().isoformat(),
            SPY_0DTE.now,
        )
        held = served()["streaming_plane"]
        holds()
        not_held = served()["streaming_plane"]
        lmp.record_feed_down()
        down = served()["streaming_plane"]
    finally:
        lmp.record_feed_down()
        with level_store._lock:
            level_store._levels.pop("SPY", None)
    assert held["subscription_state"] == "SUBSCRIBED"
    assert (held["feed_health"]["l1"]["state"], held["feed_health"]["book"]["state"]) == (
        "LIVE",
        "LIVE",
    )
    assert not_held["subscription_state"] == down["subscription_state"] == "NOT STREAMED"
    assert not_held["feed_health"]["l1"]["state"] == "NOT LIVE"
    # the badge the Flow panel draws, served with it: ACTIVE only while held with its feed live
    assert (held["subscription_active"], held["subscription_text"]) == (True, "ACTIVE")
    for plane in (not_held, down):
        assert (plane["subscription_active"], plane["subscription_text"]) == (False, "NOT STREAMED")


def test_the_flow_header_says_the_side_in_words_and_nothing_where_none_is_named():
    """The header's side as the chain record names it, served in the header's words.

    SPY's 2026-10-07 0DTE chain, published as captured: a call reads Call and a put reads Put,
    and before a chain lists the contract there is no side and no words. INDUCED: the same chain
    with the put's putCall not sent, which Schwab has not sent us: its record names no side, and
    the panel serves no words for it. The page draws the words and picks none.
    """
    at = SPY_0DTE.now.timestamp()
    call = next(c["symbol"] for c in SPY_0DTE.chain if c["putCall"] == "CALL")
    put = next(c["symbol"] for c in SPY_0DTE.chain if c["putCall"] == "PUT")
    no_side = [
        {k: v for k, v in c.items() if k != "putCall" or c["symbol"] != put} for c in SPY_0DTE.chain
    ]

    def said(symbol: str) -> tuple[str | None, str | None]:
        body = push_contract.options_microstructure(symbol, at)
        return body["put_call"], body["put_call_text"]

    def publish(chain: list) -> None:
        day = SPY_0DTE.now.date().isoformat()
        publish_capture("SPY", chain, at, SPY_0DTE.spot, day, SPY_0DTE.now)

    with level_store._lock:
        level_store._levels.pop("SPY", None)
    try:
        unlisted = said(call)
        publish(SPY_0DTE.chain)
        listed = said(call), said(put)
        publish(no_side)
        unnamed = said(call), said(put)
    finally:
        with level_store._lock:
            level_store._levels.pop("SPY", None)
    assert unlisted == (None, None)
    assert listed == (("CALL", "Call"), ("PUT", "Put"))
    assert unnamed == (("CALL", "Call"), (None, None))
