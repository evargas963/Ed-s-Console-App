"""One option contract of a Schwab chain, read once (AGENTS.md rules 2, 3 and 12).

`read_contract` is the one reader of a chain contract's fields (Schwab's /chains contract, with
the sweep's Greeks: the stream's or the quote's, schwab_client.flatten_chain_contracts and
calibration.complete_chain_capture.ChainSweep). Every calculator, the console's carry rules, the
gamma surface and the chain panel take the record; none reads the contract's fields again.
`chain_row` is the record as the chain screens show it, under Schwab's own field names.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal, TypedDict

from numeric_contract import SCHWAB_NO_VALUE, schwab_count, schwab_number

log = logging.getLogger("option_contract")

#: the Greeks the chain carries, each Schwab's stream or quote value
GREEKS = ("gamma", "delta", "theta", "vega", "rho")
#: the contract fields Schwab's chain sends rounded, which it cannot change (Schwab's reply,
#: docs/schwab/schwab_support_emails_2026_10_06.txt item 6), and its quotes and its
#: LEVELONE_OPTIONS stream send as computed
GREEK_FIELDS = (*GREEKS, "volatility")
type ListedField = Literal["pennyPilot", "exerciseType", "expirationType", "lastTradingDay"]
#: the contract's terms from /chains the Structures tab shows as sent, beside those read into
#: the record; no other /chains field reaches the screen
LISTED: tuple[ListedField, ...] = (
    "pennyPilot",
    "exerciseType",
    "expirationType",
    "lastTradingDay",
)


class Listing(TypedDict, total=False):
    """A contract's LISTED terms, each as Schwab sent it: one it did not send is not there."""

    pennyPilot: object
    exerciseType: object
    expirationType: object
    lastTradingDay: object


class ChainRow(Listing, total=False):
    """A contract as the chain screens show it, under Schwab's field names (chain_row).

    Its LISTED terms, then each of these Schwab sent or the record holds a value for (a streamed
    Greek): a field with neither is not there.
    """

    symbol: str | None
    settlementType: object
    multiplier: float | None
    nonStandard: bool | None
    gamma: float | None
    delta: float | None


@dataclass(frozen=True)
class OptionContract:
    """A chain contract's values by AGENTS.md rule 2: None where Schwab sent no value."""

    symbol: str | None
    #: "CALL" or "PUT"; None for any other putCall
    side: str | None
    strike: float | None
    #: Schwab's expirationDate as sent (time_et.time_to_expiry_years reads its time)
    expiration: Any
    #: its calendar day (YYYY-MM-DD); None when it was not sent as a date
    expiry: str | None
    #: the expiration as a time (epoch seconds); None when it is not one
    expires_at: float | None
    days_to_expiry: float | None
    settlement: Any
    open_interest: float | None
    volume: float | None
    #: its quote's bidPrice and askPrice (Schwab's /quotes answer the chain sweep asked for, or
    #: the stream's BID_PRICE and ASK_PRICE for a contract it streams); never the chain's
    bid: float | None
    ask: float | None
    #: its money intrinsic value from the same quote (/quotes' moneyIntrinsicValue, or the
    #: stream's MONEY_INTRINSIC_VALUE): positive in the money, negative out of it (Schwab
    #: Streamer API, LEVELONE_OPTIONS field 11)
    money_intrinsic: float | None
    #: a contract size: None when not a number or negative
    multiplier: float | None
    #: Schwab's volatility, a percent
    volatility: float | None
    #: each Greek: None when not sent, -999, or the contract's volatility was sent as -999
    gamma: float | None
    delta: float | None
    theta: float | None
    vega: float | None
    rho: float | None
    #: Schwab's nonStandard flag (an adjusted deliverable); None when not sent as true or false
    non_standard: bool | None
    #: the chain's interestRate and dividendYield as sent, percents (schwab_client.
    #: flatten_chain_contracts puts the chain's own on each contract)
    interest_rate: float | None
    dividend_yield: float | None
    #: when Schwab's stream sent each of its Greeks, as the chain sweep stamped it (`greeksTime`:
    #: {field: Schwab's time}); None when its Greeks are the quote's. On no screen
    greeks_time: object
    #: the LISTED terms Schwab sent, as sent, for the screen only
    listing: Listing = field(repr=False)
    #: the fields Schwab sent: the screen shows a field Schwab did not send only with a value
    sent: frozenset[str] = field(repr=False, default=frozenset())


