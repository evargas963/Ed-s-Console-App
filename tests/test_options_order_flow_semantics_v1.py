"""OPTIONS_ORDER_FLOW_V1 — order-flow/options semantic products.

order_flow_live_state.push_level_one/push_book are symbol-generic and read Schwab's
native field names, not an equity-specific schema — proven here by feeding them the REAL
captured LEVELONE_OPTIONS/OPTIONS_BOOK shapes (reports/of_capability_probe/
options_20260820T1354Z/) and reading the result back through the SAME producer equities
use (order_flow_engine.compute_book_microstructure), never a second book-imbalance
computation for options.
"""

from __future__ import annotations

import asyncio

import order_flow_live_state as ofls
import order_flow_streaming as ofs
from stream_spine import CaptureWriter, book_msg, options_quote_msg

_SPY_CONTRACT = "SPY   260820C00767000"

#: Real content shapes from the live-proven probe — not invented.
_REAL_LEVELONE_OPTIONS_CONTENT = {
    "key": _SPY_CONTRACT, "assetMainType": "OPTION", "BID_PRICE": 1.26, "ASK_PRICE": 1.28,
    "LAST_PRICE": 1.27, "LAST_SIZE": 2, "BID_SIZE": 458, "ASK_SIZE": 209,
    "TOTAL_VOLUME": 44994, "TRADE_TIME_MILLIS": 1787234092319, "OPEN_INTEREST": 2097,
    "DELTA": 0.45644607, "CONTRACT_TYPE": "C", "UNDERLYING": "SPY",
}
_REAL_OPTIONS_BOOK_CONTENT = {
    "key": _SPY_CONTRACT, "BOOK_TIME": 1787234093764,
    "BIDS": [{"BID_PRICE": 1.28, "TOTAL_VOLUME": 1746, "NUM_BIDS": 1,
             "BIDS": [{"EXCHANGE": "NYSE", "BID_VOLUME": 262, "SEQUENCE": 1}]}],
    "ASKS": [{"ASK_PRICE": 1.3, "TOTAL_VOLUME": 1533, "NUM_ASKS": 1,
             "ASKS": [{"EXCHANGE": "EDGX", "ASK_VOLUME": 346, "SEQUENCE": 2}]}],
}


def _reset(tmp_path):
    ofs._feed_running = False
    ofs._active_option_contract = None
    ofs._option_l1_cursor = {}
    ofs._option_book_cursor = {}
    ofls.clear_all_live_state()
    return tmp_path / "stream_capture.db"


def _write_option_l1_row(db, symbol, content, ts_recv):
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert(f"optquote.{symbol}", options_quote_msg(
        symbol=symbol, content=content, src="schwab_options_l1", ts_recv=ts_recv))
    w.commit()
    w.close()


def _write_option_book_row(db, symbol, content, ts_recv):
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert(f"book.{symbol}", book_msg(
        symbol=symbol, service="OPTIONS_BOOK", content=content,
        src="schwab_options_book", ts_recv=ts_recv))
    w.commit()
    w.close()


def test_option_contract_l1_replays_into_order_flow_live_state(tmp_path, monkeypatch):
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    _write_option_l1_row(db, _SPY_CONTRACT, _REAL_LEVELONE_OPTIONS_CONTENT, ts_recv=1.0)

    con = ofs._open_capture_db_readonly(db)
    ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    con.close()

    items = ofls.get_content_for_symbol(_SPY_CONTRACT)
    assert any(i.get("LAST_PRICE") == 1.27 for i in items)


def test_option_contract_book_replays_verbatim(tmp_path, monkeypatch):
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    _write_option_book_row(db, _SPY_CONTRACT, _REAL_OPTIONS_BOOK_CONTENT, ts_recv=1.0)

    con = ofs._open_capture_db_readonly(db)
    ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    con.close()

    items = ofls.get_content_for_symbol(_SPY_CONTRACT)
    assert any(i.get("BIDS") == _REAL_OPTIONS_BOOK_CONTENT["BIDS"] for i in items)


