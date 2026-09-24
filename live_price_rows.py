"""THE displayed price row -- one producer for every price the operator sees.

Built only from live_market_plane (the per-field Schwab LEVELONE_EQUITIES state) and its feed
liveness (feed_live_for). Imported by the capture daemon, which pushes these rows straight to
the browser (app/market_data/schwab/streaming/live_ui.py), and by the console, whose analytics
read the same function -- so a price on screen and a price in a calculation can never come
from two different rules.

Nothing here computes a market value: every number is a Schwab field or its receive time; the
only derivations are the live verdict, the trade age, and the forming 1-minute candle (the OHLC
of the LAST_PRICEs whose Schwab TRADE_TIME falls in the current minute).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

import live_market_plane as lmp
from instrument_identity import ticker_storage_key

SPOT_SOURCE = "streaming_plane"

_forming_lock = threading.Lock()
#: ticker -> the forming 1m candle {t, o, h, l, c} from streamed LAST_PRICE / TRADE_TIME
_forming: dict[str, dict[str, Any]] = {}
#: ticker -> the spot_received_ts already folded into its forming candle (one trade, once)
_forming_seen: dict[str, float] = {}


def live_spot(ticker: str) -> Optional[float]:
    """The streamed LAST_PRICE while the feed is live for the symbol, else None. THE spot."""
    row = lmp.get_quote(ticker)
    if (row and lmp.plane_spot_is_last_price(row) and lmp.plane_row_is_streamed(row)
            and lmp.spot_is_fresh(row)):
        return float(row["spot"])
    return None


def _note_trade(ticker: str) -> None:
    """Row listener: fold a NEW LAST_PRICE into its minute's forming candle."""
    row = lmp.get_quote(ticker)
    if not row or row.get("spot") is None or row.get("trade_ts") is None:
        return
    received = row.get("spot_received_ts")
    t = row["ticker"]
    with _forming_lock:
        if received is not None and _forming_seen.get(t) == received:
            return                      # a bid/ask-only change: no new trade
        _forming_seen[t] = received
        px = float(row["spot"])
        ts = float(row["trade_ts"])     # epoch SECONDS (the plane converts TRADE_TIME_MILLIS)
        minute = ts - (ts % 60.0)
        bar = _forming.get(t)
        if bar is None or minute > bar["t"]:
            _forming[t] = {"t": minute, "o": px, "h": px, "l": px, "c": px, "forming": True}
        elif minute == bar["t"]:
            bar["h"] = max(bar["h"], px)
            bar["l"] = min(bar["l"], px)
            bar["c"] = px
        # a trade stamped in an EARLIER minute than the forming one is late: it never
        # reopens a closed minute


lmp.add_row_listener(_note_trade)


def forming_bar(ticker: str) -> Optional[dict[str, Any]]:
    t = ticker_storage_key(ticker)
    with _forming_lock:
        bar = _forming.get(t)
        return dict(bar) if bar else None


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

    return {
        "ticker": tk,
        "spot": spot,
        "spot_disp": f"{spot:.2f}" if spot is not None else None,
        "spot_state": "live" if spot is not None else "unavailable",
        "spot_source": SPOT_SOURCE if spot is not None else None,
        # the feed itself (heartbeat, socket open, symbol held) -- distinct from "this symbol
        # has traded this session": live feed + no trade yet reads NO TRADE YET, not no feed
        "feed_live": lmp.feed_live_for(tk),
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
        "forming_1m": forming_bar(tk) if spot is not None else None,
        "ts_recv": row.get("server_received_ts") if row else None,
        "quote_ingestion": row.get("quote_ingestion") if row else None,
        "server_ts": now,
    }
