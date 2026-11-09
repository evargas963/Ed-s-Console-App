"""Order flow reads streamed Schwab fields only: top-of-book pressure from BID_SIZE / ASK_SIZE.

Real data, each as Schwab sent it: SPY's /quotes answer of 2026-10-07 13:41 UTC
(real_schwab_quotes_watchlist_check_2026_10_07.json, its quote block), SPY's /chains underlying of
2026-10-08 (real_schwab_chain_top_level_spy_tsla_2026_10_08.json), SPY's first NYSE_BOOK of
2026-11-02 10:00 ET (real_spy_books_2026_11_02.json), and the LEVELONE_OPTIONS message of SPY's
2026-10-16 780 put of 2026-10-05 14:00:02 CT (real_stream_mix_2026_10_05_1400ct.json), taken
through the live state's one reader of a contract's top (OrderFlowState.push_option_top).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.options.order_flow.engine import _compute_top_book_pressure
from app.options.order_flow.state import OrderFlowState

_FX = Path(__file__).resolve().parent / "fixtures"


def _read(name: str) -> dict:
    return json.loads((_FX / name).read_text(encoding="utf-8"))


_REST_QUOTE = next(
    a["body"]["SPY"]
    for a in _read("real_schwab_quotes_watchlist_check_2026_10_07.json")["answers"]
    if a["ticker"] == "SPY"
)
_CHAIN_UNDERLYING = _read("real_schwab_chain_top_level_spy_tsla_2026_10_08.json")["answers"]["SPY"][
    "top_level"
]["underlying"]
_BOOK = next(r[2] for r in _read("real_spy_books_2026_11_02.json")["rows"] if r[1] == "NYSE_BOOK")
_OPTION_TOP = next(
    m["item"]
    for m in _read("real_stream_mix_2026_10_05_1400ct.json")["messages"]
    if m["service"] == "LEVELONE_OPTIONS"
    and m["item"]["key"] == "SPY   261016P00780000"
    and {"BID_SIZE", "ASK_SIZE"} <= set(m["item"])
)


def test_rest_quote_blocks_never_stand_in_for_streamed_l1():
    """REST quote blocks never stand in for streamed level one.

    2026-09-24: REST quote / extended / regular / chain-underlying and the book's top level no
    longer stand in for a missing streamed BID/ASK/MARK/size.
    """
    assert {"bidSize", "askSize", "bidPrice", "askPrice", "mark"} <= set(_REST_QUOTE["quote"])
    assert {"bidSize", "askSize", "bid", "ask"} <= set(_CHAIN_UNDERLYING)
    rest = {**_REST_QUOTE, "underlying": _CHAIN_UNDERLYING, "content": [_BOOK]}
    assert _BOOK["BIDS"] and _BOOK["ASKS"]
    assert _compute_top_book_pressure(rest) is None


def test_top_book_pressure_streaming_uses_bid_ask_size_leaves_only():
    state = OrderFlowState()
    state.push_option_top(_OPTION_TOP["key"], _OPTION_TOP)
    bid, ask = _OPTION_TOP["BID_SIZE"], _OPTION_TOP["ASK_SIZE"]
    assert (bid, ask) == (250, 149)
    top = state.option_top(_OPTION_TOP["key"])
    assert _compute_top_book_pressure({"top": top}) == (bid - ask) / (bid + ask)


def test_top_book_pressure_ignores_non_canonical_streaming_bid_ask_size_keys():
    """Streaming CSV leaves are BID_SIZE/ASK_SIZE — not REST quote.bidSize/askSize."""
    assert _compute_top_book_pressure({"content": [_REST_QUOTE["quote"]]}) is None
