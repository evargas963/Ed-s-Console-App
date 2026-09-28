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
    ofs._active_ticker = None
    ofs._streaming_last_update_ts = None
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


def test_l1_message_lands_in_both_planes(tmp_path, monkeypatch):
    _reset(tmp_path)
    monkeypatch.setattr(lmp, "_by_ticker", {})
    native = {"key": "SPY", "BID_PRICE": 449.98, "ASK_PRICE": 450.02, "LAST_PRICE": 450.0,
              "LAST_SIZE": 100, "TRADE_TIME_MILLIS": 1000, "TOTAL_VOLUME": 5000}
    _push_l1("SPY", native, ts_recv=time.time())

    top = ofls.get_content_for_symbol("SPY")
    assert any(item.get("LAST_PRICE") == 450.0 for item in top)
    assert lmp.get_quote("SPY")["spot"] == 450.0


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


def test_each_symbol_lands_in_its_own_state_only(tmp_path, monkeypatch):
    """Every roster symbol is applied (the watchlist reads each one's streamed LAST_PRICE),
    each into its OWN state: a QQQ tick must never appear in SPY's."""
    _reset(tmp_path)
    monkeypatch.setattr(lmp, "_by_ticker", {})
    ofs._active_ticker = "SPY"
    _push_l1("QQQ", {"key": "QQQ", "LAST_PRICE": 380.0}, ts_recv=time.time())

    assert not any(i.get("LAST_PRICE") == 380.0 for i in ofls.get_content_for_symbol("SPY"))
    assert any(i.get("LAST_PRICE") == 380.0 for i in ofls.get_content_for_symbol("QQQ"))
    assert lmp.get_quote("QQQ")["spot"] == 380.0
    assert lmp.get_quote("SPY") is None
    # the ACTIVE ticker's feed-health clock is not advanced by another symbol's tick
    assert ofs._streaming_last_update_ts is None


def test_a_page_connecting_for_a_ticker_subscribes_its_books_and_again_after_a_restart(monkeypatch):
    """The Trade Desk never asked for books and a console restart forgot the one-shot request,
    so MU read no_book all session (2026-09-28). The page's /api/changes connection is the
    request: it survives restarts because the page reconnects."""
    import asyncio

    import push_changes
    import server

    def books_after_connect():
        asyncio.run(server.get_changes(ticker="mu"))     # the page opens its connection
        end = time.monotonic() + 5
        while time.monotonic() < end and ofs.current_wanted()["NYSE_BOOK"] != ["MU"]:
            time.sleep(0.02)
        w = ofs.current_wanted()
        return w["NYSE_BOOK"], w["NASDAQ_BOOK"]

    monkeypatch.setattr(push_changes, "_clients", {})
    monkeypatch.setattr(ofs, "_active_ticker", None)
    assert books_after_connect() == (["MU"], ["MU"])
    monkeypatch.setattr(ofs, "_active_ticker", None)     # a console restart forgets it
    assert books_after_connect() == (["MU"], ["MU"])     # the page reconnects: books again


def test_set_active_ticker_puts_its_book_and_quote_in_the_wanted_list(tmp_path, monkeypatch):
    """The wanted list is the ONLY channel by which this module influences the daemon's
    subscriptions -- the active ticker's book and quote must be in it."""
    monkeypatch.setattr(ofs, "_active_ticker", None)
    before = ofs._wanted_version
    ofs.set_streaming_active_ticker("spy")
    w = ofs.current_wanted()
    assert w["NYSE_BOOK"] == w["NASDAQ_BOOK"] == ["SPY"]
    assert w["LEVELONE_EQUITIES"][0] == "SPY"
    assert ofs._wanted_version > before, "the feed loop sends the change"


# ─────────────────────────────────────────────────────────────────────────────
# 2026-09-16, audit finding #6 (bounded-vendor-call reconciliation): the producer's
# rejected-contract map rides the SAME heartbeat row as claimed_coverage_json. These
# prove the REAL CaptureWriter.write_heartbeat / read_producer_rejected_option_contracts
# round trip: sticky-unless-explicit (a frequent claimed_coverage-only publish must not
# wipe a standing rejection) and the same staleness fail-closed rule as coverage.
