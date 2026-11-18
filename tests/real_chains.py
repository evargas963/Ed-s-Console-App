"""Real option chains the capture daemon captured on 2026-10-07.

From production complete_chain_captures, read-only; each with Schwab's underlying price in the
capture and the instant it was captured -- the valuation instant a test prices it at (`now`),
inside the sessions Schwab's /markets answers (tests/conftest.py).

SPY_0DTE: SPY's same-day expiry (2026-10-07) at 12:32:07 ET, the 20 strikes nearest the price.
CRWD:     CRWD's 2026-10-16 expiry, every strike (strike_range=ALL), at 10:38:40 ET.
TSLA:     TSLA's 2026-10-09 expiry, every strike (strike_range=ALL), at 12:32:15 ET.
MRVL:     MRVL's full chain, all 20 expiries, every strike, at 10:31:20 ET (spot: the front
          expiry's answer).
NFLX:     NFLX's 2026-10-16, 2027-12-17 and 2028-01-21 expiries at 10:32:20 ET; 8 contracts with
          open interest carry Greeks Schwab sent as -999.
SPY_FULL: SPY's whole chain, every expiry, production's complete capture of 2026-11-09 11:06 ET.
SPY_CLOSE: SPY's 2026-10-22 expiry from the close capture begun 2026-10-22 16:17:04 ET, with SPY's
          LEVELONE_EQUITIES prints after it as the daemon received them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from calc.math_exposure_core import compute_exposures_by_strike
from option_contract import OptionContract, read_chain
from time_et import ET, sessions

_FX = Path(__file__).resolve().parent / "fixtures"


@dataclass(frozen=True)
class RealChain:
    ticker: str
    chain: list
    spot: float
    now: datetime


def book_ranks(chain: list[dict], spot: float) -> dict[str, float]:
    """Return the whole book's strike ranks, worked out from the raw chain outside the program.

    Per strike, over every contract of every expiry, with Schwab's gamma and delta as sent: the
    size of gamma x open interest x multiplier x spot^2 x 1% (GEX) and of delta x open interest x
    multiplier x spot (DEX). Call and put wall: the strike of the largest call / put GEX; absolute
    gamma: of the largest call GEX + put GEX (SpotGamma); key delta: of the largest call DEX + put
    DEX; call delta wall: of the largest call DEX. A Greek Schwab sent as no number (absent or
    -999), or a contract with no open interest, is left out of that sum.
    """
    # each rank's own running total by strike, of the contracts it sums
    ranks = {
        "call_wall": ("gamma", {"CALL"}),
        "put_wall": ("gamma", {"PUT"}),
        "absolute_gamma_strike": ("gamma", {"CALL", "PUT"}),
        "key_delta_strike": ("delta", {"CALL", "PUT"}),
        "call_delta_wall": ("delta", {"CALL"}),
    }
    scale = {"gamma": spot**2 * 0.01, "delta": spot}
    totals: dict[str, dict[float, float]] = {name: {} for name in ranks}
    for c in chain:
        oi = c.get("openInterest")
        for name, (field, sides) in ranks.items():
            v = c.get(field)
            if (
                c["putCall"] in sides
                and isinstance(v, (int, float))
                and v != -999
                and oi is not None
            ):
                by_strike, k = totals[name], c["strikePrice"]
                by_strike[k] = by_strike.get(k, 0) + abs(v) * oi * c["multiplier"] * scale[field]
    return {name: max(by_strike, key=by_strike.__getitem__) for name, by_strike in totals.items()}


def _load(name: str) -> RealChain:
    d = json.loads((_FX / name).read_text(encoding="utf-8"))
    return RealChain(
        d["ticker"], d["chain"], float(d["spot"]), datetime.fromtimestamp(d["ts_utc"], ET)
    )


_SPY_FULL = json.loads((_FX / "real_spy_full_chain_2026_11_09.json").read_text(encoding="utf-8"))
#: SPY's whole chain (35 expiries, 12,904 contracts), production's complete capture of 2026-11-09
#: 11:06 ET, at its capture
SPY_FULL = RealChain(
    "SPY",
    _SPY_FULL["chain"],
    float(_SPY_FULL["spot"]),
    datetime.fromtimestamp(_SPY_FULL["capture_ts_utc"], ET),
)
SPY_0DTE = _load("real_spy_0dte_chain_2026_10_07.json")
CRWD = _load("real_crwd_complete_chain_2026_10_07.json")
TSLA = _load("real_tsla_complete_chain_2026_10_07.json")
MRVL = _load("real_mrvl_full_chain_2026_10_07.json")
NFLX = _load("real_nflx_chain_2026_10_07_three_expiries.json")


def crwd_exposures(chain: list[dict]) -> dict[float, dict]:
    """Return the per-strike exposures of `chain` (CRWD's or a copy) at CRWD's price, capture."""
    return compute_exposures_by_strike(
        read_chain(chain), spot=CRWD.spot, now=CRWD.now, sessions=sessions()
    )[0]


def spy_0dte_book() -> tuple[list[OptionContract], float]:
    """SPY_0DTE's contracts as the one reader reads them, and its price."""
    return read_chain(SPY_0DTE.chain), SPY_0DTE.spot


SPY_CLOSE = _load("real_spy_close_capture_and_after_hours_print_2026_10_22.json")
#: SPY's first LEVELONE_EQUITIES message with a LAST_PRICE from 18:00 ET 2026-10-22, as recorded
_SPY_CLOSE_FX = json.loads(
    (_FX / "real_spy_close_capture_and_after_hours_print_2026_10_22.json").read_text(
        encoding="utf-8"
    )
)
SPY_AFTER_HOURS_PRINT = _SPY_CLOSE_FX["after_hours_print"]
#: SPY's first LEVELONE_EQUITIES message after that capture whose LAST_PRICE is a strike from it
SPY_PRINT_A_STRIKE_AWAY = _SPY_CLOSE_FX["print_a_strike_away"]
#: SPY's first LEVELONE_EQUITIES message after that capture whose LAST_PRICE is one of its strikes
#: (764.00, received 16:33:27 ET): the first of the three, then SPY_PRINT_A_STRIKE_AWAY (16:39:03),
#: then SPY_AFTER_HOURS_PRINT (18:00)
SPY_PRINT_ON_A_STRIKE = json.loads(
    (_FX / "real_spy_print_on_a_strike_2026_10_22.json").read_text(encoding="utf-8")
)
