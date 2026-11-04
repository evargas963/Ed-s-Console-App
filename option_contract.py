"""One option contract of a Schwab chain, read once (AGENTS.md rules 2, 3 and 12).

`read_contract` is the one reader of a chain contract's fields (Schwab's /chains contract, with
the sweep's quote Greeks and `greeksTime`, schwab_client.flatten_chain_contracts and
calibration.complete_chain_capture.ChainSweep). Every calculator, the console's carry rules, the
gamma surface and /api/chain take the record; none reads the contract's fields again.
`chain_row` is the record as the chain screens show it, under Schwab's own field names.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from numeric_contract import SCHWAB_NO_VALUE, schwab_count, schwab_number

#: the Greeks the chain carries, each Schwab's quote value (complete_chain_capture.GREEK_FIELDS)
GREEKS = ("gamma", "delta", "theta", "vega", "rho")
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
        "greeksTime",
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
    #: its calendar day (YYYY-MM-DD); "" when it was not sent as a date
    expiry: str
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
    #: Schwab's -999 volatility: the contract's Greeks have no value
    greeks_void: bool
    gamma: float | None
    delta: float | None
    theta: float | None
    vega: float | None
    rho: float | None
    #: Schwab's time of the gamma (ms), greeksTime.gamma
    gamma_time: float | None
    #: Schwab's nonStandard flag: an adjusted deliverable
    non_standard: bool
    #: every other field, each number by rule 2, for the screen only
    listing: Mapping[str, Any] = field(repr=False)
    #: the fields Schwab sent: the screen shows a field only when it was sent
    sent: frozenset[str] = field(repr=False, default=frozenset())


def _greek(raw: Mapping, name: str, void: bool) -> float | None:
    return None if void else schwab_number(raw.get(name))


def _expires_at(raw: Any) -> float | None:
    try:
        return datetime.fromisoformat(raw).timestamp()
    except (TypeError, ValueError):
        return None


def _shown(value: Any) -> Any:
    """A listing value as the screen shows it: a number by rule 2, anything else as sent."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return schwab_number(value)
    return value


def read_contract(raw: Mapping[str, Any]) -> OptionContract:
    """The record of one contract as the chain sweep delivers it."""
    side = str(raw.get("putCall") or "").strip().upper()
    expiration = raw.get("expirationDate")
    vol_sent = raw.get("volatility")
    void = vol_sent is not None and vol_sent == SCHWAB_NO_VALUE
    multiplier = schwab_number(raw.get("multiplier"))
    times = raw.get("greeksTime")
    return OptionContract(
        symbol=raw.get("symbol"),
        side=side if side in ("CALL", "PUT") else None,
        strike=schwab_number(raw.get("strikePrice")),
        expiration=expiration,
        expiry=expiration[:10] if isinstance(expiration, str) and len(expiration) >= 10 else "",
        expires_at=_expires_at(expiration),
        days_to_expiry=schwab_number(raw.get("daysToExpiration")),
        settlement=raw.get("settlementType"),
        open_interest=schwab_count(raw.get("openInterest")),
        volume=schwab_count(raw.get("totalVolume")),
        multiplier=None if multiplier is None or multiplier < 0 else multiplier,
        volatility=schwab_number(vol_sent),
        greeks_void=void,
        **{g: _greek(raw, g, void) for g in GREEKS},
        gamma_time=schwab_number(times.get("gamma")) if isinstance(times, dict) else None,
        non_standard=raw.get("nonStandard") is True,
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


def chain_row(c: OptionContract, gamma_shown: bool) -> dict[str, Any]:
    """The contract as the chain screens show it, under Schwab's field names, each field Schwab
    sent and no other: the gamma only when it is a value at the price the chain was priced at
    (`gamma_shown`, math_exposure_core.gamma_reported)."""
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
        "gamma": c.gamma if gamma_shown else None,
        **{g: getattr(c, g) for g in GREEKS if g != "gamma"},
    }
    return {**c.listing, **{k: v for k, v in read.items() if k in c.sent}}