def _greek(raw: Mapping[str, Any], name: str, void: bool) -> float | None:
    return None if void else schwab_number(raw.get(name))


def streamed_greeks(content: Mapping[str, Any]) -> dict[str, float | None]:
    """Return the Greeks a contract's LEVELONE_OPTIONS record carries, under the contract's names.

    The one reader of those stream fields (the chain sweep, the console's order-flow state and
    its history). A field the record does not carry is left out (on Change delivery a message
    carries only what changed); one it carries is as Schwab sent it (schwab_number), so Schwab's
    -999 is None. The names are GREEK_FIELDS, each the stream field's name in lowercase.
    """
    sent = {
        "gamma": content.get("GAMMA"),
        "delta": content.get("DELTA"),
        "theta": content.get("THETA"),
        "vega": content.get("VEGA"),
        "rho": content.get("RHO"),
        "volatility": content.get("VOLATILITY"),
    }
    return {name: schwab_number(value) for name, value in sent.items() if value is not None}


def streamed_greek_set(greeks: Mapping[str, Any]) -> dict[str, float] | None:
    """Return all six Greeks of `greeks` (a contract's streamed Greeks) when each is a value.

    A contract Schwab streams takes its Greeks from the stream as one set, never some from the
    stream and some from the quotes endpoint: None when any is missing or no value, and the
    contract's Greeks are then the quote's (the chain sweep).
    """
    if any(greeks.get(name) is None for name in GREEK_FIELDS):
        return None
    return {name: greeks[name] for name in GREEK_FIELDS}


#: a streamed contract's top of book on LEVELONE_OPTIONS: each stream field, the record's name
#: of it and its reader (rule 2)
STREAMED_TOP = (
    ("BID_PRICE", "bid", schwab_number),
    ("ASK_PRICE", "ask", schwab_number),
    ("BID_SIZE", "bid_size", schwab_count),
    ("ASK_SIZE", "ask_size", schwab_count),
    ("MARK", "mark", schwab_number),
    ("QUOTE_TIME_MILLIS", "quote_time_ms", schwab_number),
    ("MONEY_INTRINSIC_VALUE", "money_intrinsic", schwab_number),
)
#: the quote among them: its bid and ask, their sizes and Schwab's time of it. A message that
#: changes one of these replaces the quote (stream_spine.MessageBus keeps the one it replaced)
QUOTE_FIELDS = ("BID_PRICE", "ASK_PRICE", "BID_SIZE", "ASK_SIZE", "QUOTE_TIME_MILLIS")


@dataclass(frozen=True)
class StreamedTop:
    """A contract's or an equity's top of book as Schwab's LEVELONE stream last sent each field.

    Each field the newest value Schwab sent for it (STREAMED_TOP's readers): None until Schwab
    sends one, and when the one it sent is not a number.
    """

    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    mark: float | None = None
    quote_time_ms: float | None = None
    money_intrinsic: float | None = None


#: a symbol with no top of book received: every field unknown
NO_TOP = StreamedTop()


@dataclass(frozen=True)
class Received:
    """One streamed field: the value Schwab sent (None: not a number) and when it was received.

    NOT_SENT, with neither, is a field the stream has not sent.
    """

    value: float | None
    ts_recv: float | None


#: a field the stream has not sent
NOT_SENT = Received(None, None)


