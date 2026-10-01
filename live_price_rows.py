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

import hashlib
from bisect import bisect_left
from datetime import datetime, timedelta
from typing import Any, Optional

import live_market_plane as lmp
from instrument_identity import ticker_storage_key
from numeric_contract import price_text, schwab_count, schwab_number, volume_text
from time_et import (COLLECT_WINDOW_START_MINS, ET, RTH_START_MINS, ct_label, et_date_str_from_ts_utc,
                     et_minute_total_from_ts_utc, is_collect_window_bar_end_ts_utc, is_trading_day_et,
                     session_close_mins_for_et_date, trading_date_label)

SPOT_SOURCE = "streaming_plane"
#: the chart timeframes: minutes, and "D" (the ET trading date)
CHART_TFS = ("1", "3", "5", "15", "30", "60", "D")
#: the timeframes built from Schwab's 1-minute bars (1m as sent; 3m-60m summed from them). The
#: daily candle is Schwab's own, never summed from minutes (day_candle, daily_candles): Schwab's
#: minute volumes sum to less than its daily volume (SPY 2026-09-30: about 68%)
INTRADAY_TFS = ("1", "3", "5", "15", "30", "60")
#: the newest 1-minute bars the Trade Desk Order Flow card shows (`recent_1m`, on each bar push
#: and on /api/bars1m): served whole so the page keeps no window of its own
RECENT_1M_BARS = 60


def minute_bar(msg: dict[str, Any]) -> Optional[dict[str, Any]]:
    """A streamed Schwab CHART_EQUITY message as the chart's 1-minute bar {t, o, h, l, c, v}
    (t: the bar's start, epoch seconds), the bar the store keeps and the screen shows. None when
    a price or the start is not a number (`schwab_number`), the start is off the minute grid, or
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


def minutes_digest(starts) -> str:
    """One fixed-width identity of a set of minutes (their starts, epoch seconds): the daemon's
    held minutes (its bar verdict) and the minutes a price-level snapshot is built from compare by
    it, so two sets of the same size and newest minute never read as equal."""
    h = hashlib.blake2b(digest_size=16)
    for t in sorted(int(s) for s in starts):
        h.update(t.to_bytes(8, "big"))
    return h.hexdigest()


def tf_bucket_key(t: float, tf: str):
    """The chart bar a timestamp belongs to: its ET trading date ("D") or its tf-minute bucket."""
    return datetime.fromtimestamp(t, ET).date() if tf == "D" else int(t // (int(tf) * 60))


def tf_bucket_start(t: float, tf: str) -> float:
    """The time a chart bar is stamped with: the start of the bucket `t` belongs to
    (tf_bucket_key) -- the tf-minute bucket's first second, or 00:00 ET of the trading date for
    "D" -- the chart convention (TradingView, lightweight-charts), so a bar's time never depends
    on which of its minutes is held."""
    if tf == "D":
        d = datetime.fromtimestamp(t, ET).date()
        return datetime(d.year, d.month, d.day, tzinfo=ET).timestamp()
    return float(tf_bucket_key(t, tf) * int(tf) * 60)


def roll_bucket(bucket: list[dict], tf: str) -> dict:
    """THE roll-up of one intraday chart bar of timeframe `tf` (INTRADAY_TFS) from its 1m bars, oldest first: first open,
    max high, min low, last close, stamped with its bucket's start (tf_bucket_start). Volume is
    the sum only when every minute reported one -- otherwise None (unknown), never a partial sum
    or a 0."""
    vols = [b.get("v") for b in bucket]
    return {"t": tf_bucket_start(bucket[0]["t"], tf), "o": bucket[0]["o"], "h": max(b["h"] for b in bucket),
            "l": min(b["l"] for b in bucket), "c": bucket[-1]["c"],
            "v": None if None in vols else sum(vols)}


def aggregate_bars(bars: list[dict], tf: str) -> list[dict]:
    """1m bars, oldest first, rolled up to an intraday chart timeframe (INTRADAY_TFS): each run
    of bars in one bucket (tf_bucket_key) is one chart bar (roll_bucket)."""
    if tf == "1":
        return list(bars)
    out: list[dict] = []
    run: list[dict] = []
    key = None
    for b in bars:
        k = tf_bucket_key(float(b["t"]), tf)
        if run and k != key:
            out.append(roll_bucket(run, tf))
            run = []
        run.append(b)
        key = k
    if run:
        out.append(roll_bucket(run, tf))
    return out


def last_bar(t: Optional[float]) -> Optional[dict[str, Any]]:
    """The newest completed minute a chart shows, with its Central Time label."""
    return None if t is None else {"t": t, "label": ct_label(t)}


def served_bar(bar: dict[str, Any], tf: str) -> dict[str, Any]:
    """A chart bar of timeframe `tf` as every route and push serves it: with its change
    (with_change) and its label -- the bar's Central Time, or a daily bar's ET trading date
    (time_et.trading_date_label) -- and its volume's text (volume_text). The chart prints them; it
    formats no bar time or volume."""
    bar = with_change(bar)
    bar["label"] = trading_date_label(bar["t"]) if tf == "D" else ct_label(bar["t"])
    bar["v_text"] = volume_text(bar.get("v"))
    return bar


def recent_1m(minutes: list[dict]) -> list[dict[str, Any]]:
    """The newest RECENT_1M_BARS of `minutes` (oldest first), served (served_bar): the Trade
    Desk Order Flow card's hour, served whole by the bar push and by /api/bars1m."""
    return [served_bar(dict(m), "1") for m in minutes[-RECENT_1M_BARS:]]


