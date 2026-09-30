"""THE displayed price row and THE chart bar -- one producer for every price the operator sees.

Built only from live_market_plane (the per-field Schwab LEVELONE_EQUITIES state) and its feed
liveness (feed_live_for), and from Schwab's CHART_EQUITY 1-minute bars. Imported by the capture
daemon, which pushes these rows and bars straight to the browser
(app/market_data/schwab/streaming/live_ui.py), and by the console, whose routes and analytics
read the same functions -- so a price or a bar on screen and one in a calculation can never
come from two different rules.

Nothing here computes a market value: every number is a Schwab field or its receive time; the
only derivations are the live verdict, the trade age, a bar's change and the roll-up of
1-minute bars to a chart timeframe.
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import datetime
from typing import Any, Optional

import live_market_plane as lmp
from instrument_identity import ticker_storage_key
from numeric_contract import schwab_count, schwab_number
from time_et import ET, ct_label, is_collect_window_bar_end_ts_utc

SPOT_SOURCE = "streaming_plane"
#: the chart timeframes: minutes, and "D" (the ET trading date)
CHART_TFS = ("1", "3", "5", "15", "30", "60", "D")


def minute_bar(msg: dict[str, Any]) -> Optional[dict[str, Any]]:
    """A streamed Schwab CHART_EQUITY message as the chart's 1-minute bar {t, o, h, l, c, v}
    (t: the bar's start, epoch seconds), the bar the store keeps and the screen shows. None when
    a price or the start is not a number (AGENTS.md rule 2), the start is off the minute grid, or
    the bar does not end in the collect window (time_et.is_collect_window_bar_end_ts_utc). A
    volume that is not a number is None, never 0."""
    o, h, lo, c = (schwab_number(msg.get(k)) for k in ("open", "high", "low", "close"))
    start_ms = schwab_number(msg.get("bar_start_ms"))
    if None in (o, h, lo, c, start_ms):
        return None
    t = start_ms / 1000.0
    if t % 60 != 0 or not is_collect_window_bar_end_ts_utc(t + 60.0):
        return None
    return {"t": t, "o": o, "h": h, "l": lo, "c": c, "v": schwab_count(msg.get("volume"))}


def tf_bucket_key(t: float, tf: str):
    """The chart bar a timestamp belongs to: its ET trading date ("D") or its tf-minute bucket."""
    return datetime.fromtimestamp(t, ET).date() if tf == "D" else int(t // (int(tf) * 60))


def roll_bucket(bucket: list[dict]) -> dict:
    """THE roll-up of one chart bar from its 1m bars, oldest first: first open, max high, min
    low, last close, stamped with the first bar's t. Volume is the sum only when every minute
    reported one -- otherwise None (unknown), never a partial sum or a 0."""
    vols = [b.get("v") for b in bucket]
    return {"t": bucket[0]["t"], "o": bucket[0]["o"], "h": max(b["h"] for b in bucket),
            "l": min(b["l"] for b in bucket), "c": bucket[-1]["c"],
            "v": None if None in vols else sum(vols)}


def aggregate_bars(bars: list[dict], tf: str) -> list[dict]:
    """1m bars, oldest first, rolled up to a chart timeframe (CHART_TFS): each run of bars in one
    bucket (tf_bucket_key) is one chart bar (roll_bucket)."""
    if tf == "1":
        return list(bars)
    out: list[dict] = []
    run: list[dict] = []
    key = None
    for b in bars:
        k = tf_bucket_key(float(b["t"]), tf)
        if run and k != key:
            out.append(roll_bucket(run))
            run = []
        run.append(b)
        key = k
    if run:
        out.append(roll_bucket(run))
    return out


def last_bar(t: Optional[float]) -> Optional[dict[str, Any]]:
    """The newest completed minute a chart shows, with its Central Time label."""
    return None if t is None else {"t": t, "label": ct_label(t)}


def bar_update(ticker: str, minutes: list[dict], bar: dict, ts_recv: float) -> dict[str, Any]:
    """What the daemon pushes for one new 1-minute `bar`: for every chart timeframe, the chart
    bar that contains it (roll_bucket), from `minutes` -- the ticker's minutes of `bar`'s ET
    trading day, oldest first, `bar` among them; the "D" bar is all of them -- with the daemon's
    receive time of Schwab's message."""
    i = bisect_left([m["t"] for m in minutes], bar["t"])
    by_tf = {"D": with_change(roll_bucket(minutes))}
    for tf in (tf for tf in CHART_TFS if tf != "D"):
        key = tf_bucket_key(bar["t"], tf)
        lo, hi = i, i + 1
        while lo and tf_bucket_key(minutes[lo - 1]["t"], tf) == key:
            lo -= 1
        while hi < len(minutes) and tf_bucket_key(minutes[hi]["t"], tf) == key:
            hi += 1
        by_tf[tf] = with_change(roll_bucket(minutes[lo:hi]))
    return {"ticker": ticker_storage_key(ticker), "ts_recv": ts_recv, "last_bar": last_bar(minutes[-1]["t"]),
            "tf": by_tf}


def live_spot(ticker: str, now: float) -> Optional[float]:
    """The streamed LAST_PRICE while the feed is live for the symbol at `now`, else None. THE spot."""
    row = lmp.get_quote(ticker)
    if (row and lmp.plane_spot_is_last_price(row) and lmp.plane_row_is_streamed(row)
            and lmp.spot_is_fresh(row, now)):
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


def price_row(ticker: str, now: float) -> dict[str, Any]:
    """The finished row the screen paints for one symbol, as it is at `now` (epoch seconds)."""
    tk = ticker_storage_key(ticker)
    row = lmp.get_quote(tk)
    spot = live_spot(tk, now)
    quote_live = bool(row) and lmp.quote_is_fresh(row, now)
    trade_ts = row["trade_ts"] if row and spot is not None and "trade_ts" in row else None

    def field(name: str):
        return row[name] if quote_live and name in row else None

    closed = not lmp.in_session(now)
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
        "feed_live": lmp.feed_live_for(tk, "LEVELONE_EQUITIES", now),
        # market closed: the last streamed trade, a past observation labelled with its time
        "closed_last": {"price": float(last["spot"]), "spot_disp": f"{float(last['spot']):.2f}",
                        "as_of": ct_label(last["trade_ts"])}
                       if last else None,
        "bid": field("bid"),
        "ask": field("ask"),
        "bid_size": field("bid_size"),
        "ask_size": field("ask_size"),
        "mark": field("mark"),                         # Schwab MARK
        "quote_ts": field("exchange_quote_ts"),        # Schwab QUOTE_TIME (epoch s)
        "last_size": field("last_size") if spot is not None else None,
        "total_volume": field("total_volume"),
        "chg_pct": lmp.streamed_chg_pct(row, now),
        "chg_pct_regular": lmp.streamed_chg_pct(row, now, "chg_pct_regular"),
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