@dataclass(frozen=True)
class StreamedGreeks:
    """A contract's Greeks, volatility and volume as LEVELONE_OPTIONS last sent each one.

    Each field with its own receive time (a message carries only the fields that changed);
    NOT_SENT until the stream sends it. With them the stock's price the record carries
    (UNDERLYING_PRICE), the price its delta is at.
    """

    gamma: Received = NOT_SENT
    delta: Received = NOT_SENT
    theta: Received = NOT_SENT
    vega: Received = NOT_SENT
    rho: Received = NOT_SENT
    volatility: Received = NOT_SENT
    total_volume: Received = NOT_SENT
    underlying_price: Received = NOT_SENT

    def newest_ts(self) -> float | None:
        """Return when the newest of its gamma, delta and volume was received; None: none was."""
        times = [
            f.ts_recv for f in (self.gamma, self.delta, self.total_volume) if f.ts_recv is not None
        ]
        return max(times) if times else None

    def values(self) -> dict[str, float | None]:
        """Return each field the stream sent, by its name, as a value (option_contract's names)."""
        sent = {
            "gamma": self.gamma,
            "delta": self.delta,
            "theta": self.theta,
            "vega": self.vega,
            "rho": self.rho,
            "volatility": self.volatility,
            "total_volume": self.total_volume,
        }
        return {name: f.value for name, f in sent.items() if f is not NOT_SENT}


#: a contract with no Greeks streamed
NO_GREEKS = StreamedGreeks()


@dataclass(frozen=True)
class Streamed:
    """What the stream holds of one contract: its top of book and its Greeks."""

    top: StreamedTop
    greeks: StreamedGreeks


def streamed_quote(sent: Streamed) -> dict[str, float | None]:
    """Return the quote a streamed contract's record takes: its volume, bid, ask and intrinsic.

    Each the stream's newest (`sent`), None until the stream sends it; the one builder of them
    (the levels' overlay and the chain sweep).
    """
    return {
        "volume": sent.greeks.total_volume.value,
        "bid": sent.top.bid,
        "ask": sent.top.ask,
        "money_intrinsic": sent.top.money_intrinsic,
    }


def streamed_top(content: Mapping[str, Any]) -> dict[str, float | None]:
    """Return the top of book a contract's LEVELONE_OPTIONS record carries, under our names.

    The one reader of those stream fields (the console's order-flow state and the chain sweep).
    A field the record does not carry is left out; one it carries is as Schwab sent it, None
    when it is not a number.
    """
    return {name: read(content[field]) for field, name, read in STREAMED_TOP if field in content}


def _expires_at(raw: Any, symbol: Any) -> float | None:
    """Schwab's expirationDate ("2026-09-18T20:00:00.000+00:00") as a time.

    None, logged, when it was not sent as one (rule 2).
    """
    try:
        return datetime.fromisoformat(raw).timestamp()
    except (TypeError, ValueError) as e:
        log.warning("%s has no expirationDate as a date (%s: %s)", symbol, type(e).__name__, e)
        return None