def session_first_minute(t: float) -> float:
    """The start of the first minute the collect window keeps on `t`'s ET date (09:15 ET)."""
    d = datetime.fromtimestamp(t, ET).date()
    return datetime(d.year, d.month, d.day, COLLECT_WINDOW_START_MINS // 60, COLLECT_WINDOW_START_MINS % 60,
                    tzinfo=ET).timestamp()


def uncovered(covered: list[tuple[float, float]], first: float, last: float) -> list[tuple[float, float]]:
    """The minutes from `first` to `last` (minute starts, inclusive) outside the `covered` spans
    (sorted, inclusive minute-start pairs), as spans."""
    gaps, at = [], first
    for a, b in covered:
        if b < at:
            continue
        if a > last:
            break
        if a > at:
            gaps.append((at, a - 60.0))
        at = max(at, b + 60.0)
    if at <= last:
        gaps.append((at, last))
    return gaps


def missing_reason(gaps: list[tuple[float, float]]) -> str:
    """Why a bar is not served complete: each span of minutes not received from Schwab."""
    return "; ".join(f"minutes {ct_label(a)} – {ct_label(b)} not received from Schwab" for a, b in gaps)


#: whether a symbol's minutes of the day are covered through now (coverage_now): every value
#: built from today's bars is current only while they are
COVERAGE_CURRENT, COVERAGE_STALE = "current", "stale"


