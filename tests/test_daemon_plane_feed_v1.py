"""Section 2: the canonical daemon's captured L1 + equity books route into the live plane.

Every test CALLS the feeder against a real fixture stream_capture.db and asserts the two live-plane
surfaces (live_market_plane quotes, order_flow_live_state book/tape/top) reflect the daemon's data
with the field MEANING preserved — proven by driving frames, not by matching source text.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import daemon_plane_feed as dpf  # noqa: E402
import live_market_plane as lmp  # noqa: E402
import order_flow_live_state as ofs  # noqa: E402
from calibration.equity_book_frames import ensure_equity_book_schema  # noqa: E402
from instrument_identity import ticker_storage_key  # noqa: E402
from stream_spine import STREAM_SCHEMA_SQL  # noqa: E402

TICK = "ZZTESTB"        # test tickers that cannot collide with a real symbol
OTHER = "ZZOTHERB"


def _clear(*syms):
    for s in syms:
        ofs.clear_symbol(s)
        with lmp._lock:
            lmp._by_ticker.pop(ticker_storage_key(s), None)


def _capture_db(tmp_path, *, l1: bool = True, book: bool = True) -> sqlite3.Connection:
    con = sqlite3.connect(str(tmp_path / "stream_capture.db"))
    con.executescript(STREAM_SCHEMA_SQL)
    ensure_equity_book_schema(con)
    if l1:
        con.execute(
            "INSERT INTO stream_quotes_raw(ts_recv,symbol,bid,ask,last,bid_size,ask_size,"
            "last_size,total_volume,quote_time_ms,trade_time_ms,src) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (time.time(), TICK, 712.44, 712.46, 712.45, 100, 200, 5, 1_000_000,
             1787231152000, 1787231151900, "schwab_l1"))
        con.execute(  # an OLDER quote for the same ticker — proves "latest wins"
            "INSERT INTO stream_quotes_raw(ts_recv,symbol,bid,ask,last,src) VALUES(?,?,?,?,?,?)",
            (time.time() - 60, TICK, 1.0, 2.0, 1.5, "schwab_l1"))
    if book:
        frame = {"service": "NASDAQ_BOOK", "timestamp": 1787231152513,
                 "content": [{"key": TICK, "BOOK_TIME": 1787231152213,
                              "BIDS": [{"BID_PRICE": 712.44, "TOTAL_VOLUME": 40}],
                              "ASKS": [{"ASK_PRICE": 712.46, "TOTAL_VOLUME": 30}]}]}
        cur = con.execute(
            "INSERT INTO equity_book_frames(service,frame_ts_ms,received_ts_ms,ingest_lag_ms,"
            "n_symbols,payload_json) VALUES(?,?,?,?,?,?)",
            ("NASDAQ_BOOK", frame["timestamp"], frame["timestamp"] + 10, 10, 1, json.dumps(frame)))
        con.execute("INSERT INTO equity_book_frame_symbols(frame_id,symbol_key,content_idx) "
                    "VALUES(?,?,?)", (cur.lastrowid, TICK, 0))
    con.commit()
    return con


def test_daemon_l1_hydrates_the_quote_plane_with_correct_meaning(tmp_path):
    _clear(TICK)
    con = _capture_db(tmp_path)
    counts = dpf.feed_once(con, [TICK])
    con.close()

    assert counts["l1"] == 1 and counts["quote_updates"] == 1
    q = lmp.get_quote(TICK)
    assert q is not None, "daemon L1 did not reach the quote plane"
    # meaning preserved: spot<-LAST_PRICE, bid<-BID_PRICE, ask<-ASK_PRICE, from the LATEST row
    assert q["spot"] == 712.45 and q["bid"] == 712.44 and q["ask"] == 712.46
    assert q["quote_ingestion"] == "schwab_streaming_level_one"
    # exchange clock is the vendor QUOTE_TIME_MILLIS (epoch seconds), not a server clock
    assert abs(q["exchange_quote_ts"] - 1787231152.0) < 1.0
    # a field the daemon does NOT capture (MARK) is honestly absent, never fabricated
    assert q.get("quote_mid") is None


def test_daemon_l1_hydrates_order_flow_top_and_tape(tmp_path):
    _clear(TICK)
    con = _capture_db(tmp_path)
    dpf.feed_once(con, [TICK])
    con.close()

    sizes = ofs.get_top_of_book_sizes(TICK)
    assert sizes["bid_size"] == 100 and sizes["ask_size"] == 200
    assert ofs.get_stream_volume(TICK) == 1_000_000
    content = ofs.get_content_for_symbol(TICK)
    assert any(c.get("LAST_PRICE") == 712.45 for c in content), "no tape print from the daemon L1"


def test_daemon_book_hydrates_order_flow_book_snapshots(tmp_path):
    _clear(TICK)
    con = _capture_db(tmp_path)
    counts = dpf.feed_once(con, [TICK])
    con.close()

    assert counts["book"] == 1
    books = [c for c in ofs.get_content_for_symbol(TICK) if c.get("BIDS") and c.get("ASKS")]
    assert books, "the daemon's book snapshot did not reach the order-flow state"
    assert books[0]["BIDS"][0]["BID_PRICE"] == 712.44   # nested depth carried verbatim


def test_only_daemon_captured_tickers_are_fed_so_dynamic_viewing_is_preserved(tmp_path):
    _clear(TICK, OTHER)
    con = _capture_db(tmp_path)
    dpf.feed_once(con, [TICK, OTHER])   # OTHER has no captured rows
    con.close()

    assert lmp.get_quote(TICK) is not None
    assert lmp.get_quote(OTHER) is None, "a ticker the daemon never captured must not be fabricated"


def test_feeder_works_read_only_no_writes_no_socket(tmp_path):
    """The feeder takes a db connection and only READS it — no Schwab StreamClient, no writes. Prove
    it runs against a strictly READ-ONLY connection (which would raise on any write)."""
    _clear(TICK)
    _capture_db(tmp_path).close()                       # build the db, then reopen read-only
    ro = dpf.open_capture_ro(str(tmp_path / "stream_capture.db"))
    counts = dpf.feed_once(ro, [TICK])
    ro.close()
    assert counts["l1"] == 1 and counts["book"] == 1    # read-only feed succeeded
    assert lmp.get_quote(TICK)["spot"] == 712.45


def test_missing_book_table_is_not_an_error(tmp_path):
    _clear(TICK)
    con = _capture_db(tmp_path, book=False)
    con.execute("DROP TABLE equity_book_frames")
    con.commit()
    counts = dpf.feed_once(con, [TICK])                 # books never captured
    con.close()
    assert counts["l1"] == 1 and counts["book"] == 0    # L1 still fed; no book, no crash


def test_gate_defaults_off(monkeypatch):
    monkeypatch.delenv(dpf.ED_DAEMON_PLANE_FEED_ENV, raising=False)
    assert dpf.daemon_plane_feed_enabled() is False
    monkeypatch.setenv(dpf.ED_DAEMON_PLANE_FEED_ENV, "on")
    assert dpf.daemon_plane_feed_enabled() is True


def test_captured_tickers_are_only_the_recently_captured_ones(tmp_path):
    con = _capture_db(tmp_path)
    try:
        assert dpf.captured_tickers(con, lookback_s=300) == [TICK]   # the one L1 symbol captured
        assert dpf.captured_tickers(con, lookback_s=1) == [TICK]     # newest row is ~now
    finally:
        con.close()


def test_run_loop_hydrates_the_plane_each_tick_and_is_cancellable(tmp_path):
    """The lifespan loop reads the daemon's recent captures and hydrates the plane each tick, then
    exits cleanly on cancellation (graceful shutdown)."""
    import asyncio

    _clear(TICK)
    _capture_db(tmp_path).close()

    async def _run():
        task = asyncio.create_task(
            dpf.run_daemon_plane_feed(str(tmp_path / "stream_capture.db"), interval_s=0.05))
        for _ in range(60):
            await asyncio.sleep(0.05)
            if lmp.get_quote(TICK) is not None:
                break
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert task.done()
        return lmp.get_quote(TICK)

    q = asyncio.run(_run())
    assert q is not None and q["spot"] == 712.45   # the loop hydrated the plane from the daemon db
