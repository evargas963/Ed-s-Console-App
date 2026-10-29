"""Schwab -> the book. The top size keeps every digit; the screen rounds it."""

from __future__ import annotations

from app.options.order_flow import engine as ofe


def test_the_book_top_keeps_every_digit_of_size():
    """Bid size and ask size are the counts Schwab sent. The depth ladder already keeps them;
    the top does too. Cutting a size to a whole number happens on the screen, and the
    microprice is weighted by the size Schwab sent."""
    bid, ask, bid_size, ask_size = 10.0, 11.0, 10.6, 3.2
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