def day_gaps(covered: list[tuple[float, float]], stream_from: Optional[float], now: float) -> list[tuple[float, float]]:
    """The spans of `now`'s ET trading day, from the collect window's first minute (09:15 ET)
    through the newest one completed at `now` inside the window, not covered -- by `covered`
    (the spans held: the stream's through its bars, each price-history reply's) nor by the
    stream's subscription unbroken since `stream_from` (None: not streaming), which covers every
    completed minute (a minute with no bar had no trade). Not a trading day: none."""
    close = session_close_mins_for_et_date(et_date_str_from_ts_utc(now))
    if close is None:
        return []
    first = session_first_minute(now)
    last = min(now // 60 * 60 - 60, first + (close + 15 - COLLECT_WINDOW_START_MINS - 1) * 60.0)
    spans = sorted(covered + ([(max(stream_from, first), last)] if stream_from is not None else []))
    return uncovered(spans, first, last) if last >= first else []


def coverage_now(covered: list[tuple[float, float]], stream_from: Optional[float], now: float) -> tuple[str, str]:
    """(state, reason): whether `now`'s day has no gap (day_gaps); nothing due yet: current."""
    gaps = day_gaps(covered, stream_from, now)
    if not gaps:
        return COVERAGE_CURRENT, ""
    return COVERAGE_STALE, missing_reason(gaps) + ("" if stream_from is not None else
                                                   " (the symbol's 1-minute bar stream is not subscribed now)")


def bar_update(ticker: str, minutes: list[dict], bar: dict, ts_recv: float,
               covered: list[tuple[float, float]]) -> dict[str, Any]:
    """What the daemon pushes for one 1-minute `bar`: for each intraday chart timeframe
    (INTRADAY_TFS), the chart bar that contains it (roll_bucket) when that is the chart's newest
    bar, from `minutes` -- the ticker's minutes of `bar`'s ET trading day, oldest first, `bar`
    among them -- with the daemon's receive time of Schwab's message and `recent_1m`. The daily
    candle is not built from minutes: it is Schwab's (price_row `day`). `covered`: the spans of
    minutes the daemon holds all of Schwab's bars for (the stream while subscribed, or a
    price-history reply); inside them a minute with no bar is a minute Schwab reported no trade
    in. A bar above 1 minute, and `recent_1m`, is served only when every minute from its bucket's
    start (or the session's first minute) to its newest is covered; otherwise it is absent and
    `unavailable` names each span missing (never a partial bar served as complete, nothing filled
    or guessed). The 1-minute bar is always served.

    A chart's push is only ever its newest bar: a chart places it with the library's own update,
    which replaces the newest bar or adds a newer one, and a bar's time is its bucket's start, so
    no minute moves it. A minute Schwab sends late (older than the newest one held) is a past
    event. It is held, so the newest bars that contain it, every later roll-up and `recent_1m`
    carry it; a chart bar of an older bucket is not pushed as a tail: the stored history carries
    it when the chart is loaded again."""
    i = bisect_left([m["t"] for m in minutes], bar["t"])
    newest, first = minutes[-1]["t"], session_first_minute(bar["t"])
    by_tf: dict[str, Any] = {}
    unavailable: dict[str, str] = {}
    for tf in INTRADAY_TFS:
        key = tf_bucket_key(bar["t"], tf)
        if key != tf_bucket_key(newest, tf):
            continue
        lo, hi = i, i + 1
        while lo and tf_bucket_key(minutes[lo - 1]["t"], tf) == key:
            lo -= 1
        while hi < len(minutes) and tf_bucket_key(minutes[hi]["t"], tf) == key:
            hi += 1
        gaps = [] if tf == "1" else uncovered(covered, max(tf_bucket_start(bar["t"], tf), first),
                                              minutes[hi - 1]["t"])
        if gaps:
            unavailable[tf] = missing_reason(gaps)
        else:
            by_tf[tf] = served_bar(roll_bucket(minutes[lo:hi], tf), tf)
    # the Order Flow hour: its minutes, and the hour before the newest, all covered
    recent = minutes[-RECENT_1M_BARS:]
    gaps = uncovered(covered, max(min(recent[0]["t"], newest - (RECENT_1M_BARS - 1) * 60.0), first), newest)
    if gaps:
        unavailable["recent_1m"] = missing_reason(gaps)
    return {"ticker": ticker_storage_key(ticker), "ts_recv": ts_recv, "last_bar": last_bar(newest),
            "tf": by_tf, "recent_1m": None if gaps else recent_1m(minutes), "unavailable": unavailable}


#: where today's daily candle comes from: Schwab's LEVELONE_EQUITIES day fields, as sent
DAY_SOURCE = ("Schwab LEVELONE_EQUITIES OPEN_PRICE / HIGH_PRICE / LOW_PRICE / LAST_PRICE "
              "(REGULAR_MARKET_LAST_PRICE after the regular close) / TOTAL_VOLUME")


def day_candle(ticker: str, now: float) -> dict[str, Any]:
    """Today's daily candle at `now`, Schwab's day fields as sent (decided by the operator,
    2026-10-01: "lets use what schwab gives us"): open OPEN_PRICE, high HIGH_PRICE, low LOW_PRICE
    (regular-session trades, Streamer Guide p.17-18), close LAST_PRICE -- after the regular close
    REGULAR_MARKET_LAST_PRICE, the regular session's last (2026-09-30: SPY 762.63, Schwab's
    daily candle close) -- and volume TOTAL_VOLUME (the day's, pre- and post-market included,
    p.16). Never built from minutes: Schwab's minute volumes sum to about 68% of TOTAL_VOLUME
    (SPY 2026-09-30). The day fields are today's only when the same quote shows a trade in
    today's session (TRADE_TIME_MILLIS on today's session day, lmp.session_day; sessions start
    04:00 ET) and each field was received in it: after midnight Schwab re-sends the prior day's
    values with a new receive time (SPY 2026-09-08 00:02 ET: Friday 09-04's high, low, open and
    34,054,199 shares; IWM 2026-09-28 01:47 ET: Friday's 22,613,925), and zeroes HIGH/LOW/OPEN at
    about 01:30 ET and TOTAL_VOLUME at about 04:05 ET. The open, high and low also need today's
    regular session to have opened (Schwab's open is blank before it, its high and low come from
    regular-session trades). While the market is in session a field counts only from a live
    feed. Otherwise absent with the reason, never filled from minutes. {t: the day's bar time,
    bar: the served daily bar (o, h, l and c all present) or None, volume, absent: {field:
    reason}, unavailable: the chart's text when there is no bar, as_of, source}."""
    tk = ticker_storage_key(ticker)
    d = datetime.fromtimestamp(now, ET).date()
    day_start = datetime(d.year, d.month, d.day, tzinfo=ET).timestamp()
    close = session_close_mins_for_et_date(d.isoformat())
    if close is None:
        why = f"{d.isoformat()} is not a trading day"
        return {"t": day_start, "bar": None, "volume": None, "volume_text": volume_text(None),
                "absent": {"day": why}, "unavailable": f"No daily candle today: {why}",
                "as_of": None, "source": DAY_SOURCE}
    fields = lmp.day_fields(tk)
    stale = lmp.in_session(now) and not lmp.feed_live_for(tk, "LEVELONE_EQUITIES", now)
    minute = et_minute_total_from_ts_utc(now)
    closed = minute >= close
    trade = fields.get("TRADE_TIME_MILLIS")
    if lmp.session_day(now) != d:
        not_today = ("today's session starts at 04:00 ET: Schwab's day fields before then are the prior "
                     "day's")
    elif trade is None:
        not_today = "Schwab has not sent this symbol's last trade time (TRADE_TIME_MILLIS) in today's session"
    elif lmp.session_day(trade[0]) != d:
        not_today = (f"no trade in today's session yet: Schwab's last trade is from {ct_label(trade[0])}, "
                     f"so its day fields are that session's")
    else:
        not_today = None
    absent: dict[str, str] = {}
    used: list[float] = []

    def take(key: str, name: str, zero_means: Optional[str] = None, regular: bool = False) -> Optional[float]:
        if stale:
            absent[key] = "Schwab's LEVELONE feed for this symbol is not live"
            return None
        if not_today is not None:
            absent[key] = not_today
            return None
        if regular and minute < RTH_START_MINS:
            absent[key] = (f"today's regular session has not opened: Schwab's {name} comes from "
                           f"regular-session trades (Streamer Guide p.17-18)")
            return None
        if name not in fields or lmp.session_day(fields[name][1]) != d:
            absent[key] = f"Schwab has not sent {name} in today's session"
            return None
        value, received = fields[name]
        if zero_means is not None and value == 0:
            absent[key] = zero_means
            return None
        used.append(received)
        return value

    o = take("o", "OPEN_PRICE", "Schwab's OPEN_PRICE is blank (0) until the regular session opens (Streamer Guide p.18)",
             regular=True)
    h = take("h", "HIGH_PRICE", "Schwab's HIGH_PRICE is 0 until the regular session's first trade (Streamer Guide p.17)",
             regular=True)
    lo = take("l", "LOW_PRICE", "Schwab's LOW_PRICE is 0 until the regular session's first trade (Streamer Guide p.17)",
              regular=True)
    c = take("c", "REGULAR_MARKET_LAST_PRICE" if closed else "LAST_PRICE")
    v = take("v", "TOTAL_VOLUME")
    bar = (served_bar({"t": day_start, "o": o, "h": h, "l": lo, "c": c, "v": v}, "D")
           if None not in (o, h, lo, c) else None)
    return {"t": day_start, "bar": bar, "volume": v, "volume_text": volume_text(v), "absent": absent,
            # the daily chart's line when it draws no candle today: each served reason once
            "unavailable": None if bar else "No daily candle today: " + "; ".join(
                dict.fromkeys(absent[k] for k in ("o", "h", "l", "c") if k in absent)),
            "as_of": ct_label(max(used)) if used else None, "source": DAY_SOURCE}


def daily_candles(candles: list[dict], before: float) -> list[dict[str, Any]]:
    """Schwab's daily price-history candles (get_price_history_every_day, as sent) of the days
    before `before` (epoch seconds; today's candle is day_candle), as served daily bars, oldest
    first, each stamped 00:00 ET of its date. A candle whose price is not a number is not a chart
    bar; a volume that is not a number is None."""
    out = []
    for c in candles:
        o, h, lo, cl, ms = (schwab_number(c.get(k)) for k in ("open", "high", "low", "close", "datetime"))
        if None in (o, h, lo, cl, ms):
            continue
        d = datetime.fromtimestamp(ms / 1000.0, ET).date()
        t = datetime(d.year, d.month, d.day, tzinfo=ET).timestamp()
        if t < before:
            out.append(served_bar({"t": t, "o": o, "h": h, "l": lo, "c": cl, "v": schwab_count(c.get("volume"))}, "D"))
    return sorted(out, key=lambda b: b["t"])


def daily_history_gap(candles: list[dict[str, Any]], day: float) -> Optional[str]:
    """Why Schwab's daily candles (daily_candles, oldest first) are not yet whole for the day
    starting at `day` (00:00 ET): their newest is not the previous trading session's (the market
    calendar's), so the prior day's high and low and the daily ATR would be an older day's. None
    when it is."""
    d = datetime.fromtimestamp(day, ET).date() - timedelta(days=1)
    while not is_trading_day_et(d.isoformat()):
        d -= timedelta(days=1)
    newest = datetime.fromtimestamp(candles[-1]["t"], ET).date() if candles else None
    return None if newest == d else f"Schwab's daily history does not yet include {d.isoformat()}"


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


def _refused_text(reason: Optional[str]) -> Optional[str]:
    return None if reason is None else f"Schwab refused this symbol's stream: {reason}"


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
        "spot_disp": price_text(spot) if spot is not None else None,
        "spot_state": "live" if spot is not None else ("closed" if closed else "unavailable"),
        # why there is no live price when Schwab refused the symbol's stream (its own answer,
        # e.g. code 19 REACHED_SYMBOL_LIMIT; the limit itself is not in Schwab's documents)
        "unavailable_reason": (None if spot is not None or closed else
                               _refused_text(lmp.refused_reason(tk, "LEVELONE_EQUITIES", now))),
        "spot_source": SPOT_SOURCE if spot is not None else None,
        # the feed itself (heartbeat, socket open, symbol held) -- distinct from "this symbol
        # has traded this session": live feed + no trade yet reads NO TRADE YET, not no feed
        "feed_live": lmp.feed_live_for(tk, "LEVELONE_EQUITIES", now),
        # market closed: the last streamed trade, a past observation labelled with its time
        "closed_last": {"price": float(last["spot"]), "spot_disp": price_text(float(last['spot'])),
                        "as_of": ct_label(last["trade_ts"])}
                       if last else None,
        "bid": field("bid"),
        "ask": field("ask"),
        "bid_size": field("bid_size"),
        "ask_size": field("ask_size"),
        "mark": field("mark"),                         # Schwab MARK
        "quote_ts": field("exchange_quote_ts"),        # Schwab QUOTE_TIME (epoch s)
        "last_size": field("last_size") if spot is not None else None,
        # the day's open, high, low, close and volume: Schwab's day fields, the one source of every
        # day value on screen (the Trade Desk's session volume, the daily candle)
        "day": day_candle(tk, now),
        "chg_pct": lmp.streamed_chg_pct(row, now),
        "chg_pct_regular": lmp.streamed_chg_pct(row, now, "chg_pct_regular"),
        "net_change": field("net_change") if spot is not None else None,
        "prior_close": field("prior_close"),
        "trade_ts": trade_ts,
        "trade_age_sec": _trade_age_sec(trade_ts, now),
        "ts_recv": row.get("server_received_ts") if row else None,
        "quote_ingestion": row.get("quote_ingestion") if row else None,
        "server_ts": now,
    }
