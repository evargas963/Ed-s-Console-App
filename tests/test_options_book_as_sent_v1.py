"""An option contract's OPTIONS_BOOK as Schwab sent it, through the console's push ingest, read back
through the one book producer equities use. Real data: the unedited OPTIONS_BOOK and NASDAQ_BOOK
messages the capture daemon recorded (tests/fixtures/real_options_stream_history_samples.json, a SPY
and a TSLA contract; tests/fixtures/real_spy_nyse_nasdaq_books.json, SPY's equity books)."""
from __future__ import annotations

import json
from pathlib import Path

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
from app.options.order_flow.live_payload import options_live_payload
from stream_spine import book_msg

_FX = Path(__file__).parent / "fixtures"
_SAMPLES = json.loads((_FX / "real_options_stream_history_samples.json").read_text(encoding="utf-8"))["contracts"]
_EQUITY_BOOKS = json.loads((_FX / "real_spy_nyse_nasdaq_books.json").read_text(encoding="utf-8"))["books"]
UNDERLYINGS = ("SPY", "TSLA")


def _sent_books() -> "list[tuple[str, dict]]":
    """Each underlying's contract and the newest OPTIONS_BOOK Schwab sent for it."""
    out = []
    for underlying in UNDERLYINGS:
        contract = next(c for c in _SAMPLES if c["symbol"].startswith(underlying + " "))
        out.append((contract["symbol"], [e for e in contract["events"] if e["kind"] == "book"][-1]))
    return out


def _clear() -> None:
    ofs._option_streaming_last_update_ts = None
    ofs._option_contract_last_update_ts.clear()
    ofls.clear_all_live_state()
    lmp.record_feed_down()


def _push(symbol: str, service: str, event: dict) -> None:
    ofs._ingest_pushed(f"book.{symbol}", book_msg(symbol=symbol, service=service, content=event["content"],
                                                  src=event.get("source", "schwab_book"), ts_recv=event["ts_recv"]))


def test_an_option_contracts_book_lands_as_sent():
    for symbol, book in _sent_books():
        _clear()
        _push(symbol, "OPTIONS_BOOK", book)
        items = ofls.get_content_for_symbol(symbol)
        assert any(i.get("BIDS") == book["content"]["BIDS"] and i.get("ASKS") == book["content"]["ASKS"]
                   for i in items), symbol
    _clear()


def test_only_an_options_book_advances_the_contracts_freshness_clock():
    """SPY's equity NASDAQ_BOOK is never an option contract's OPTIONS_BOOK activity; the contract's
    own OPTIONS_BOOK sets its freshness to the time the daemon received it."""
    for symbol, book in _sent_books():
        _clear()
        _push("SPY", "NASDAQ_BOOK", _EQUITY_BOOKS["NASDAQ_BOOK"])
        assert symbol not in ofs._option_contract_last_update_ts
        assert ofs._option_streaming_last_update_ts is None
        _push(symbol, "OPTIONS_BOOK", book)
        assert ofs._option_contract_last_update_ts[symbol] == book["ts_recv"], symbol
    _clear()


def test_the_option_book_payload_is_the_one_book_producers():
    """compute_book_microstructure, the function the equity /api/order-flow/microstructure route
    calls, gives the contract's top-of-book imbalance."""
    for symbol, book in _sent_books():
        _clear()
        _push(symbol, "OPTIONS_BOOK", book)
        result = options_live_payload(symbol, book["ts_recv"])
        assert result["depth"]["1"]["imbalance"] is not None, symbol
    _clear()
