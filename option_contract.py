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
#: the contract fields Schwab's chain sends rounded, which it cannot change (Schwab Trader API
#: Support, 2026-10-06, item 6), and its quotes and its LEVELONE_OPTIONS stream send as computed
GREEK_FIELDS = (*GREEKS, "volatility")
#: the fields read into the record; every other field is the listing, shown as sent
READ = frozenset(
    {
        "symbol",
        "putCall",
        "strikePrice",
        "expirationDate",
        "daysToExpiration",
        "settlementType",
        "openInterest",
        "totalVolume",
        "multiplier",
        "volatility",
        "nonStandard",
        *GREEKS,
    }
)


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
    #: every other field, each number by rule 2, for the screen only
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
    """Schwab's expirationDate ("2026-09-18T20:00:00.000+00:00") as a time; None, logged, when it
    was not sent as one (rule 2)."""
    try:
        return datetime.fromisoformat(raw).timestamp()
    except (TypeError, ValueError) as e:
        log.warning("%s has no expirationDate as a date (%s: %s)", symbol, type(e).__name__, e)
        return None


def _shown(value: Any) -> Any:
    """A listing value as the screen shows it: a number by rule 2, anything else as sent."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return schwab_number(value)
    return value


def read_contract(raw: Mapping[str, Any]) -> OptionContract:
    """The record of one contract as the chain sweep delivers it."""
    put_call = raw.get("putCall")
    side = put_call.strip().upper() if isinstance(put_call, str) else None
    expiration = raw.get("expirationDate")
    vol_sent = raw.get("volatility")
    void = vol_sent is not None and vol_sent == SCHWAB_NO_VALUE
    multiplier = schwab_number(raw.get("multiplier"))
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
        volume=schwab_count(raw.get("totalVolume")),
        multiplier=None if multiplier is None or multiplier < 0 else multiplier,
        volatility=schwab_number(vol_sent),
        **{g: _greek(raw, g, void) for g in GREEKS},
        non_standard=flag if isinstance(flag := raw.get("nonStandard"), bool) else None,
        listing={k: _shown(v) for k, v in raw.items() if k not in READ},
        sent=frozenset(raw),
    )


def read_chain(contracts: Iterable[Mapping[str, Any]]) -> list[OptionContract]:
    """Each contract of a chain as the sweep delivers it, in order."""
    return [read_contract(c) for c in contracts]


def listed_expiries(answer: Mapping[str, Any], today: date) -> list[date]:
    """The expiries of Schwab's expiration chain answer (/marketdata/v1/expirationchain) from
    `today` on, ascending. The list still carries an expiry that has passed (a Saturday's list
    holds Friday's), and a chain request whose fromDate has passed is refused with HTTP 400, so
    those are left out."""
    return sorted(
        {
            d
            for e in answer["expirationList"]
            if (d := date.fromisoformat(e["expirationDate"][:10])) >= today
        }
    )


def chain_row(c: OptionContract) -> dict[str, Any]:
    """The contract as the chain screens show it, under Schwab's field names: each field Schwab
    sent, and each value the record holds (a streamed count or a carried Greek), and no other."""
    read = {
        "symbol": c.symbol,
        "putCall": c.side,
        "strikePrice": c.strike,
        "expirationDate": c.expiration,
        "daysToExpiration": c.days_to_expiry,
        "settlementType": c.settlement,
        "openInterest": c.open_interest,
        "totalVolume": c.volume,
        "multiplier": c.multiplier,
        "volatility": c.volatility,
        "nonStandard": c.non_standard,
        **{g: getattr(c, g) for g in GREEKS},
    }
    return {**c.listing, **{k: v for k, v in read.items() if k in c.sent or v is not None}}
