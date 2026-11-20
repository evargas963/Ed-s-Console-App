"""ONE FAUCET: Schwab LEVELONE trade-observation identity and signed-flow math.

Vendor contract (authenticated LEVELONE_EQUITIES, probed in RTH):
  LAST_PRICE, LAST_SIZE, TRADE_TIME_MILLIS are NATIVE last-print fields.
  SEQUENCE is absent at L1. TIMESALE_EQUITY returns code 11 (UNAVAILABLE).
  No aggressor / buy-sell / trade-condition field exists on L1, book, or REST.

TRADE_TIME_MILLIS is a vendor event clock, not a unique trade id and not
receive order. Same vendor-ms + different price or size are distinct
observations. Adjacent identical (time, price, size) is a LEVELONE
restatement/heartbeat, not a proven second print.

Local receive_seq / server_received_ts distinguish received updates. They
are not native trade identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from numeric_contract import schwab_count, schwab_number

# Source classification — mechanical, not aspirational.
TAPE_CLASSIFICATION = "PROXY_LEE_READY_L1"
TAPE_COMPLETENESS = "INCOMPLETE_OBSERVATION"

#: what the tape's pressure and cumulative delta are, shown on hover beside them
TAPE_NOTE = (
    "Estimated, not Schwab's: Schwab sends no buyer or seller side. Each last trade is signed by "
    "Lee and Ready (1991) against Schwab's bid and ask held with it: above their midpoint counts "
    "as buying, below as selling, at it the tick test (above the trade before, buying; below, "
    "selling; unchanged, the last change's side). A trade with no bid and ask, or at the "
    "midpoint before any price change, is unsigned; its share of the size is shown beside each "
    "value. On Nasdaq this method was right 81% of the time, the tick test alone 78% (Ellis, "
    "Michaely and O'Hara 2000); Finucane (2000) found the two about equal. Schwab's stream is "
    "not every trade. Pressure: signed size over the signed size in the window, -1 to +1."
)
VENDOR_TRADE_TIME = "TRADE_TIME_MILLIS"
VENDOR_LAST_PRICE = "LAST_PRICE"
VENDOR_LAST_SIZE = "LAST_SIZE"


def _schwab_int(val: Any) -> int | None:
    v = schwab_number(val)
    return int(v) if v is not None else None


def vendor_triple(
    trade_ms: Any, price: Any, size: Any
) -> tuple[int | None, float | None, float | None]:
    """Vendor last-print key. Not a native trade id."""
    return (_schwab_int(trade_ms), schwab_number(price), schwab_count(size))


def is_adjacent_restatement(
    prev: tuple[Any, ...] | None,
    curr: tuple[Any, ...],
) -> bool:
    """Return True only when the immediately previous observation equals this vendor triple."""
    return prev is not None and prev == curr


#: how each field of the last print is read, as Schwab sends it (AGENTS.md rule 2)
_PRINT_READERS = {
    VENDOR_LAST_PRICE: schwab_number,
    VENDOR_LAST_SIZE: schwab_count,
    VENDOR_TRADE_TIME: _schwab_int,
}


def last_print(item: dict[str, Any]) -> dict[str, Any]:
    """Read a LEVELONE message's last print; the one reader of its three fields.

    Each of LAST_PRICE, LAST_SIZE and TRADE_TIME_MILLIS (epoch ms) the message carries, by its
    Schwab name; one sent as no number is None. A field the message does not carry is not in it.
    """
    return {name: read(item[name]) for name, read in _PRINT_READERS.items() if name in item}


@dataclass(frozen=True)
class TradePrint:
    """A LEVELONE message's last print: its price, and its size and time (epoch ms) if sent."""

    price: float
    size: float | None
    time_millis: int | None


def extract_vendor_print(item: dict[str, Any]) -> TradePrint | None:
    """Return a LEVELONE message's last print as a trade.

    A message with no LAST_PRICE is not a trade observation (None).
    """
    sent = last_print(item)
    price = sent.get(VENDOR_LAST_PRICE)
    if price is None:
        return None
    return TradePrint(
        price=price, size=sent.get(VENDOR_LAST_SIZE), time_millis=sent.get(VENDOR_TRADE_TIME)
    )


