"""One record per option contract, on the daemon's bus (docs/DATA_FLOW.md, the option ledger):
opened from Schwab's REST answer, then posted to by every message Schwab sends for the contract.
Each source names a value its own way; the record names it once, as the chain does (the names
every calculation reads). A posting carries only the fields its message sent; the bus keeps
each field's newest by Schwab's time (stream_spine.MessageBus, "contract" topics)."""
from __future__ import annotations

from stream_spine import _now

#: The contract fields Schwab's chain sends rounded, which it cannot change (Schwab Trader API
#: Support, 2026-10-06, item 6; docs/schwab/schwab_support_emails_2026_10_06.txt): never posted
#: from a chain; its quotes and its LEVELONE_OPTIONS stream send them as computed.
GREEK_FIELDS = ("gamma", "delta", "theta", "vega", "rho", "volatility")

#: Each record field and the LEVELONE_OPTIONS field that posts to it (Streamer API §1.1: Change;
#: each pair is one quantity by the LEVELONE_OPTIONS field table). Open interest is not posted
#: from the stream (Schwab's is the prior day's, docs/schwab/schwab_support_emails_2026_10_12.txt 5).
STREAM_FIELDS: tuple[tuple[str, str], ...] = (
    ("bid", "BID_PRICE"), ("ask", "ASK_PRICE"), ("last", "LAST_PRICE"), ("mark", "MARK"),
    ("bidSize", "BID_SIZE"), ("askSize", "ASK_SIZE"), ("lastSize", "LAST_SIZE"),
    ("totalVolume", "TOTAL_VOLUME"),
    ("highPrice", "HIGH_PRICE"), ("lowPrice", "LOW_PRICE"), ("openPrice", "OPEN_PRICE"),
    ("closePrice", "CLOSE_PRICE"), ("high52Week", "HIGH_PRICE_52_WEEK"), ("low52Week", "LOW_PRICE_52_WEEK"),
    ("netChange", "NET_CHANGE"), ("percentChange", "NET_PERCENT_CHANGE"),
    ("markChange", "MARK_CHANGE"), ("markPercentChange", "MARK_CHANGE_PERCENT"),
    ("delta", "DELTA"), ("gamma", "GAMMA"), ("theta", "THETA"), ("vega", "VEGA"), ("rho", "RHO"),
    ("volatility", "VOLATILITY"), ("theoreticalOptionValue", "THEORETICAL_OPTION_VALUE"),
    ("timeValue", "TIME_VALUE"), ("intrinsicValue", "MONEY_INTRINSIC_VALUE"),
    ("quoteTimeInLong", "QUOTE_TIME_MILLIS"), ("tradeTimeInLong", "TRADE_TIME_MILLIS"),
    ("underlyingPrice", "UNDERLYING_PRICE"),
)

#: Each record field and the field of Schwab's /quotes answer for an option ("quote") that posts
#: to it (Market Data API, Quotes; measured on SPY's 2026-11-20 chain and its quotes: each pair is
#: one quantity in one unit, its value as of its answer's time).
QUOTE_FIELDS: tuple[tuple[str, str], ...] = (
    ("bid", "bidPrice"), ("ask", "askPrice"), ("last", "lastPrice"), ("mark", "mark"),
    ("bidSize", "bidSize"), ("askSize", "askSize"), ("lastSize", "lastSize"),
    ("totalVolume", "totalVolume"), ("openInterest", "openInterest"),
    ("highPrice", "highPrice"), ("lowPrice", "lowPrice"), ("openPrice", "openPrice"),
    ("closePrice", "closePrice"), ("high52Week", "52WeekHigh"), ("low52Week", "52WeekLow"),
    ("netChange", "netChange"), ("percentChange", "netPercentChange"),
    ("markChange", "markChange"), ("markPercentChange", "markPercentChange"),
    ("delta", "delta"), ("gamma", "gamma"), ("theta", "theta"), ("vega", "vega"), ("rho", "rho"),
    ("volatility", "volatility"), ("theoreticalOptionValue", "theoreticalOptionValue"),
    ("timeValue", "timeValue"), ("intrinsicValue", "moneyIntrinsicValue"),
    ("quoteTimeInLong", "quoteTime"), ("tradeTimeInLong", "tradeTime"),
    ("underlyingPrice", "underlyingPrice"),
)

#: the source of every contract record: one record per contract, whichever Schwab answer posts
LEDGER_SRC = "ledger"


def opening(contract: dict, ticker: str, chain: "dict | None" = None) -> dict:
    """A contract of Schwab's chain answer (`chain`) as the fields that open its record: every
    field as sent but the rounded Greeks, the answer's underlyingPrice when it sent one (the
    chain sends it once, beside the contracts), and the watchlist ticker it is listed under."""
    sent = {"underlyingPrice": chain["underlyingPrice"]} if chain is not None and "underlyingPrice" in chain else {}
    return {**{k: v for k, v in contract.items() if k not in GREEK_FIELDS}, **sent, "ticker": ticker}


def from_quote(quote: dict) -> dict:
    """The fields Schwab's /quotes answer for a contract posts to its record."""
    return {key: quote[field] for key, field in QUOTE_FIELDS if field in quote}


def from_stream(item: dict, schwab_ts: "int | None") -> dict:
    """The fields a LEVELONE_OPTIONS message posts to its contract's record, and `streamTime`:
    the Schwab time of the stream's newest message for it (whether the stream carries it now)."""
    return {**{key: item[field] for key, field in STREAM_FIELDS if field in item}, "streamTime": schwab_ts}


def posting(symbol: str, fields: dict, schwab_ts: "int | float | None",
            ts_recv: "float | None" = None) -> "tuple[str, dict]":
    """One posting to `symbol`'s record: its bus topic and message (the fields, Schwab's time of
    the answer that carried them, the daemon's receive time)."""
    return f"contract.{symbol}", {"src": LEDGER_SRC, "symbol": symbol, "fields": fields,
                                  "schwab_ts": schwab_ts, "ts_recv": _now(ts_recv)}
