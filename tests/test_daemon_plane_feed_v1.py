"""SINGLE-STREAM-AUTHORITY root fix — the live plane is fed by the canonical capture daemon,
with zero Schwab connection of its own.

This is the seam that used to be a second `schwab.streaming.StreamClient`. Since 2026-09-23
the daemon PUSHES each message (live_push); these tests drive the REAL message constructors
the daemon publishes with (stream_spine.quote_msg / book_msg) through the REAL ingest
(order_flow_streaming._ingest_pushed). The socket end to end is
tests/test_live_push_channel_v1.py.
"""

from __future__ import annotations

import time

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
from stream_spine import book_msg, quote_msg


@pytest.fixture(autouse=True)
def _isolate_stream_capture_env(monkeypatch):
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)


def _reset(tmp_path):
    ofs._feed_running = False
    ofls.clear_all_live_state()
    return tmp_path / "stream_capture.db"


def _push_l1(symbol, native, ts_recv):
    ofs._ingest_pushed(f"quote.{symbol}", quote_msg(
        symbol=symbol, bid=native.get("BID_PRICE"), src="schwab_l1", ts_recv=ts_recv,
        native=native))


def _push_book(symbol, content, ts_recv):
    ofs._ingest_pushed(f"book.{symbol}", book_msg(
        symbol=symbol, service="NASDAQ_BOOK", content=content, src="schwab_book",
        ts_recv=ts_recv))


def test_l1_message_lands_in_the_tape_and_the_console_keeps_no_price(tmp_path, monkeypatch):
    _reset(tmp_path)
    monkeypatch.setattr(lmp, "_by_ticker", {})
    native = {"key": "SPY", "BID_PRICE": 449.98, "ASK_PRICE": 450.02, "LAST_PRICE": 450.0,
              "LAST_SIZE": 100, "TRADE_TIME_MILLIS": 1000, "TOTAL_VOLUME": 5000}
    _push_l1("SPY", native, ts_recv=time.time())

    top = ofls.get_content_for_symbol("SPY")
    assert any(item.get("LAST_PRICE") == 450.0 for item in top)
    assert lmp.get_quote("SPY") is None          # the price is the daemon's row, not a copy here


def test_book_message_lands_verbatim(tmp_path):
    _reset(tmp_path)
    content = {"key": "SPY", "BIDS": [{"BID_PRICE": 449.9, "BID_SIZE": 100}],
               "ASKS": [{"ASK_PRICE": 450.1, "ASK_SIZE": 200}], "BOOK_TIME": 555}
    _push_book("SPY", content, ts_recv=time.time())

    items = ofls.get_content_for_symbol("SPY")
    assert any(i.get("BIDS") == content["BIDS"] for i in items)


def test_each_venue_serves_only_its_own_book(tmp_path):
    """Real SPY NYSE_BOOK and NASDAQ_BOOK messages (tests/fixtures/real_spy_nyse_nasdaq_books.json)
    through the real ingest: each venue's route answer is that venue's book, never the newest
    of the two."""
    import json
    from pathlib import Path

    import server
    _reset(tmp_path)
    fx = json.loads((Path(__file__).parent / "fixtures" / "real_spy_nyse_nasdaq_books.json")
                    .read_text(encoding="utf-8"))["books"]
    for svc in ("NASDAQ_BOOK", "NYSE_BOOK"):
        ofs._ingest_pushed("book.SPY", book_msg(symbol="SPY", service=svc, content=fx[svc]["content"],
                                                src="schwab_book", ts_recv=fx[svc]["ts_recv"]))
    for svc in ("NASDAQ_BOOK", "NYSE_BOOK"):
        body = json.loads(server.api_order_flow_microstructure(ticker="SPY", venue=svc).body)
        prov = body["provenance"]
        assert (body["venue"], prov["book_source"]) == (svc, svc)
        assert prov["n_bid_levels"] == len(fx[svc]["content"]["BIDS"])
        assert prov["book_time_ms"] == fx[svc]["content"]["BOOK_TIME"]


def test_a_book_is_live_by_the_one_rule_on_its_venue_not_by_its_book_time(tmp_path, monkeypatch):
    """ONE-15: a book read stale once its BOOK_TIME was 25 s old -- a fourth liveness limit. It
    is live while the daemon's heartbeat is live and it holds the ticker on that venue's service,
    however old its last change (these real books are days old), at any hour: no clock of ours
    judges it (operator 2026-10-01, "From Schwab's mouth to our UI's ears. Period."). Real SPY
    books (tests/fixtures/real_spy_nyse_nasdaq_books.json)."""
    import json
    from pathlib import Path

    import server
    _reset(tmp_path)
    fx = json.loads((Path(__file__).parent / "fixtures" / "real_spy_nyse_nasdaq_books.json")
                    .read_text(encoding="utf-8"))["books"]
    for svc in ("NASDAQ_BOOK", "NYSE_BOOK"):
        ofs._ingest_pushed("book.SPY", book_msg(symbol="SPY", service=svc, content=fx[svc]["content"],
                                                src="schwab_book", ts_recv=fx[svc]["ts_recv"]))

    def stale(svc):
        return json.loads(server.api_order_flow_microstructure(ticker="SPY", venue=svc).body)["ages"]["book_stale"]

    held = {"schwab_socket_open": True, "held": {"NASDAQ_BOOK": ["SPY"], "NYSE_BOOK": []}}
    lmp.record_feed_heartbeat({**held, "ts": time.time()})
    assert (stale("NASDAQ_BOOK"), stale("NYSE_BOOK")) == (False, True)
    lmp.record_feed_heartbeat({**held, "ts": time.time() - lmp.FEED_HEARTBEAT_MAX_AGE_SEC - 1})
    assert (stale("NASDAQ_BOOK"), stale("NYSE_BOOK")) == (True, True)


def test_each_symbol_lands_in_its_own_state_only(tmp_path, monkeypatch):
    """Every roster symbol is applied, each into its OWN state: a QQQ tick must never appear in
    SPY's."""
    _reset(tmp_path)
    monkeypatch.setattr(lmp, "_by_ticker", {})
    _push_l1("QQQ", {"key": "QQQ", "LAST_PRICE": 380.0}, ts_recv=time.time())

    assert not any(i.get("LAST_PRICE") == 380.0 for i in ofls.get_content_for_symbol("SPY"))
    assert any(i.get("LAST_PRICE") == 380.0 for i in ofls.get_content_for_symbol("QQQ"))
