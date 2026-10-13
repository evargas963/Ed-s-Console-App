"""ONE FAUCET: Schwab LEVELONE trade-observation identity and signed-flow math.

Vendor contract (authenticated LEVELONE_EQUITIES, RTH probe 2026-08-20):
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

from typing import Any, Optional

from numeric_contract import schwab_count, schwab_number

# Source classification — mechanical, not aspirational.
NATIVE_AGGRESSOR_AVAILABLE = False
TAPE_CLASSIFICATION = "PROXY_RECONSTRUCTED_L1_TICK"


def _schwab_int(val: Any) -> Optional[int]:
    v = schwab_number(val)
    return int(v) if v is not None else None


def vendor_triple(
    trade_ms: Any, price: Any, size: Any
) -> tuple[Optional[int], Optional[float], Optional[float]]:
    """Vendor last-print key. Not a native trade id."""
    return (_schwab_int(trade_ms), schwab_number(price), schwab_count(size))


def is_adjacent_restatement(
    prev: Optional[tuple[Any, ...]],
    curr: tuple[Any, ...],
) -> bool:
    """True only when the immediately previous observation equals this vendor triple."""
    return prev is not None and prev == curr


def tick_rule_signed_size(
    prev_price: Optional[float],
    price: Optional[float],
    size: Optional[int],
) -> Optional[float]:
    """PROXY tick-rule signed size. Not native aggressor. None without a size or a price to
    compare (Schwab sent none); a size of 0 signs 0."""
    if size is None or price is None or prev_price is None:
        return None
    if price > prev_price:
        return float(size)
    if price < prev_price:
        return -float(size)
    return 0.0


def iter_signed_cum_points(
    prints: list[dict[str, Any]],
    window_sec: Optional[float] = None,
    now_ms: Optional[float] = None,
) -> list[tuple[float, float]]:
    """ONE signed-size walk. x is vendor seconds when present, else receive index.

    Receive index is not a native trade id. Used by CVD and CVD-slope only. With a window, only
    prints whose trade time is within `window_sec` before `now_ms` count; a print with no time
    cannot be placed in the window and is left out.
    """
    cutoff = None if window_sec is None else now_ms - int(window_sec * 1000)
    points: list[tuple[float, float]] = []
    cum = 0.0
    prev_price: Optional[float] = None
    for i, p in enumerate(prints):
        t = p.get("time_millis")
        price = p.get("price")
        if cutoff is not None and (t is None or t < cutoff):
            if price is not None:
                prev_price = price
            continue
        size = p.get("size")
        if size is None:
            if price is not None:
                prev_price = price
            continue
        signed = tick_rule_signed_size(prev_price, price, size)
        if signed is not None:
            cum += signed
        if price is not None:
            prev_price = price
        if t is not None:
            x = t / 1000.0
        else:
            x = float(i)
        points.append((x, cum))
    return points


def compute_cum_delta_proxy(prints: list[dict[str, Any]]) -> Optional[float]:
    """The tick-rule signed size summed over every print with a size (a size of 0 adds 0);
    None when no print carried one. The prints it sums are cum_delta_window's."""
    points = iter_signed_cum_points(prints)
    if not points:
        return None
    return points[-1][1]


def cum_delta_window(prints: list[dict[str, Any]]) -> tuple[Optional[float], Optional[float]]:
    """(first, last) Schwab trade time, epoch seconds, of the prints compute_cum_delta_proxy
    sums (those with a size and a trade time): the window the cumulative delta covers. It is
    what the tape holds -- no clock resets it -- so it is served beside the number."""
    times = [p["time_millis"] / 1000.0 for p in prints
             if p.get("size") is not None and p.get("time_millis") is not None]
    return (min(times), max(times)) if times else (None, None)


def compute_tape_pressure(
    prints: list[dict[str, Any]], window_sec: float, now_ms: float
) -> Optional[float]:
    """Tick-rule signed size over total size for the prints traded in the `window_sec` before
    `now_ms`; None when none traded in it. A print with no trade time is left out."""
    cutoff_ms = now_ms - int(window_sec * 1000)
    total_delta = 0.0
    total_sz = 0
    prev_price: Optional[float] = None
    for p in prints:
        t = p.get("time_millis")
        price = p.get("price")
        if t is None or t < cutoff_ms:
            if price is not None:
                prev_price = price
            continue
        size = p.get("size")
        if size is None or size <= 0:
            if price is not None:
                prev_price = price
            continue
        signed = tick_rule_signed_size(prev_price, price, size)
        if signed is not None:
            total_delta += signed
        total_sz += size
        if price is not None:
            prev_price = price
    if total_sz <= 0:
        return None
    return total_delta / total_sz

