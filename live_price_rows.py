"""THE displayed price row -- one producer for every price the operator sees.

Built only from live_market_plane (the per-field Schwab LEVELONE_EQUITIES state) and its live
rule (live_state). Imported by the capture daemon, which pushes these rows straight to
the browser (app/market_data/schwab/streaming/live_ui.py) and orders and records its option
contracts at their price (`spot`, capture.Daemon's option rule), and by the console, whose
analytics read the same function -- so a price on screen and a price in a calculation can
never come from two different rules.

Nothing here computes a market value: every number is a Schwab field or its receive time, with
Schwab's own trade time; the only derivations are the trade age and its label. Whether the
values are live now, the word for that (`feed_label`) and why not (`outage`) are stated beside
them; the last values Schwab sent stay (docs/DATA_FLOW.md §2 D5).
"""

from __future__ import annotations

from typing import Any

import live_market_plane as lmp
from instrument_identity import ticker_storage_key
from numeric_contract import change_percent_text, count_text, price_text
from time_et import age_text, ct_label

SPOT_SOURCE = "streaming_plane"


def with_change(bar: dict[str, Any]) -> dict[str, Any]:
    """`bar` with its change over the bar (close - open) and that change as a percent of open.

    THE bar-change computation for every bar served, with its text as the screen shows it
    (`chg_text`: signed, two decimals, the percent beside it, "+1.25 (+0.18%)"). Every bar holds
    its open and close (a Candle's); a percent of an open of 0 is not a number: None, and the
    text shows the change alone.
    """
    chg = bar["c"] - bar["o"]
    pct = chg / bar["o"] * 100 if bar["o"] else None
    bar["chg"], bar["chg_pct"] = chg, pct
    text = f"{chg:+.2f}"
    if pct is not None:  # its percent beside it, when it is a number
        text += f" ({pct:+.2f}%)"
    bar["chg_text"] = text
    return bar


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


def price_row(ticker: str, now: float) -> dict[str, Any]:
    """Return the finished row the screen paints for one symbol, as it is at `now`.

    Each field is the last value Schwab sent. Not live, it sets `feed_live` false, `feed_label`
    and `outage`; the fields stay (docs/DATA_FLOW.md §2 D5).
    """
    tk = ticker_storage_key(ticker)
    label, outage = lmp.live_state(tk, "LEVELONE_EQUITIES", now)
    row = lmp.get_quote(tk)
    spot = row.spot
    trade_ts = row.trade_ts
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
        "trade_time_ct": ct_label(trade_ts) if trade_ts is not None else None,
        "trade_age_text": _trade_age_text(trade_ts, now),
        "ts_recv": row.server_received_ts,
    }
