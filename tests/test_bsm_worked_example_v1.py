"""The program's Black-Scholes-Merton gamma and delta against the textbook's worked option.

Hull, Options, Futures and Other Derivatives, ch. 19 (the Greek letters), works one option
through the chapter: a stock at 49, a strike of 50, a risk-free rate of 5% a year, a volatility
of 20% a year, 20 weeks to expiry (20/52 of a year), no dividend. The text gives its delta as
0.522 and its gamma as 0.066, and a put's delta as the call's less 1. These are numbers published
outside this repository, so they check math_exposure_core.bsm_gamma_delta (the gamma the gamma
profile, the flip and the support levels sum) against a source, not against itself.
"""

from __future__ import annotations

from calc.math_exposure_core import bsm_gamma_delta

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
