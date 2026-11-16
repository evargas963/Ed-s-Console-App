"""The live price every panel reads: Schwab's last trade with its time, and its mark while not live.

Read from State: the daemon's price row (live_price_rows) and the price's state (price_state).
"""

from __future__ import annotations

from typing import TypedDict

import live_market_plane as lmp
from app.options.order_flow.streaming import price_state
from live_price_rows import price_row
from time_et import age_text, ct_label

#: Precedence for the ONE spot authority. Highest wins; every entry records where the
#: number came from so a caller can never silently accept a lower-confidence source.
SPOT_SOURCE_PLANE = (
    "streaming_plane"  # live_market_plane.get_quote — the freshest real trade this process has seen
)
SPOT_SOURCE_NONE = "none"  # Schwab has sent no price


class PriceMark(TypedDict):
    """The live price's trade time and, while the price is not live, the mark beside its values."""

    spot_time_ct: str | None
    spot_not_live_text: str | None


def price_mark(ticker: str, spot_ts: float | None, now: float) -> PriceMark:
    """Return the live price's trade time and, while not live at `now` (price_state), its mark.

    Served beside every value computed from that price, so a value from a price that has stopped
    stands marked not live (AGENTS rule 5): `spot_not_live_text` is the mark the page prints
    beside each such value, with the trade's time and age, None while the price is live.
    """
    mark = ["not live"]
    if spot_ts is not None:
        mark.append(f"last trade {ct_label(spot_ts)}, {age_text(now - spot_ts)} old")
    return {
        "spot_time_ct": None if spot_ts is None else ct_label(spot_ts),
        "spot_not_live_text": (
            None if price_state(ticker, now)[0] == lmp.LIVE else " · ".join(mark)
        ),
    }


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
