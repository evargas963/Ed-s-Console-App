"""Default option contract for one underlying: the at-the-money call of its front expiry, from
the chain Schwab sent for it. Uses the vendor's own ``symbol`` field; never constructs an OSI
string. A ticker with no chain or no live price has none.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from numeric_contract import float_finite_or_none, schwab_number
from time_et import ET, session


def _expiry_cutoff_et(now: datetime) -> str:
    """The earliest expiry still trading at `now`: today's until today's regular close as Schwab's
    /markets sent it (early closes included), else tomorrow's -- also while today's answer is not
    in, so an expiry that may have passed is never the default."""
    et = now.astimezone(ET)
    today = session(et.date().isoformat())
    open_today = today is not None and any(et < end for _start, end in today.regular)
    return (et.date() if open_today else (et + timedelta(days=1)).date()).isoformat()


def pick_atm_call_symbol(contracts: list[Any], spot: float | None) -> str | None:
    """Nearest-strike CALL whose ``symbol`` is already on the vendor row."""
    px = float_finite_or_none(spot)
    if px is None:
        return None
    best: tuple[float, str] | None = None
    for raw in contracts or []:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("putCall") or "").upper() != "CALL":
            continue
        sym = str(raw.get("symbol") or "").strip()
        strike = schwab_number(raw.get("strikePrice"))
        if not sym or strike is None:
            continue
        dist = abs(strike - px)
        if best is None or dist < best[0]:
            best = (dist, sym)
    return best[1] if best else None


def front_atm_call(chain: list[dict], spot: float | None, now: datetime) -> str | None:
    """The at-the-money call of the chain's nearest expiry still trading at `now`."""
    cutoff = _expiry_cutoff_et(now)
    front = min((str(c.get("expirationDate") or "")[:10] for c in chain
                 if str(c.get("expirationDate") or "")[:10] >= cutoff), default=None)
    return pick_atm_call_symbol([c for c in chain if str(c.get("expirationDate") or "")[:10] == front], spot)
