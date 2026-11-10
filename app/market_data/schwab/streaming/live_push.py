"""Which bus records are Schwab's, and the market context every page shows.

Ed Console is one program: the console reads the daemon's bus in memory (app.options.order_flow.
streaming._bus_loop), never a copy over a socket. The bus records the console takes -- Schwab only,
by each message's `src` (anything else published on the same topics is refused, is_forwarded):
  quote.SYM    src "schwab_l1"          LEVELONE_EQUITIES
  book.SYM     src "schwab_book"        NASDAQ_BOOK / NYSE_BOOK / OPTIONS_BOOK (by `service`)
  optquote.SYM src "schwab_options_l1"  LEVELONE_OPTIONS
  news.SYM     src "schwab_news"        NEWS_HEADLINE
  bar1m.SYM    src "schwab_chart"       CHART_EQUITY
  chain.TK     src "schwab_chain"       the REST option chain, in parts (the daemon's chain sweep)
  pricehistory.TK.SERIES src "schwab_pricehistory"  Schwab's 1-minute bars, 15-minute and daily
               candles of the ticker (the chain sweep's /pricehistory requests)
  markets.DATE src "schwab_markets"     Schwab's /markets answer for the market date (the chain
               sweep's requests), with its status
  watchlist    src "daemon_watchlist"   the watchlist after each add or removal the console asked
               for, with Schwab's /quotes answer to an add's check (capture.watchlist_message)
"""

from __future__ import annotations

#: The market context every page's header shows beside the selected ticker (Trade Desk): the
#: daemon streams it whatever the watchlist holds.
MARKET_CONTEXT = ("$SPX", "$NDX", "$VIX")

#: topic prefix -> the only `src` forwarded for it
_FORWARDED = {
    "quote.": "schwab_l1",
    "book.": "schwab_book",
    "optquote.": "schwab_options_l1",
    "news.": "schwab_news",
    "bar1m.": "schwab_chart",
    "chain.": "schwab_chain",
    "optquotes": "schwab_quotes",
    "pricehistory.": "schwab_pricehistory",
    "markets.": "schwab_markets",
    "watchlist": "daemon_watchlist",
}


def is_forwarded(topic: str, msg) -> bool:
    """Tell whether a record came from Schwab (a chain: its parts)."""
    if isinstance(msg, list) and msg:
        msg = msg[0]
    if not isinstance(msg, dict):
        return False
    for prefix, src in _FORWARDED.items():
        if topic.startswith(prefix):
            return msg.get("src") == src
    return False
