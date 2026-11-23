"""The live price every panel computes from: the price row's, Schwab's last trade with its time.

Read from State: the daemon's price row (live_price_rows), the one producer of the live price,
and the price's state (price_state). A panel computes from it; no panel serves the price, its
time or whether it is live: the page draws those from the price row itself (ed-core.js,
paintLivePrice).
"""

from __future__ import annotations

from app.options.order_flow.streaming import price_state
from live_price_rows import price_row

#: Precedence for the ONE spot authority. Highest wins; every entry records where the
#: number came from so a caller can never silently accept a lower-confidence source.
SPOT_SOURCE_PLANE = (
    "streaming_plane"  # live_market_plane.get_quote — the freshest real trade this process has seen
)
SPOT_SOURCE_NONE = "none"  # Schwab has sent no price


def resolve_spot(ticker: str, *, now: float) -> tuple[float | None, str, float | None]:
    """(spot, source, as_of_ts_utc): the daemon's price row's Schwab LAST_PRICE as sent.

    With its trade time. Why it is not live (price_state) does not remove it; the number stays.
    (None, the outage reason or SPOT_SOURCE_NONE, None) until Schwab has sent one.
    """
    row = price_row(ticker, now)
    if row["spot"] is not None:
        return row["spot"], SPOT_SOURCE_PLANE, row["trade_ts"]
    outage = price_state(ticker, now)[1]
    if outage is None:
        return None, SPOT_SOURCE_NONE, None
    return None, outage, None
