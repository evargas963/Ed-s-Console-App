"""THE displayed price row -- one producer for every price the operator sees.

Built only from live_market_plane (the per-field Schwab LEVELONE_EQUITIES state) and its feed
liveness (feed_live_for). Imported by the capture daemon, which pushes these rows straight to
the browser (app/market_data/schwab/streaming/live_ui.py), and by the console, whose analytics
read the same function -- so a price on screen and a price in a calculation can never come
from two different rules.

Nothing here computes a market value: every number is a Schwab field or its receive time; the
only derivations are the live verdict and the trade age.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import live_market_plane as lmp
from instrument_identity import ticker_storage_key
from time_et import ct_label, is_capturable_session

SPOT_SOURCE = "streaming_plane"


def live_spot(ticker: str) -> Optional[float]:
    """The streamed LAST_PRICE while the feed is live for the symbol, else None. THE spot."""
    row = lmp.get_quote(ticker)
    if (row and lmp.plane_spot_is_last_price(row) and lmp.plane_row_is_streamed(row)
            and lmp.spot_is_fresh(row)):
        return float(row["spot"])
    return None


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
    return round(max(0.0, now - float(trade_ts)), 1)


def price_row(ticker: str) -> dict[str, Any]:
    """The finished row the screen paints for one symbol, as it is this instant."""
    tk = ticker_storage_key(ticker)
    row = lmp.get_quote(tk)
    spot = live_spot(tk)
    quote_live = bool(row) and lmp.quote_is_fresh(row)
    now = time.time()
    trade_ts = row["trade_ts"] if row and spot is not None and "trade_ts" in row else None

    def field(name: str):
        return row[name] if quote_live and name in row else None

    closed = not is_capturable_session()
    last = (row if closed and row and lmp.plane_spot_is_last_price(row)
            and lmp.plane_row_is_streamed(row) and row.get("trade_ts") is not None else None)

    return {
        "ticker": tk,
        "spot": spot,
        "spot_disp": f"{spot:.2f}" if spot is not None else None,
        "spot_state": "live" if spot is not None else ("closed" if closed else "unavailable"),
        "spot_source": SPOT_SOURCE if spot is not None else None,
        # the feed itself (heartbeat, socket open, symbol held) -- distinct from "this symbol
        # has traded this session": live feed + no trade yet reads NO TRADE YET, not no feed
        "feed_live": lmp.feed_live_for(tk),
        # market closed: the last streamed trade, a past observation labelled with its time
        "closed_last": {"spot_disp": f"{float(last['spot']):.2f}", "as_of": ct_label(last["trade_ts"])}
                       if last else None,
        "bid": field("bid"),
        "ask": field("ask"),
        "bid_size": field("bid_size"),
        "ask_size": field("ask_size"),
        "last_size": field("last_size") if spot is not None else None,
        "total_volume": field("total_volume"),
        "chg_pct": lmp.streamed_chg_pct(row),
        "net_change": field("net_change") if spot is not None else None,
        "open_price": field("open_price"),
        "high_price": field("high_price"),
        "low_price": field("low_price"),
        "prior_close": field("prior_close"),
        "trade_ts": trade_ts,
        "trade_age_sec": _trade_age_sec(trade_ts, now),
        "ts_recv": row.get("server_received_ts") if row else None,
        "quote_ingestion": row.get("quote_ingestion") if row else None,
        "server_ts": now,
    }
