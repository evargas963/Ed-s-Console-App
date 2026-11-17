"""Schwab -> the book. The top size is the count Schwab sent; the screen rounds it.

Real data: SPY's LEVELONE_EQUITIES messages of 2026-11-13 from 10:00 ET as the capture daemon
recorded them (tests/fixtures/real_spy_levelone_2026_11_13_1000et.json). Schwab streams changes,
so the top is each field's newest value, merged in order as the console holds them.
"""

from __future__ import annotations

import json
from pathlib import Path

from calc import order_flow as ofe

_MSGS = json.loads(
    (Path(__file__).parent / "fixtures" / "real_spy_levelone_2026_11_13_1000et.json").read_text(
        encoding="utf-8"
    )
)["messages"]
_FIELDS = ("BID_PRICE", "ASK_PRICE", "BID_SIZE", "ASK_SIZE")


def test_the_book_top_is_the_size_schwab_sent():
    """Bid size and ask size are the counts Schwab sent; the microprice is weighted by them.

    The top as it stood after the stream's third message: 754.30 x 600 bid, 754.32 x 40 ask,
    sizes far enough apart that a size read on the wrong side moves the microprice.
    """
    held: dict[str, float] = {}
    for m in _MSGS[:3]:
        held.update({f: m["item"][f] for f in _FIELDS if f in m["item"]})
    bid, ask = held["BID_PRICE"], held["ASK_PRICE"]
    bid_size, ask_size = held["BID_SIZE"], held["ASK_SIZE"]
    assert (bid, ask, bid_size, ask_size) == (754.3, 754.32, 600, 40)
    m = ofe.compute_book_microstructure(
        {
            "content": [],
            "top": {"bid": bid, "ask": ask, "bid_size": bid_size, "ask_size": ask_size},
        },
        now_ts=1.0,
    )
    top = m["top_of_book"]
    assert top["bid_size"] == bid_size
    assert top["ask_size"] == ask_size
    assert m["microprice"] == (bid * ask_size + ask * bid_size) / (bid_size + ask_size)
