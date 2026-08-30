"""SINGLE-STREAM-AUTHORITY root fix — end-to-end proof that the live plane hydrates from
rows the canonical capture daemon ALREADY wrote, with zero Schwab connection of its own.

This is the seam that used to be a second `schwab.streaming.StreamClient`. These tests
drive the REAL CaptureWriter (what the daemon calls) and the REAL replay path
(order_flow_streaming._replay_new_rows / _feed_loop), never a synthetic shortcut.
"""

from __future__ import annotations

import ast
import asyncio
import inspect

import order_flow_streaming as ofs
import order_flow_live_state as ofls
from stream_spine import CaptureWriter, book_msg, quote_msg


def _reset(tmp_path):
    ofs._feed_running = False
    ofs._active_ticker = None
    ofs._streaming_last_update_ts = None
    ofs._last_subscribe_completed_ts = None
    ofs._l1_cursor = {}
    ofs._book_cursor = {}
    ofls.clear_all_live_state()
    return tmp_path / "stream_capture.db"


def _write_l1_row(db, symbol, native, ts_recv):
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert(f"quote.{symbol}", quote_msg(symbol=symbol, bid=native.get("BID_PRICE"),
                                          src="schwab_l1", ts_recv=ts_recv, native=native))
    w.commit()
    w.close()


def _write_book_row(db, symbol, content, ts_recv):
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert(f"book.{symbol}", book_msg(symbol=symbol, service="NASDAQ_BOOK", content=content,
                                        src="schwab_book", ts_recv=ts_recv))
    w.commit()
    w.close()


def test_no_schwab_import_anywhere_in_this_module():
    """THE root fix, structurally: this module must not be ABLE to open a Schwab
    session — not merely choose not to. An `import schwab` statement here (not prose
    mentioning the word — the docstring explains the repair using it) is the violation."""
    tree = ast.parse(inspect.getsource(ofs))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[0] == "schwab" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "schwab"


def test_l1_row_replays_into_both_planes(tmp_path, monkeypatch):
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    native = {"key": "SPY", "BID_PRICE": 449.98, "ASK_PRICE": 450.02, "LAST_PRICE": 450.0,
             "LAST_SIZE": 100, "TRADE_TIME_MILLIS": 1000, "TOTAL_VOLUME": 5000}
    _write_l1_row(db, "SPY", native, ts_recv=1.0)

    con = ofs._open_capture_db_readonly(db)
    ofs._replay_new_rows(con, "SPY")
    con.close()

    top = ofls.get_content_for_symbol("SPY")
    assert any(item.get("LAST_PRICE") == 450.0 for item in top)
    import live_market_plane as lmp
    assert lmp.get_quote("SPY")["spot"] == 450.0


def test_replay_cursor_never_reprocesses_the_same_row(tmp_path, monkeypatch):
    """Prevents duplicate tape prints / duplicate live_market_plane generations from one
    row surviving across two poll ticks."""
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    native = {"key": "SPY", "LAST_PRICE": 450.0, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 1}
    _write_l1_row(db, "SPY", native, ts_recv=1.0)

    con = ofs._open_capture_db_readonly(db)
    ofs._replay_new_rows(con, "SPY")
    ofs._replay_new_rows(con, "SPY")   # second tick, no new rows
    con.close()

    tape = ofls.get_content_for_symbol("SPY")
    prints = [x for x in tape if "LAST_PRICE" in x and "BIDS" not in x]
    assert len(prints) == 1


def test_book_row_replays_verbatim(tmp_path, monkeypatch):
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    content = {"key": "SPY", "BIDS": [{"BID_PRICE": 449.9, "BID_SIZE": 100}],
              "ASKS": [{"ASK_PRICE": 450.1, "ASK_SIZE": 200}], "BOOK_TIME": 555}
    _write_book_row(db, "SPY", content, ts_recv=1.0)

    con = ofs._open_capture_db_readonly(db)
    ofs._replay_new_rows(con, "SPY")
    con.close()

    items = ofls.get_content_for_symbol("SPY")
    assert any(i.get("BIDS") == content["BIDS"] for i in items)


def test_mismatched_ticker_rows_are_not_replayed(tmp_path, monkeypatch):
    """The daemon captures its whole roster; the feed must only replay the ONE symbol
    it was told is active — otherwise QQQ ticks would corrupt SPY's live state."""
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    _write_l1_row(db, "QQQ", {"key": "QQQ", "LAST_PRICE": 380.0}, ts_recv=1.0)

    con = ofs._open_capture_db_readonly(db)
    ofs._replay_new_rows(con, "SPY")
    con.close()

    # order_flow_live_state's clear() zeroes _top's dict value rather than deleting the
    # key (pre-existing behavior, unrelated to this repair), so a bare `== []` is not the
    # right invariant — assert the thing that would actually indicate cross-symbol leakage:
    # the QQQ row's price must not appear anywhere in SPY's replayed content.
    items = ofls.get_content_for_symbol("SPY")
    assert not any(i.get("LAST_PRICE") == 380.0 for i in items)
    # QQQ's own row was never replayed either (only "SPY" was passed to _replay_new_rows) —
    # confirms the mismatch was "wrong symbol filtered out", not "nothing ran at all".
    con2 = ofs._open_capture_db_readonly(db)
    ofs._replay_new_rows(con2, "QQQ")
    con2.close()
    assert any(i.get("LAST_PRICE") == 380.0 for i in ofls.get_content_for_symbol("QQQ"))


def test_missing_capture_db_is_handled_not_fatal(tmp_path, monkeypatch):
    """Cold start: the daemon has not created stream_capture.db yet. The feed must
    tolerate this (retry next tick), never crash the server's lifespan startup."""
    db = tmp_path / "does_not_exist.db"
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    assert ofs._open_capture_db_readonly(db) is None


def test_authority_is_streaming_after_replay_and_active_ticker_set(tmp_path, monkeypatch):
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.setattr("stream_spine.write_active_ticker_signal", lambda *_a, **_k: None)
    ofs._feed_running = True
    ofs.set_streaming_active_ticker("SPY")
    _write_l1_row(db, "SPY", {"key": "SPY", "LAST_PRICE": 450.0}, ts_recv=1.0)

    con = ofs._open_capture_db_readonly(db)
    ofs._replay_new_rows(con, "SPY")
    con.close()

    assert ofs.get_plane_authority_for_ticker("SPY") == "streaming"
    assert ofs.get_plane_authority_for_ticker("QQQ") == "rest_mismatch"


def test_set_active_ticker_writes_the_daemon_signal(tmp_path, monkeypatch):
    """This is the ONLY channel by which this module influences the daemon's
    subscriptions — proves the write actually happens, not just that no error is raised."""
    calls = []
    monkeypatch.setattr("order_flow_streaming.write_active_ticker_signal",
                        lambda t: calls.append(t))
    ofs._active_ticker = None
    ofs.set_streaming_active_ticker("spy")
    assert calls == ["SPY"]


def test_feed_loop_starts_and_stops_cleanly(tmp_path, monkeypatch):
    """start_order_flow_stream/stop_order_flow_stream must work with NO Schwab client
    (None) — the whole point of the repair is that this feed needs no account/session."""
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.setattr("stream_spine.write_active_ticker_signal", lambda *_a, **_k: None)

    async def go():
        ok = ofs.start_order_flow_stream(None, None, "SPY")
        assert ok is True
        assert ofs.is_order_flow_stream_running() is True
        await asyncio.sleep(0.05)
        ofs.stop_order_flow_stream(join_timeout=1.0)
        assert ofs.is_order_flow_stream_running() is False
    asyncio.run(go())