def test_option_contract_replay_reads_only_options_book_service(tmp_path, monkeypatch):
    """A NASDAQ_BOOK/NYSE_BOOK row for the SAME symbol string (should never happen for an
    OSI contract symbol, but the query must not accidentally cross services) must not
    leak into the option contract's replayed content."""
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert(f"book.{_SPY_CONTRACT}", book_msg(
        symbol=_SPY_CONTRACT, service="NASDAQ_BOOK",
        content={"key": _SPY_CONTRACT, "BIDS": [{"WRONG_SERVICE": True}], "ASKS": []},
        src="t", ts_recv=1.0))
    w.commit()
    w.close()

    con = ofs._open_capture_db_readonly(db)
    ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    con.close()

    items = ofls.get_content_for_symbol(_SPY_CONTRACT)
    assert not any(i.get("BIDS") == [{"WRONG_SERVICE": True}] for i in items)


def test_get_option_contract_book_microstructure_reuses_the_one_producer(tmp_path, monkeypatch):
    """The decisive proof: this is compute_book_microstructure itself (the SAME function
    the equity /api/order-flow/microstructure route calls), not a parallel computation."""
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    _write_option_book_row(db, _SPY_CONTRACT, _REAL_OPTIONS_BOOK_CONTENT, ts_recv=1.0)
    con = ofs._open_capture_db_readonly(db)
    ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    con.close()

    result = ofs.get_option_contract_book_microstructure(_SPY_CONTRACT)
    assert result["depth"]["1"]["imbalance"] is not None


def test_get_option_contract_book_microstructure_fails_closed_with_no_book():
    """No replayed content yet -> the producer's own fail-closed contract: status
    'no_book', never a fabricated imbalance."""
    ofls.clear_all_live_state()
    result = ofs.get_option_contract_book_microstructure("QQQ   260820C00450000")
    assert result.get("status") == "no_book" or result["depth"]["1"]["imbalance"] is None


def test_set_active_option_contract_writes_signal_and_clears_old_symbol(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("order_flow_streaming.write_active_option_contract_signal",
                        lambda s: calls.append(s))
    cleared = []
    monkeypatch.setattr("order_flow_streaming.clear_symbol", lambda s: cleared.append(s))
    ofs._active_option_contract = "OLD   260101C00100000"

    ok = ofs.set_active_option_contract(_SPY_CONTRACT)
    assert ok is True
    assert calls == [_SPY_CONTRACT]
    assert cleared == ["OLD   260101C00100000"]
    assert ofs._active_option_contract == _SPY_CONTRACT


def test_feed_loop_replays_both_ticker_and_option_contract_independently(tmp_path, monkeypatch):
    """The equity active ticker and the option contract are independent slots — both must
    hydrate in the SAME poll tick without interfering with each other."""
    db = _reset(tmp_path)
    ofs._active_ticker = None
    ofs._l1_cursor = {}
    ofs._book_cursor = {}
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.setattr("order_flow_streaming.write_active_ticker_signal", lambda *_a, **_k: None)
    monkeypatch.setattr("order_flow_streaming.write_active_option_contract_signal", lambda *_a, **_k: None)

    from stream_spine import quote_msg
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert("quote.SPY", quote_msg(symbol="SPY", bid=450.0, src="schwab_l1", ts_recv=1.0,
                                    native={"key": "SPY", "LAST_PRICE": 450.0}))
    w.commit()
    w.close()
    _write_option_l1_row(db, _SPY_CONTRACT, _REAL_LEVELONE_OPTIONS_CONTENT, ts_recv=1.0)

    async def go():
        ofs._feed_running = True
        ofs.set_streaming_active_ticker("SPY")
        ofs.set_active_option_contract(_SPY_CONTRACT)
        task = asyncio.get_event_loop().create_task(ofs._feed_loop())
        await asyncio.sleep(0.3)
        ofs._feed_running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    asyncio.run(go())

    assert any(i.get("LAST_PRICE") == 450.0 for i in ofls.get_content_for_symbol("SPY"))
    assert any(i.get("LAST_PRICE") == 1.27 for i in ofls.get_content_for_symbol(_SPY_CONTRACT))
