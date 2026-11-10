"""One option contract of a Schwab chain, read once (AGENTS.md rules 2, 3 and 12).

`read_contract` is the one reader of a chain contract's fields (Schwab's /chains contract, with
the sweep's Greeks: the stream's or the quote's, schwab_client.flatten_chain_contracts and
calibration.complete_chain_capture.ChainSweep). Every calculator, the console's carry rules, the
gamma surface and /api/chain take the record; none reads the contract's fields again.
`chain_row` is the record as the chain screens show it, under Schwab's own field names.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from numeric_contract import SCHWAB_NO_VALUE, schwab_count, schwab_number

log = logging.getLogger("option_contract")

#: the Greeks the chain carries, each Schwab's stream or quote value
GREEKS = ("gamma", "delta", "theta", "vega", "rho")
#: the contract fields Schwab's chain sends rounded, which it cannot change (Schwab's reply,
#: docs/schwab/schwab_support_emails_2026_10_06.txt item 6), and its quotes and its
#: LEVELONE_OPTIONS stream send as computed
GREEK_FIELDS = (*GREEKS, "volatility")
#: the contract's terms from /chains the Structures tab shows as sent, beside those read into
#: the record, and the time of its Greeks (the chain sweep's `greeksTime`, AGENTS.md rule 5);
#: no other /chains field reaches the screen
LISTED = ("pennyPilot", "exerciseType", "expirationType", "lastTradingDay", "greeksTime")


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
    #: the LISTED terms Schwab sent, as sent, for the screen only
    listing: Mapping[str, Any] = field(repr=False)
    #: the fields Schwab sent: the screen shows a field Schwab did not send only with a value
    sent: frozenset[str] = field(repr=False, default=frozenset())


def _greek(raw: Mapping, name: str, void: bool) -> float | None:
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
    return OptionContract(
        symbol=raw.get("symbol"),
        side=side if side in ("CALL", "PUT") else None,
        strike=schwab_number(raw.get("strikePrice")),
        expiration=expiration,
        expiry=expiration[:10] if isinstance(expiration, str) and len(expiration) >= 10 else None,
        expires_at=_expires_at(expiration, raw.get("symbol")),
        days_to_expiry=schwab_number(raw.get("daysToExpiration")),
        settlement=raw.get("settlementType"),
        open_interest=schwab_count(raw.get("openInterest")),
        # the quote's (the sweep's /quotes answer); a chain stored before quotes were kept with
        # it carries only the volume /chains sent, as recorded
        volume=quoted["volume"] if quoted else schwab_count(raw.get("totalVolume")),
        bid=quoted.get("bid"),
        ask=quoted.get("ask"),
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
        listing={k: _shown(raw[k]) for k in LISTED if k in raw},
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


def chain_row(c: OptionContract) -> dict[str, Any]:
    """Return the contract as the chain screens show it, under Schwab's field names.

    Each field Schwab
    sent, and each value the record holds (a streamed count or Greek), and no other.
    """
    read = {
        "symbol": c.symbol,
        "putCall": c.side,
        "strikePrice": c.strike,
        "expirationDate": c.expiration,
        "daysToExpiration": c.days_to_expiry,
        "settlementType": c.settlement,
        "openInterest": c.open_interest,
        "totalVolume": c.volume,
        "bid": c.bid,
        "ask": c.ask,
        "multiplier": c.multiplier,
        "volatility": c.volatility,
        "nonStandard": c.non_standard,
        **{g: getattr(c, g) for g in GREEKS},
    }
    return {**c.listing, **{k: v for k, v in read.items() if k in c.sent or v is not None}}