def _shown(value: Any) -> Any:
    """Return a listing value as the screen shows it: a number by rule 2, anything else as sent."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return schwab_number(value)
    return value


def quote_values(quote: Mapping[str, Any]) -> dict[str, Any]:
    """Return a contract record's values from Schwab's /quotes answer for it (its `quote`).

    Its bid and ask, volume, Greeks and volatility, each as sent (rule 2; a -999 volatility voids
    the Greeks).
    """
    vol = quote.get("volatility")
    void = vol is not None and vol == SCHWAB_NO_VALUE
    return {
        "bid": schwab_number(quote.get("bidPrice")),
        "ask": schwab_number(quote.get("askPrice")),
        "money_intrinsic": schwab_number(quote.get("moneyIntrinsicValue")),
        "volume": schwab_count(quote.get("totalVolume")),
        "volatility": schwab_number(vol),
        **{g: _greek(quote, g, void) for g in GREEKS},
    }


def read_contract(raw: Mapping[str, Any]) -> OptionContract:
    """Return the record of one contract as the chain sweep delivers it."""
    put_call = raw.get("putCall")
    side = put_call.strip().upper() if isinstance(put_call, str) else None
    expiration = raw.get("expirationDate")
    vol_sent = raw.get("volatility")
    void = vol_sent is not None and vol_sent == SCHWAB_NO_VALUE
    multiplier = schwab_number(raw.get("multiplier"))
    quoted = quote_values(raw["quote"]) if isinstance(raw.get("quote"), Mapping) else {}
    if isinstance(raw.get("streamed"), Mapping):
        # a contract Schwab streams: the stream's bid, ask and volume when its chain was
        # complete, as the sweep read them (ChainSweep.take_greeks)
        quoted = raw["streamed"]
    listing: Listing = {}
    for name in LISTED:
        if name in raw:
            listing[name] = _shown(raw[name])
    return OptionContract(
        symbol=raw.get("symbol"),
        side=side if side in ("CALL", "PUT") else None,
        strike=schwab_count(raw.get("strikePrice")),
        expiration=expiration,
        expiry=expiration[:10] if isinstance(expiration, str) and len(expiration) >= 10 else None,
        expires_at=_expires_at(expiration, raw.get("symbol")),
        days_to_expiry=schwab_number(raw.get("daysToExpiration")),
        settlement=raw.get("settlementType"),
        open_interest=schwab_count(raw.get("openInterest")),
        # the quote's (the sweep's /quotes answer) or, for a streamed contract, the stream's; a
        # chain stored before quotes were kept with it carries only the volume /chains sent
        volume=quoted["volume"] if quoted else schwab_count(raw.get("totalVolume")),
        bid=quoted.get("bid"),
        ask=quoted.get("ask"),
        money_intrinsic=quoted.get("money_intrinsic"),
        multiplier=None if multiplier is None or multiplier < 0 else multiplier,
        # the stream's, as the sweep wrote them, or the quote's
        **{
            "volatility": schwab_number(vol_sent),
            **{g: _greek(raw, g, void) for g in GREEKS},
            **{k: v for k, v in quoted.items() if k in GREEK_FIELDS},
        },
        non_standard=flag if isinstance(flag := raw.get("nonStandard"), bool) else None,
        interest_rate=schwab_number(raw.get("interestRate")),
        dividend_yield=schwab_number(raw.get("dividendYield")),
        greeks_time=raw.get("greeksTime"),
        listing=listing,
        sent=frozenset(raw),
    )


def read_chain(contracts: Iterable[Mapping[str, Any]]) -> list[OptionContract]:
    """Each contract of a chain as the sweep delivers it, in order."""
    return [read_contract(c) for c in contracts]


def listed_expiries(answer: Mapping[str, Any], today: date) -> list[date]:
    """Return the expiries of Schwab's expiration chain answer from `today` on, ascending.

    The answer is /marketdata/v1/expirationchain's. The list still carries an expiry that has
    passed (a Saturday's list holds Friday's), and a chain request whose fromDate has passed is
    refused with HTTP 400, so those are left out.
    """
    return sorted(
        {
            d
            for e in answer["expirationList"]
            if (d := date.fromisoformat(e["expirationDate"][:10])) >= today
        }
    )


def _shows(c: OptionContract, name: str, value: object) -> bool:
    """Tell whether the chain screens show `name` of `c`: Schwab sent it, or the record holds it."""
    return name in c.sent or value is not None


def chain_row(c: OptionContract) -> ChainRow:
    """Return the contract as the chain screens show it, under Schwab's field names.

    Each field Schwab
    sent, and each value the record holds (a streamed Greek), and no other. Of its Greeks, the
    two the Chain ladder draws: gamma and delta. Its strike, its side and its in-the-money flag
    are the ladder row's (calc.terrain_engine.chain_ladder); its open interest, volume, IV, bid
    and ask are the texts served beside it (push.chain).
    """
    row: ChainRow = {**c.listing}
    if _shows(c, "symbol", c.symbol):
        row["symbol"] = c.symbol
    if _shows(c, "settlementType", c.settlement):
        row["settlementType"] = c.settlement
    if _shows(c, "multiplier", c.multiplier):
        row["multiplier"] = c.multiplier
    if _shows(c, "nonStandard", c.non_standard):
        row["nonStandard"] = c.non_standard
    if _shows(c, "gamma", c.gamma):
        row["gamma"] = c.gamma
    if _shows(c, "delta", c.delta):
        row["delta"] = c.delta
    return row
