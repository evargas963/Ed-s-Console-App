"""THE displayed price row -- one producer for every price the operator sees.

Built only from live_market_plane (the per-field Schwab LEVELONE_EQUITIES state) and its live
rule (live_state). Imported by the capture daemon, which pushes these rows straight to
the browser (app/market_data/schwab/streaming/live_ui.py) and orders and records its option
contracts at their price (`spot`, capture.Daemon's option rule), and by the console, whose
analytics read the same function -- so a price on screen and a price in a calculation can
never come from two different rules.

Nothing here computes a market value: every number is a Schwab field or its receive time, with
Schwab's own trade time; the only derivations are the trade age and its label, and the trade's
state as every surface says it (`trade_said`, AGENTS.md rule 4). Whether the
values are live now, the word for that (`feed_label`) and why not (`outage`) are stated beside
them; the last values Schwab sent stay (docs/DATA_FLOW.md §2 D5).
"""

from __future__ import annotations

from typing import TypedDict

import live_market_plane as lmp
from instrument_identity import ticker_storage_key
from numeric_contract import change_percent_text, count_text, price_text
from time_et import age_text, ct_label

SPOT_SOURCE = "streaming_plane"
#: what the trade's state reads when Schwab has sent no trade time (`trade_said`)
NO_TRADE = "no trade sent"


class BarChange(TypedDict):
    """A bar's change over the bar, that change as a percent of its open, and the screen's text."""

    chg: float
    chg_pct: float | None
    chg_text: str


class PriceRow(TypedDict):
    """The finished row the screen paints for one symbol (price_row), each key as served.

    A value is None until Schwab sends it, and when the one it sent is not a number; a text is
    None with its value. The times are epoch seconds.
    """

    ticker: str
    spot: float | None
    spot_disp: str | None
    spot_source: str | None
    feed_live: bool
    feed_label: str
    outage: str | None
    bid: float | None
    ask: float | None
    bid_text: str | None
    ask_text: str | None
    bid_size: float | None
    ask_size: float | None
    mark: float | None
    quote_ts: float | None
    quote_time_ct: str | None
    last_size: float | None
    total_volume: float | None
    last_size_text: str | None
    total_volume_text: str | None
    chg_pct: float | None
    chg_pct_regular: float | None
    chg_pct_text: str | None
    chg_pct_regular_text: str | None
    net_change: float | None
    open_price: float | None
    high_price: float | None
    low_price: float | None
    trade_ts: float | None
    trade_time_ct: str | None
    trade_age_text: str | None
    trade_said: str
    ts_recv: float | None


def bar_change(bar_open: float, bar_close: float) -> BarChange:
    """Return a bar's change over the bar (close - open) and that change as a percent of its open.

    THE bar-change computation for every bar served, with its text as the screen shows it
    (`chg_text`: signed, two decimals, the percent beside it, "+1.25 (+0.18%)"). Every bar holds
    its open and close (a Candle's); a percent of an open of 0 is not a number: None, and the
    text shows the change alone.
    """
    chg = bar_close - bar_open
    pct = chg / bar_open * 100 if bar_open else None
    text = f"{chg:+.2f}"
    if pct is not None:  # its percent beside it, when it is a number
        text += f" ({pct:+.2f}%)"
    return {"chg": chg, "chg_pct": pct, "chg_text": text}


def _trade_age_text(trade_ts: float | None, now: float) -> str | None:
    """Return the age of Schwab's trade time as the screen shows it (time_et.age_text).

    None when no trade is known (never a 0).
    """
    return None if trade_ts is None else age_text(now - trade_ts)


def spot(ticker: str) -> float | None:
    """`ticker`'s live price, the price row's own (price_row's `spot`): Schwab's LAST_PRICE.

    For a reader that needs only the price: the capture daemon's option rule. None while the
    row has none (never received, or sent as not a number).
    """
    return lmp.get_quote(ticker_storage_key(ticker)).spot


def price_row(ticker: str, now: float) -> PriceRow:
    """Return the finished row the screen paints for one symbol, as it is at `now`.

    Each field is the last value Schwab sent. Not live, it sets `feed_live` false, `feed_label`
    and `outage`; the fields stay (docs/DATA_FLOW.md §2 D5).
    """
    tk = ticker_storage_key(ticker)
    label, outage = lmp.live_state(tk, "LEVELONE_EQUITIES", now)
    row = lmp.get_quote(tk)
    spot = row.spot
    trade_ts = row.trade_ts
    trade_ct = ct_label(trade_ts) if trade_ts is not None else None
    quote_ts = row.exchange_quote_ts
    return {
        "ticker": tk,
        "spot": spot,
        "spot_disp": price_text(spot),
        "spot_source": SPOT_SOURCE if spot is not None else None,
        # whether the values are updating now (the feed delivering them, their market trading),
        # the word for that state, and why they are not
        "feed_live": label == lmp.LIVE,
        "feed_label": label,
        "outage": outage,
        "bid": row.bid,
        "ask": row.ask,
        "bid_text": price_text(row.bid),
        "ask_text": price_text(row.ask),
        "bid_size": row.bid_size,
        "ask_size": row.ask_size,
        "mark": row.mark,  # Schwab MARK
        "quote_ts": quote_ts,  # Schwab QUOTE_TIME (epoch s)
        "quote_time_ct": ct_label(quote_ts) if quote_ts is not None else None,
        "last_size": row.last_size,
        "total_volume": row.total_volume,
        "last_size_text": count_text(row.last_size),
        "total_volume_text": count_text(row.total_volume),
        # Schwab's own percent changes vs the prior close: NET_CHANGE_PERCENT (extended hours
        # included) and REGULAR_MARKET_CHANGE_PERCENT
        "chg_pct": row.chg_pct,
        "chg_pct_regular": row.chg_pct_regular,
        # each as the screen shows it, signed with two decimals
        "chg_pct_text": change_percent_text(row.chg_pct),
        "chg_pct_regular_text": change_percent_text(row.chg_pct_regular),
        "net_change": row.net_change,
        "open_price": row.open_price,
        "high_price": row.high_price,
        "low_price": row.low_price,
        "trade_ts": trade_ts,  # Schwab TRADE_TIME (epoch s)
        "trade_time_ct": trade_ct,
        "trade_age_text": _trade_age_text(trade_ts, now),
        # the trade's state as every surface says it, one whole phrase (AGENTS.md rule 4)
        "trade_said": f"last trade {trade_ct}" if trade_ct is not None else NO_TRADE,
        "ts_recv": row.server_received_ts,
    }
