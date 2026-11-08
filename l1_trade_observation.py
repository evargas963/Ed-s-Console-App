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

from typing import Any

from numeric_contract import schwab_count, schwab_number

# Source classification — mechanical, not aspirational.
NATIVE_AGGRESSOR_AVAILABLE = False
TAPE_CLASSIFICATION = "PROXY_RECONSTRUCTED_L1_TICK"
TAPE_COMPLETENESS = "INCOMPLETE_OBSERVATION"

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
    """True only when the immediately previous observation equals this vendor triple."""
    return prev is not None and prev == curr


def extract_vendor_print(item: dict[str, Any]) -> dict[str, Any] | None:
    """The one reader of a LEVELONE message's last print (LAST_PRICE, LAST_SIZE,
    TRADE_TIME_MILLIS), each by rule 2: {price, size, time_millis}. Missing LAST_PRICE is not a
    trade observation (None)."""
    price = schwab_number(item.get(VENDOR_LAST_PRICE))
    if price is None:
        return None
    return {
        "price": price,
        "size": schwab_count(item.get(VENDOR_LAST_SIZE)),
        "time_millis": _schwab_int(item.get(VENDOR_TRADE_TIME)),
    }


def canonical_tape_prints(content_items: list) -> list[dict[str, Any]]:
    """The tape's prints among `content_items` (each one the live state recorded: a genuinely
    new print, an adjacent restatement never recorded), in receive order. Never sorts by
    TRADE_TIME_MILLIS: out-of-order vendor clocks stay in receive order."""
    return [item for item in content_items if isinstance(item, dict)]


def tick_rule_signed_size(
    prev_price: float | None,
    price: float | None,
    size: float | None,
) -> float | None:
    """PROXY tick-rule signed size. Not native aggressor. None without a size or a price to
    compare (Schwab sent none); a size of 0 signs 0."""
    if size is None or price is None or prev_price is None:
        return None
    if price > prev_price:
        return float(size)
    if price < prev_price:
        return -float(size)
    return 0.0


def _signed_walk(prints: list[dict[str, Any]], cutoff_ms: float | None):
    """THE one tick-rule walk: each print with a size, traded at or after `cutoff_ms` (every
    one when None; a print with no trade time cannot be placed after it), as (x, size, signed
    size or None). x is the trade time in seconds, else the receive index (not a trade id). A
    print before the window still sets the price the first one in it is signed against."""
    prev_price: float | None = None
    for i, p in enumerate(prints):
        t, price, size = p.get("time_millis"), p.get("price"), p.get("size")
        in_window = cutoff_ms is None or (t is not None and t >= cutoff_ms)
        if in_window and size is not None:
            x = float(i) if t is None else t / 1000.0
            yield x, size, tick_rule_signed_size(prev_price, price, size)
        if price is not None:
            prev_price = price


def iter_signed_cum_points(
    prints: list[dict[str, Any]],
    window_sec: float | None = None,
    now_ms: float | None = None,
) -> list[tuple[float, float]]:
    """The cumulative signed size at each print of the walk (_signed_walk), for CVD and its
    slope; with a window, the prints traded in the `window_sec` before `now_ms`."""
    cutoff = None if window_sec is None else now_ms - int(window_sec * 1000)
    points: list[tuple[float, float]] = []
    cum = 0.0
    for x, _size, signed in _signed_walk(prints, cutoff):
        if signed is not None:
            cum += signed
        points.append((x, cum))
    return points


def compute_cum_delta_proxy(prints: list[dict[str, Any]]) -> float | None:
    """The tick-rule signed size summed over every print with a size (a size of 0 adds 0);
    None when no print carried one. The prints it sums are cum_delta_window's."""
    points = iter_signed_cum_points(prints)
    if not points:
        return None
    return points[-1][1]


def cum_delta_window(prints: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    """(first, last) Schwab trade time, epoch seconds, of the prints compute_cum_delta_proxy
    sums (those with a size and a trade time): the window the cumulative delta covers. It is
    what the tape holds -- no clock resets it -- so it is served beside the number."""
    times = [
        p["time_millis"] / 1000.0
        for p in prints
        if p.get("size") is not None and p.get("time_millis") is not None
    ]
    return (min(times), max(times)) if times else (None, None)


def compute_tape_pressure(
    prints: list[dict[str, Any]], window_sec: float, now_ms: float
) -> float | None:
    """Tick-rule signed size over total size for the prints traded in the `window_sec` before
    `now_ms` (_signed_walk); None when none traded in it."""
    walk = list(_signed_walk(prints, now_ms - int(window_sec * 1000)))
    total_sz = sum(size for _x, size, _signed in walk)
    if total_sz <= 0:
        return None
    return sum(signed for _x, _size, signed in walk if signed is not None) / total_sz
