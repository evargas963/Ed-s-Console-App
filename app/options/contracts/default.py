"""Default snapshot-collectable option contract for one underlying.

Uses a banked COMPLETE chain capture and the vendor's own ``symbol`` field.
Never constructs an OSI string. Quote-only / unchainable names yield None.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from instrument_identity import ticker_storage_key
from numeric_contract import float_finite_or_none
from time_et import RTH_END_MINS, now_et

from calibration.complete_chain_capture import nearest_complete_chain_capture


def _expiry_cutoff_et() -> str:
    et = now_et()
    mins = et.hour * 60 + et.minute
    day = et.date() if mins < RTH_END_MINS else (et + timedelta(days=1)).date()
    return day.isoformat()


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
        strike = float_finite_or_none(raw.get("strikePrice"))
        if not sym or strike is None:
            continue
        dist = abs(strike - px)
        if best is None or dist < best[0]:
            best = (dist, sym)
    return best[1] if best else None


def default_option_contract(ticker: str, *, chain_db_path: str | Path) -> str | None:
    """ATM CALL on the nearest still-listed expiry, or None if no banked chain."""
    tk = ticker_storage_key(ticker)
    if not tk:
        return None
    cap = nearest_complete_chain_capture(
        chain_db_path, tk, on_or_after_expiry=_expiry_cutoff_et()
    )
    if not cap:
        return None
    return pick_atm_call_symbol(cap.get("contracts") or [], cap.get("spot"))
