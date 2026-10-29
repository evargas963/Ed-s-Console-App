"""Schwab -> the tape. A print's size keeps every digit; the screen rounds it."""

from __future__ import annotations

import l1_trade_observation as l1


def test_a_print_keeps_every_digit_of_size():
    """LAST_SIZE is the count Schwab sent. Cutting it to a whole number happens on the screen,
    and the signed size on the tape is that same count."""
    first = {"LAST_PRICE": 10.0, "LAST_SIZE": 1.0, "TRADE_TIME_MILLIS": 1}
    second = {"LAST_PRICE": 11.0, "LAST_SIZE": 10.6, "TRADE_TIME_MILLIS": 2}
    printed = l1.extract_vendor_print(second)
    assert printed["size"] == 10.6
    points = l1.iter_signed_cum_points(l1.canonical_tape_prints([first, second]))
    assert points[-1][1] == 10.6
