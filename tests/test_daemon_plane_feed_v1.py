"""SINGLE-STREAM-AUTHORITY root fix — the live plane is fed by the canonical capture daemon,
with zero Schwab connection of its own.

This is the seam that used to be a second `schwab.streaming.StreamClient`. Since 2026-09-23
the daemon publishes each message on its bus, which the console in the same program reads
(order_flow_streaming._bus_loop); these tests drive the REAL message constructors the daemon
publishes with (stream_spine.quote_msg / book_msg) through the REAL ingest
(order_flow_streaming._ingest_pushed). The bus end to end is tests/test_live_push_channel_v1.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import server
import time_et
from app.options.order_flow.engine import read_book
from stream_spine import book_msg, quote_msg
from tests.feed_live_helper import RTH_INSTANT, daemon_status


def _reset(tmp_path):
    ofs._feed_running = False
    ofls.clear_all_live_state()
    return tmp_path / "stream_capture.db"


def _push_l1(symbol, native, ts_recv):
    ofs._ingest_pushed(
        f"quote.{symbol}",
        quote_msg(
            symbol=symbol,
            bid=native.get("BID_PRICE"),
            src="schwab_l1",
            ts_recv=ts_recv,
            native=native,
        ),
    )


def _push_book(symbol, content, ts_recv):
    ofs._ingest_pushed(
        f"book.{symbol}",
        book_msg(
            symbol=symbol,
            service="NASDAQ_BOOK",
            content=content,
            src="schwab_book",
            ts_recv=ts_recv,
        ),
    )


def test_l1_message_lands_in_the_tape_and_the_console_keeps_no_price(tmp_path):
    _reset(tmp_path)
    lmp._by_ticker.pop("SPY", None)  # a plane row an earlier test wrote
    lmp._fields_by_ticker.pop("SPY", None)
    native = {
        "key": "SPY",
        "BID_PRICE": 449.98,
        "ASK_PRICE": 450.02,
        "LAST_PRICE": 450.0,
        "LAST_SIZE": 100,
        "TRADE_TIME_MILLIS": 1000,
        "TOTAL_VOLUME": 5000,
    }
    _push_l1("SPY", native, ts_recv=time_et.now())

    top = ofls.get_content_for_symbol("SPY")
    assert any(isinstance(item, dict) and item["price"] == 450.0 for item in top)
    assert lmp.get_quote("SPY") is None  # the price is the daemon's row, not a copy here


def test_a_book_message_lands_as_the_one_reader_reads_it(tmp_path):
    """A real SPY NASDAQ_BOOK message (tests/fixtures/real_spy_nyse_nasdaq_books.json) through the
    real ingest: the console holds the book as engine.read_book reads it, every level Schwab sent
    with its price and size.
    """
    _reset(tmp_path)
    fx = Path(__file__).resolve().parent / "fixtures" / "real_spy_nyse_nasdaq_books.json"
    content = json.loads(fx.read_text(encoding="utf-8"))["books"]["NASDAQ_BOOK"]["content"]
    _push_book("SPY", content, ts_recv=time_et.now())

    items = ofls.get_content_for_symbol("SPY")
    held = read_book(content, "NASDAQ_BOOK")
    assert held in items
    assert [p for p, _v in held.pairs("BIDS")] == [lv["BID_PRICE"] for lv in content["BIDS"]]


def test_each_venue_serves_only_its_own_book(tmp_path):
    """Real SPY NYSE_BOOK and NASDAQ_BOOK messages (tests/fixtures/real_spy_nyse_nasdaq_books.json)
    through the real ingest: each venue's route answer is that venue's book, never the newest
    of the two.
    """
    _reset(tmp_path)
    fx = json.loads(
        (Path(__file__).parent / "fixtures" / "real_spy_nyse_nasdaq_books.json").read_text(
            encoding="utf-8"
        )
    )["books"]
    for svc in ("NASDAQ_BOOK", "NYSE_BOOK"):
        ofs._ingest_pushed(
            "book.SPY",
            book_msg(
                symbol="SPY",
                service=svc,
                content=fx[svc]["content"],
                src="schwab_book",
                ts_recv=fx[svc]["ts_recv"],
            ),
        )
    for svc in ("NASDAQ_BOOK", "NYSE_BOOK"):
        body = json.loads(server.api_order_flow_microstructure(ticker="SPY", venue=svc).body)
        prov = body["provenance"]
        assert (body["venue"], prov["book_source"]) == (svc, svc)
        assert prov["n_bid_levels"] == len(fx[svc]["content"]["BIDS"])
        assert prov["book_time_ms"] == fx[svc]["content"]["BOOK_TIME"]


def test_a_book_is_live_by_the_one_rule_on_its_venue_not_by_its_book_time(tmp_path):
    """ONE-15: a book read stale once its BOOK_TIME was 25 s old -- a fourth liveness limit. It
    is live while the daemon's heartbeat is live and it holds the ticker on that venue's service,
    however old its last change (these real books are days old), at any hour: no clock of ours
    judges it (operator 2026-10-01, "From Schwab's mouth to our UI's ears. Period."). Real SPY
    books (tests/fixtures/real_spy_nyse_nasdaq_books.json), judged in regular hours
    (RTH_INSTANT).
    """
    _reset(tmp_path)
    fx = json.loads(
        (Path(__file__).parent / "fixtures" / "real_spy_nyse_nasdaq_books.json").read_text(
            encoding="utf-8"
        )
    )["books"]
    for svc in ("NASDAQ_BOOK", "NYSE_BOOK"):
        ofs._ingest_pushed(
            "book.SPY",
            book_msg(
                symbol="SPY",
                service=svc,
                content=fx[svc]["content"],
                src="schwab_book",
                ts_recv=fx[svc]["ts_recv"],
            ),
        )

    def stale(svc):
        return server.order_flow_microstructure("SPY", svc, RTH_INSTANT)["ages"]["book_stale"]

    held = {
        "schwab_socket_open": True,
        "held": {"LEVELONE_EQUITIES": ["SPY"], "NASDAQ_BOOK": ["SPY"], "NYSE_BOOK": []},
    }
    lmp.record_feed_heartbeat(daemon_status(RTH_INSTANT, **held))
    assert (stale("NASDAQ_BOOK"), stale("NYSE_BOOK")) == (False, True)
    lmp.record_feed_heartbeat(
        daemon_status(RTH_INSTANT - lmp.FEED_HEARTBEAT_MAX_AGE_SEC - 1, **held)
    )
    assert (stale("NASDAQ_BOOK"), stale("NYSE_BOOK")) == (True, True)


def test_each_symbol_lands_in_its_own_state_only(tmp_path):
    """Every roster symbol is applied, each into its OWN state: a QQQ tick must never appear in
    SPY's.
    """
    _reset(tmp_path)
    _push_l1("QQQ", {"key": "QQQ", "LAST_PRICE": 380.0}, ts_recv=time_et.now())

    def prices(sym: str) -> list:
        return [i["price"] for i in ofls.get_content_for_symbol(sym) if isinstance(i, dict)]

    assert 380.0 not in prices("SPY")
    assert 380.0 in prices("QQQ")
