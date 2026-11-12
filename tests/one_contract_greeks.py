"""The terrain's Black-Scholes-Merton charm and vanna of one contract, as the arrays compute them.

bs_charm_array and bs_vanna_array (math_exposure_core) of a single contract, with the rate and
dividend yield as decimals (0 unless given); None where they give NaN (a contract they cannot
price).
"""

from __future__ import annotations

import math

import numpy as np

from math_exposure_core import bs_charm_array, bs_vanna_array


def _value(v) -> float | None:
    v = float(v[0])
    return None if math.isnan(v) else v


def charm(
    spot: float,
    strike: float,
    t_years: float,
    sigma: float,
    sign: int = 1,
    rate: float = 0.0,
    dividend: float = 0.0,
) -> float | None:
    one = (np.array([x], float) for x in (strike, t_years, sigma, sign, rate, dividend))
    return _value(bs_charm_array(spot, *one))


def vanna(
    spot: float,
    strike: float,
    t_years: float,
    sigma: float,
    rate: float = 0.0,
    dividend: float = 0.0,
) -> float | None:
    one = (np.array([x], float) for x in (strike, t_years, sigma, rate, dividend))
    return _value(bs_vanna_array(spot, *one))
