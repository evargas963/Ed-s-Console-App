"""The program's Black-Scholes-Merton gamma and delta against the textbook's worked option.

Hull, Options, Futures and Other Derivatives, ch. 19 (the Greek letters), works one option
through the chapter: a stock at 49, a strike of 50, a risk-free rate of 5% a year, a volatility
of 20% a year, 20 weeks to expiry (20/52 of a year), no dividend. The text gives its delta as
0.522 and its gamma as 0.066, and a put's delta as the call's less 1. These are numbers published
outside this repository, so they check math_exposure_core.bsm_gamma_delta (the gamma the gamma
profile, the flip and the support levels sum) against a source, not against itself.
"""

from __future__ import annotations

import math
from datetime import datetime

from calc.math_exposure_core import bsm_gamma_delta
from tests.real_chains import MRVL

#: Hull's worked option: price, strike, years to expiry, volatility, rate, dividend yield
S, K, T, SIGMA, R, Q = 49.0, 50.0, 20 / 52, 0.20, 0.05, 0.0


def test_the_worked_options_delta_and_gamma_are_the_textbooks():
    gamma, delta = bsm_gamma_delta(S, K, T, SIGMA, 1, R, Q)
    assert round(delta, 3) == 0.522
    assert round(gamma, 3) == 0.066


def test_a_puts_delta_is_the_calls_less_one_and_its_gamma_the_calls():
    call_gamma, call_delta = bsm_gamma_delta(S, K, T, SIGMA, 1, R, Q)
    put_gamma, put_delta = bsm_gamma_delta(S, K, T, SIGMA, -1, R, Q)
    assert abs(put_delta - (call_delta - 1.0)) < 1e-12
    assert put_gamma == call_gamma


def test_on_schwabs_inputs_the_gamma_and_delta_are_the_formulas():
    """MRVL's contracts within 15 of the price, on Schwab's own inputs, against the formula.

    tests/fixtures/real_mrvl_full_chain_2026_10_07.json: each contract's volatility, interest rate
    and dividend yield as Schwab sent them (percents), at the price Schwab sent in the chain and
    the time to its expirationDate from the capture, from 2 days to 835. The expected gamma and
    delta are Black-Scholes-Merton's (Hull ch. 19), worked out here from the normal density and
    the error function, outside the program.
    """
    priced = 0
    for c in MRVL.chain:
        k = c["strikePrice"]
        if abs(k - MRVL.spot) > 15:
            continue
        expiry = datetime.fromisoformat(c["expirationDate"]).timestamp()
        t = (expiry - MRVL.now.timestamp()) / (365 * 86400)
        sigma, r, q = c["volatility"] / 100, c["interestRate"] / 100, c["dividendYield"] / 100
        sign = 1 if c["putCall"] == "CALL" else -1
        d1 = (math.log(MRVL.spot / k) + (r - q + sigma**2 / 2) * t) / (sigma * math.sqrt(t))
        density = math.exp(-(d1**2) / 2) / math.sqrt(2 * math.pi)
        gamma = math.exp(-q * t) * density / (MRVL.spot * sigma * math.sqrt(t))
        below = (1 + math.erf(d1 / math.sqrt(2))) / 2
        delta = math.exp(-q * t) * (below if sign == 1 else below - 1)
        got_gamma, got_delta = bsm_gamma_delta(MRVL.spot, k, t, sigma, sign, r, q)
        assert math.isclose(got_gamma, gamma, rel_tol=1e-9), c["symbol"]
        assert math.isclose(got_delta, delta, rel_tol=1e-9, abs_tol=1e-12), c["symbol"]
        priced += 1
    assert priced > 100
