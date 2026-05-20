"""A2 contract vs underlying price/spread precedence (DFR-006 / OP-007)."""

from __future__ import annotations

from typing import Any


def _num(value: Any) -> float | None:
    from numeric_contract import float_finite_or_none

    return float_finite_or_none(value)


def contract_spread_pts_from_bid_ask(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None:
        return None
    try:
        bf, af = float(bid), float(ask)
        if af > 0 and bf >= 0:
            return round(af - bf, 4)
    except (TypeError, ValueError):
        return None
    return None


def resolve_a2_contract_mid(*, chain_row: dict[str, Any]) -> tuple[float | None, str | None]:
    """Schwab chain mid ladder: mark → last → (bid+ask)/2."""
    mark_raw = _num(chain_row.get("mark"))
    if mark_raw is not None and mark_raw > 0:
        return float(mark_raw), "schwab_chain_mark"
    last_raw = _num(chain_row.get("last"))
    if last_raw is not None and last_raw > 0:
        return float(last_raw), "schwab_chain_last"
    bid = _num(chain_row.get("bid"))
    ask = _num(chain_row.get("ask"))
    if bid is not None and ask is not None:
        try:
            bf, af = float(bid), float(ask)
            if af > 0 and bf >= 0:
                calc = (af + bf) / 2.0
                if calc > 0:
                    return round(calc, 4), "derived_bid_ask_mid"
        except (TypeError, ValueError):
            pass
    return None, None


def resolve_a2_contract_spread(
    *, bid: float | None, ask: float | None
) -> tuple[float | None, str | None]:
    """Contract spread for A2 gates — chain bid/ask points only."""
    pts = contract_spread_pts_from_bid_ask(bid, ask)
    if pts is not None:
        return pts, "schwab_chain_bid_ask_pts"
    return None, None


def resolve_a2_underlying_spread_pts(*, ms_dict: dict[str, Any]) -> tuple[float | None, str | None]:
    """Underlying quote spread — never mixed into contract spread gates."""
    sp_pts = _num(ms_dict.get("spread_pts"))
    if sp_pts is not None:
        return sp_pts, "underlying_spread_pts"
    legacy = _num(ms_dict.get("spread"))
    if legacy is not None:
        return legacy, "underlying_spread_legacy_pts"
    return None, None
