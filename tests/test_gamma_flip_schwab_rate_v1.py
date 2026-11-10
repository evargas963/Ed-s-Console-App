"""The gamma flip reprices each contract with Schwab's own rate and dividend yield.

The flip is the price where the book's dealer gamma (+call / -put), each contract's gamma
recomputed at that price, changes sign (SqueezeMetrics, SpotGamma). Each contract's gamma there
is the Black-Scholes-Merton gamma (Hull, Options, Futures and Other Derivatives, ch. 19):
e^(-qT) * phi(d1) / (S * sigma * sqrt(T)), d1 = (ln(S/K) + (r - q + sigma^2 / 2) T) /
(sigma * sqrt(T)), with Schwab's volatility, and r and q the chain's interestRate
(docs/schwab/schwab_market_data_api_spec.pdf p. 27, OptionChain) and dividendYield as Schwab sent
them, percents. The expected flip is worked out here, independently of the program's curve: the
same sum on a grid ten times finer, each crossing found by bisection, the one nearest the
price. T is the program's one time to expiry (time_et.time_to_expiry_years), tested on its own.

Real chains: CRWD, TSLA, MRVL and SPY's same-day chain of 2026-10-07 and SPY's whole chain of
2026-11-09, each valued at its capture.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from option_contract import read_chain
from terrain_engine import compute_terrain
from tests.real_chains import CRWD, MRVL, SPY_0DTE, SPY_FULL, TSLA, RealChain
from time_et import ET, option_close_product, time_to_expiry_years


def _number(x):
    """A value Schwab sent as a number, else None (rule 2: -999, text, NaN)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return None if not math.isfinite(x) or x == -999 else float(x)


def _inputs(book: RealChain):
    """Each contract with open interest that can be priced: K, T, sigma, r, q, signed OI x mult."""
    rows = []
    product = option_close_product(book.ticker)
    for c in book.chain:
        oi, k, iv, mult = (
            _number(c.get(f)) for f in ("openInterest", "strikePrice", "volatility", "multiplier")
        )
        r, q = _number(c.get("interestRate")), _number(c.get("dividendYield"))
        if not oi or None in (k, iv, mult, r, q) or iv <= 0 or c["putCall"] not in ("CALL", "PUT"):
            continue
        t = time_to_expiry_years(
            c["expirationDate"], book.now, settlement_type=c.get("settlementType"), product=product
        )
        if not t:
            continue
        sign = 1.0 if c["putCall"] == "CALL" else -1.0
        rows.append((k, t, iv / 100.0, r / 100.0, q / 100.0, sign * oi * mult))
    return np.array(rows).T


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


def _expected_flip(book: RealChain) -> float | None:
    k, t, sigma, r, q, w = _inputs(book)

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


@pytest.mark.parametrize(
    "book", [CRWD, TSLA, MRVL, SPY_0DTE, SPY_FULL], ids=lambda b: f"{b.ticker}-{b.now.date()}"
)
def test_the_flip_reprices_with_schwabs_rate_and_dividend_yield(book):
    snap = compute_terrain(book.ticker, read_chain(book.chain), book.spot, now=book.now)
    expected = _expected_flip(book)
    assert expected is not None
    # the program's curve is 240 straight steps across +/-15%: its crossing is within a few
    # hundred-thousandths of the price of the true one
    assert snap.gamma_flip == pytest.approx(expected, rel=5e-5)


def test_a_contract_schwab_sent_without_its_rate_is_not_priced():
    """SPY's same-day chain as captured 2026-09-22, before each contract carried the chain's rate.

    tests/fixtures/real_spy_0dte_chain.json carries no interestRate or dividendYield (the capture
    kept them from 2026-09-27): no contract is priced, they are counted "no_rate", and no flip is
    drawn. Nothing stands in for the rate Schwab's answer held but the capture did not keep.
    """
    held = json.loads(
        (Path(__file__).parent / "fixtures" / "real_spy_0dte_chain.json").read_text(
            encoding="utf-8"
        )
    )
    chain = read_chain(held["chain"])
    assert all(c.interest_rate is None and c.dividend_yield is None for c in chain)
    snap = compute_terrain(
        "SPY", chain, float(held["spot"]), now=datetime.fromtimestamp(held["ts_utc"], ET)
    )
    assert snap.flip_diag["unpriced"].get("no_rate", 0) > 0
    assert snap.gamma_flip is None and snap.profile == []
