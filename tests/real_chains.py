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
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from calc.math_exposure_core import compute_exposures_by_strike
from option_contract import OptionContract, read_chain
from time_et import ET, option_close_product, sessions, time_to_expiry_years

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


_erf = np.vectorize(math.erf)


def _bsm_delta(s, k, t, sigma, sign, r, q):
    """Hull ch. 19, worked out here: e^(-qT) N(d1) for a call, e^(-qT) (N(d1) - 1) for a put."""
    d1 = (np.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * np.sqrt(t))
    n = 0.5 * (1.0 + _erf(d1 / math.sqrt(2.0)))
    return np.exp(-q * t) * np.where(sign > 0, n, n - 1.0)


def _number(x):
    """Return a value Schwab sent as a number, else None (rule 2: -999, text, NaN)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return None if not math.isfinite(x) or x == -999 else float(x)


def _schwab_inputs(book: RealChain):
    """Each contract that can be priced: K, T, sigma, sign, r, q, OI x multiplier.

    Read here from Schwab's own fields as numbers (_number), with open interest above 0, the rate
    and yield the chain's interestRate and dividendYield (percents), T the program's one time to
    expiry (tested on its own).
    """
    product = option_close_product(book.ticker)
    held = sessions()
    rows = []
    for c in book.chain:
        oi, k, iv, mult = (
            _number(c.get(f)) for f in ("openInterest", "strikePrice", "volatility", "multiplier")
        )
        r, q = _number(c.get("interestRate")), _number(c.get("dividendYield"))
        if not oi or None in (k, iv, mult, r, q) or iv <= 0 or c["putCall"] not in ("CALL", "PUT"):
            continue
        t = time_to_expiry_years(
            c["expirationDate"],
            book.now,
            sessions=held,
            settlement_type=c.get("settlementType"),
            product=product,
        )
        if not t:
            continue
        sign = 1.0 if c["putCall"] == "CALL" else -1.0
        rows.append((k, t, iv / 100.0, sign, r / 100.0, q / 100.0, oi * mult))
    return np.array(rows, float).T


def delta_derivatives(book: RealChain):
    """Return (inputs, dDelta/dt as T shrinks, dDelta/dSigma) per contract, outside the program.

    Central differences of the textbook Black-Scholes-Merton delta (_bsm_delta) at Schwab's
    volatility, rate and yield: each contract's charm and vanna, worked out apart from the code
    under test.
    """
    k, t, sigma, sign, r, q, size = _schwab_inputs(book)
    h, e = t * 1e-4, sigma * 1e-4
    charm_fd = (
        _bsm_delta(book.spot, k, t - h, sigma, sign, r, q)
        - _bsm_delta(book.spot, k, t + h, sigma, sign, r, q)
    ) / (2.0 * h)
    vanna_fd = (
        _bsm_delta(book.spot, k, t, sigma + e, sign, r, q)
        - _bsm_delta(book.spot, k, t, sigma - e, sign, r, q)
    ) / (2.0 * e)
    return (k, t, sigma, sign, r, q, size), charm_fd, vanna_fd


def _crossing(f, lo: float, hi: float) -> float:
    """Return where `f` changes sign between `lo` and `hi`, halving the gap 60 times."""
    f_lo = f(lo)
    for _ in range(60):
        mid = (lo + hi) / 2.0
        f_mid = f(mid)
        if f_lo * f_mid > 0:
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def gamma_flip_worked_out(book: RealChain) -> float | None:
    """Return the gamma flip nearest the price, worked out outside the program.

    The book's dealer gamma (+call / -put) with each contract's Black-Scholes-Merton gamma at
    the price (Hull ch. 19) on Schwab's volatility, rate and yield, summed on a grid of 2,401
    prices over +-15% of the price; each sign change found by bisection; the one nearest the price.
    """
    k, t, sigma, sign, r, q, size = _schwab_inputs(book)
    w = sign * size  # the dealer convention: +call / -put

    def gex(s: float) -> float:
        vt = sigma * np.sqrt(t)
        d1 = (np.log(s / k) + (r - q + 0.5 * sigma**2) * t) / vt
        phi = np.exp(-0.5 * d1**2) / math.sqrt(2.0 * math.pi)
        g = np.exp(-q * t) * phi / (s * vt)
        return float(np.sum(g * w) * s * s * 0.01)

    xs = np.linspace(book.spot * 0.85, book.spot * 1.15, 2401)
    ys = [gex(x) for x in xs]
    roots = [
        _crossing(gex, xs[i - 1], xs[i])
        for i in range(1, len(xs))
        if ys[i - 1] == 0 or ys[i - 1] * ys[i] < 0
    ]
    return min(roots, key=lambda x: abs(x - book.spot)) if roots else None


def charm_walls(book: RealChain) -> tuple[float, float]:
    """Return (call charm wall, put charm wall) of a one-expiry book, outside the program.

    Per strike and side, the contracts' charm (delta_derivatives) x open interest x multiplier
    summed; each wall the strike of the largest absolute sum on its side.
    """
    (k, _t, _sigma, sign, _r, _q, size), charm_fd, _vanna_fd = delta_derivatives(book)
    walls = []
    for side in (1.0, -1.0):
        by_strike: dict[float, float] = {}
        for strike, value in zip(k[sign == side], (charm_fd * size)[sign == side], strict=True):
            by_strike[float(strike)] = by_strike.get(float(strike), 0) + float(value)
        walls.append(max(by_strike, key=lambda s: abs(by_strike[s])))
    return walls[0], walls[1]


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