def tick_rule_sign(prev_price: float | None, price: float | None, last: int | None) -> int | None:
    """Return the tick test's sign of a print: +1 above the price before, -1 below it.

    At an unchanged price (a zero tick) the sign of the last price change, `last` (Lee and Ready
    1991, Journal of Finance 46(2)); None while no change has been seen, or without a price to
    compare (Schwab sent none). An estimate, not Schwab's: no aggressor field exists.
    """
    if price is None or prev_price is None:
        return None
    if price > prev_price:
        return 1
    if price < prev_price:
        return -1
    return last


def trade_sign(price: float | None, bid: float | None, ask: float | None, tick: int | None):
    """Return Lee and Ready's sign of a print against the bid and ask held with it.

    +1 above their midpoint, -1 below it, at it the tick test's sign `tick` (Lee and Ready 1991,
    Journal of Finance 46(2)). None without a price, a bid or an ask: no quote, no sign.
    """
    if price is None or bid is None or ask is None:
        return None
    mid = (bid + ask) / 2.0
    if price > mid:
        return 1
    if price < mid:
        return -1
    return tick


def _signed_walk(prints: list[dict[str, Any]], cutoff_ms: float | None):
    """Walk the prints by Lee and Ready (trade_sign); THE one signed-size walk.

    Each print with a size, traded at or after `cutoff_ms` (every one when None; a print with
    no trade time cannot be placed after it), as (trade time in ms or None, size, signed size or
    None). A print before the window still sets the price and the last change the tick test of
    the first one in it reads.
    """
    prev_price: float | None = None
    last: int | None = None
    for p in prints:
        t, price, size = p.get("time_millis"), p.get("price"), p.get("size")
        tick = tick_rule_sign(prev_price, price, last)
        sign = trade_sign(price, p.get("bid"), p.get("ask"), tick)
        in_window = cutoff_ms is None or (t is not None and t >= cutoff_ms)
        if in_window and size is not None:
            yield t, size, None if sign is None else sign * float(size)
        if tick is not None:
            last = tick
        if price is not None:
            prev_price = price


def unsigned_share(prints: list[dict[str, Any]], cutoff_ms: float | None = None) -> float | None:
    """Return the share of the size traded at or after `cutoff_ms` that _signed_walk left unsigned.

    0 to 1; None when no size traded in it.
    """
    walk = list(_signed_walk(prints, cutoff_ms))
    total = sum(size for _x, size, _signed in walk)
    if total <= 0:
        return None
    return sum(size for _x, size, signed in walk if signed is None) / total


def iter_signed_cum_points(
    prints: list[dict[str, Any]], cutoff_ms: float
) -> list[tuple[float, float]]:
    """Return (trade time in seconds, cumulative signed size) at each print of the walk.

    It is for the slope of the cumulative delta: the prints traded at or after `cutoff_ms`
    (_signed_walk), each of which has a trade time.
    """
    points: list[tuple[float, float]] = []
    cum = 0.0
    for t, _size, signed in _signed_walk(prints, cutoff_ms):
        if signed is not None:
            cum += signed
        points.append((t / 1000.0, cum))
    return points


def compute_cum_delta_proxy(prints: list[dict[str, Any]]) -> float | None:
    """Sum the signed size over every print with a size (a size of 0 adds 0).

    None when no print was signed: nothing classified is no value, never 0. The prints it sums
    are cum_delta_window's.
    """
    walk = list(_signed_walk(prints, None))
    if all(signed is None for _x, _size, signed in walk):
        return None
    return sum(signed for _x, _size, signed in walk if signed is not None)


def cum_delta_window(prints: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    """(first, last) Schwab trade time, epoch seconds, of the prints compute_cum_delta_proxy sums.

    Those are the prints with a size and a trade time: the window the cumulative delta covers.
    It is
    what the tape holds -- no clock resets it -- so it is served beside the number.
    """
    times = [
        p["time_millis"] / 1000.0
        for p in prints
        if p.get("size") is not None and p.get("time_millis") is not None
    ]
    return (min(times), max(times)) if times else (None, None)


def compute_tape_pressure(
    prints: list[dict[str, Any]], window_sec: float, now_ms: float
) -> float | None:
    """Return the signed size over the size of the signed prints traded in the window.

    The window is the `window_sec` before `now_ms` (_signed_walk); None when no signed print
    traded in it. The unsigned prints' share is unsigned_share's, served beside it.
    """
    walk = [
        (size, signed)
        for _x, size, signed in _signed_walk(prints, now_ms - int(window_sec * 1000))
        if signed is not None
    ]
    total_sz = sum(size for size, _signed in walk)
    if total_sz <= 0:
        return None
    return sum(signed for _size, signed in walk) / total_sz
