"""ONE FAUCET: Schwab LEVELONE trade-observation identity and signed-flow math.

Vendor contract (authenticated LEVELONE_EQUITIES, probed in RTH):
  LAST_PRICE, LAST_SIZE, TRADE_TIME_MILLIS are NATIVE last-print fields.
  SEQUENCE is absent at L1. TIMESALE_EQUITY returns code 11 (UNAVAILABLE).
  No aggressor / buy-sell / trade-condition field exists on L1, book, or REST.

TRADE_TIME_MILLIS is a vendor event clock, not a unique trade id and not
receive order. Same vendor-ms + different price or size are distinct
observations. Schwab streams LEVELONE as Change (Streamer API §1.5): only the
fields that changed, so a new trade changes at least one of the three, and a
second trade identical in all three changes none and is not sent (its only
trace, TOTAL_VOLUME, also moves alone for trades that set no last price). An
adjacent identical (time, price, size) is a restatement: a subscription's whole
record, or the bus's merged record re-sent on a quote change
(docs/derived_register.md, "A print on the tape").

The receive time kept with a print (KeptPrint.server_received_ts) distinguishes
received updates. It is not native trade identity.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, NamedTuple

from numeric_contract import schwab_count, schwab_number
from option_contract import NO_TOP, StreamedTop
from time_et import et_date_str_from_ts_utc

#: what the tape's pressure and cumulative delta are, shown on hover beside them
TAPE_NOTE = (
    "Estimated, not Schwab's: Schwab sends no buyer or seller side. Each last trade is signed by "
    "Lee and Ready (1991) against Schwab's bid and ask in force when it traded, the newest quote "
    "Schwab timed at or before the trade: above their midpoint counts "
    "as buying, below as selling, at it the tick test (above the trade before, buying; below, "
    "selling; unchanged, the last change's side). A trade with no such bid and ask, or at the "
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


#: how each field of the last print is read, as Schwab sends it (AGENTS.md rule 2)
_PRINT_READERS = {
    VENDOR_LAST_PRICE: schwab_number,
    VENDOR_LAST_SIZE: schwab_count,
    VENDOR_TRADE_TIME: _schwab_int,
}
#: a print's three fields: a new value of any makes a new print
PRINT_FIELDS = tuple(_PRINT_READERS)


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


class KeptPrint(NamedTuple):
    """A print as the tape keeps it (app.options.order_flow.history.quoted), in receive order.

    The trade Schwab sent (a TradePrint's three values); when the daemon received the message
    that carried it; the bid and ask in force when it traded, with their sizes (quote_in_force);
    the record's streamed volume, volatility and delta then; and where the trade landed against
    that bid and ask (history.quoted's own words: a comparison, never a buy or a sell).
    """

    price: float
    size: float | None
    time_millis: int | None
    server_received_ts: float
    bid: float | None
    bid_size: float | None
    ask: float | None
    ask_size: float | None
    volume: float | None
    iv: float | None
    delta: float | None
    landed: str


def is_adjacent_restatement(prev: KeptPrint | None, trade: TradePrint) -> bool:
    """Return whether `trade` restates `prev`, the print kept just before it (None: none kept).

    The same time, price and size: Schwab's last-print values, not a native trade id.
    """
    return prev is not None and (prev.time_millis, prev.price, prev.size) == (
        trade.time_millis,
        trade.price,
        trade.size,
    )


def quote_in_force(trade_ms: int | None, top: StreamedTop, before: StreamedTop) -> StreamedTop:
    """Return the quote in force when a trade was made: the newest Schwab timed at or before it.

    `top` and `before` are the quotes the record held when the trade came, its newest then and the
    one that one replaced (stream_spine.quotes_at_trade), each timed by Schwab's
    QUOTE_TIME_MILLIS; `trade_ms` is the trade's TRADE_TIME_MILLIS. Schwab's update carries a
    trade with the quote that followed it ("quotes may be recorded ahead of trades that triggered
    them", Lee and Ready 1991), so the newest quote is the trade's only when Schwab timed it no
    later than the trade. A quote Schwab timed on an earlier ET date than the trade is not in
    force either: the market closes between ET dates (no window Schwab's /markets sends crosses
    midnight ET), so the last quote before a close was replaced, unseen, before the first trade
    after it. NO_TOP when the trade has no time or neither quote qualifies: no quote in force is
    known, and a later one is never used.
    """
    if trade_ms is not None:
        day = et_date_str_from_ts_utc(trade_ms / 1000.0)
        for quote in (top, before):
            timed = quote.quote_time_ms
            if timed is None or timed > trade_ms:
                continue
            if et_date_str_from_ts_utc(timed / 1000.0) == day:
                return quote
    return NO_TOP


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
    """Return Lee and Ready's sign of a print against the bid and ask in force when it traded.

    They are the ones kept with the print (quote_in_force). +1 above their midpoint, -1 below it,
    at it the tick test's sign `tick` (Lee and Ready 1991, Journal of Finance 46(2)). None
    without a price, a bid or an ask: no quote, no sign.
    """
    if price is None or bid is None or ask is None:
        return None
    mid = (bid + ask) / 2.0
    if price > mid:
        return 1
    if price < mid:
        return -1
    return tick


#: a print of the walk: (its trade time in ms, its size, its signed size or None)
type _Walked = tuple[float, float, float | None]


def _signed_walk(prints: list[KeptPrint], cutoff_ms: float | None) -> Iterator[_Walked]:
    """Walk the prints by Lee and Ready (trade_sign); THE one signed-size walk.

    Each print with a size and a trade time, traded at or after `cutoff_ms` (every one when
    None), as (trade time in ms, size, signed size or None). A print with no trade time is in no
    walk: it cannot be placed in a window, and the cumulative delta sums the prints its window
    names (operator 2026-11-24). A print outside the walk still sets the price and the last
    change the tick test of the next one reads.
    """
    prev_price: float | None = None
    last: int | None = None
    for p in prints:
        t, size = p.time_millis, p.size
        tick = tick_rule_sign(prev_price, p.price, last)
        sign = trade_sign(p.price, p.bid, p.ask, tick)
        if t is not None and size is not None and (cutoff_ms is None or t >= cutoff_ms):
            yield t, size, None if sign is None else sign * float(size)
        if tick is not None:
            last = tick
        prev_price = p.price


def unsigned_share(prints: list[KeptPrint], cutoff_ms: float | None = None) -> float | None:
    """Return the share of the size traded at or after `cutoff_ms` that _signed_walk left unsigned.

    0 to 1; None when no size traded in it.
    """
    walk = list(_signed_walk(prints, cutoff_ms))
    total = sum(size for _x, size, _signed in walk)
    if total <= 0:
        return None
    return sum(size for _x, size, signed in walk if signed is None) / total


def iter_signed_cum_points(prints: list[KeptPrint], cutoff_ms: float) -> list[tuple[float, float]]:
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


def compute_cum_delta_proxy(prints: list[KeptPrint]) -> float | None:
    """Sum the signed size over every print with a size and a trade time (a size of 0 adds 0).

    None when no print was signed: nothing classified is no value, never 0. The prints it sums
    are cum_delta_window's (_signed_walk).
    """
    walk = list(_signed_walk(prints, None))
    if all(signed is None for _x, _size, signed in walk):
        return None
    return sum(signed for _x, _size, signed in walk if signed is not None)


def cum_delta_window(prints: list[KeptPrint]) -> tuple[float | None, float | None]:
    """(first, last) Schwab trade time, epoch seconds, of the prints compute_cum_delta_proxy sums.

    Those are the prints with a size and a trade time: the window the cumulative delta covers.
    It is
    what the tape holds -- no clock resets it -- so it is served beside the number.
    """
    times = [
        p.time_millis / 1000.0 for p in prints if p.size is not None and p.time_millis is not None
    ]
    return (min(times), max(times)) if times else (None, None)


def compute_tape_pressure(
    prints: list[KeptPrint], window_sec: float, now_ms: float
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
