"""THE displayed price row -- one producer for every price the operator sees.

Built only from live_market_plane (the per-field Schwab LEVELONE_EQUITIES state) and its feed
state (feed_live_for). Imported by the capture daemon, which pushes these rows straight to
the browser (app/market_data/schwab/streaming/live_ui.py), and by the console, whose analytics
read the same function -- so a price on screen and a price in a calculation can never come
from two different rules.

Nothing here computes a market value: every number is a Schwab field or its receive time, with
Schwab's own trade time; the only derivations are the trade age and its label. Whether the feed
is delivering the symbol now (`feed_live`) is stated beside the values. A down feed sets
`outage` and leaves the last values Schwab sent, the market open or closed
(docs/DATA_FLOW.md §2 D5).
"""
from __future__ import annotations

from typing import Any, Optional

import live_market_plane as lmp
from instrument_identity import ticker_storage_key
from time_et import ct_label

SPOT_SOURCE = "streaming_plane"


def with_change(bar: dict[str, Any]) -> dict[str, Any]:
    """`bar` with its change over the bar (close - open) and that change as a percent of the
    open: THE bar-change computation for every bar served."""
    o, c = bar.get("o"), bar.get("c")
    bar["chg"] = c - o if c is not None and o is not None else None
    bar["chg_pct"] = bar["chg"] / o * 100 if bar["chg"] is not None and o else None
    return bar


def _trade_age_sec(trade_ts: Optional[float], now: float) -> Optional[float]:
    """Seconds since the Schwab trade time; None when no trade is known (never a 0)."""
    if trade_ts is None:
        return None
    return max(0.0, now - float(trade_ts))


def price_row(ticker: str, now: float) -> dict[str, Any]:
    """The finished row the screen paints for one symbol, as it is at `now`: each field the
    last value Schwab sent. A feed down sets `outage` and `feed_live` false, the market open
    or closed; the fields stay (docs/DATA_FLOW.md §2 D5)."""
    tk = ticker_storage_key(ticker)
    outage = lmp.outage(tk, "LEVELONE_EQUITIES", now)
    row = lmp.get_quote(tk) if tk else None
    streamed = bool(row) and lmp.plane_row_is_streamed(row)
    spot = float(row["spot"]) if streamed and lmp.plane_spot_is_last_price(row) else None

    def field(name: str):
        return row.get(name) if streamed else None

    trade_ts = field("trade_ts")
    quote_ts = field("exchange_quote_ts")
    return {
        "ticker": tk,
        "spot": spot,
        "spot_disp": f"{spot:.2f}" if spot is not None else None,
        "spot_source": SPOT_SOURCE if spot is not None else None,
        # the feed itself (heartbeat, socket open, symbol held), and why the values are absent
        "feed_live": lmp.feed_live_for(tk, "LEVELONE_EQUITIES", now),
        "outage": outage,
        "bid": field("bid"),
        "ask": field("ask"),
        "bid_size": field("bid_size"),
        "ask_size": field("ask_size"),
        "mark": field("mark"),                         # Schwab MARK
        "quote_ts": quote_ts,                          # Schwab QUOTE_TIME (epoch s)
        "quote_time_ct": ct_label(quote_ts) if quote_ts is not None else None,
        "last_size": field("last_size"),
        "total_volume": field("total_volume"),
        # Schwab's own percent changes vs the prior close: NET_CHANGE_PERCENT (extended hours
        # included) and REGULAR_MARKET_CHANGE_PERCENT
        "chg_pct": field("chg_pct"),
        "chg_pct_regular": field("chg_pct_regular"),
        "net_change": field("net_change"),
        "open_price": field("open_price"),
        "high_price": field("high_price"),
        "low_price": field("low_price"),
        "prior_close": field("prior_close"),
        "trade_ts": trade_ts,                          # Schwab TRADE_TIME (epoch s)
        "trade_time_ct": ct_label(trade_ts) if trade_ts is not None else None,
        "trade_age_sec": _trade_age_sec(trade_ts, now),
        "ts_recv": row.get("server_received_ts") if row else None,
        "quote_ingestion": row.get("quote_ingestion") if row else None,
        "server_ts": now,
    }
