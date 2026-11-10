"""The terrain's Black-Scholes charm and vanna of one contract, as the arrays compute them.

bs_charm_array and bs_vanna_array (math_exposure_core) of a single contract; None where they give
NaN (a contract they cannot price).
"""

from __future__ import annotations

import math

import numpy as np

from math_exposure_core import bs_charm_array, bs_vanna_array


def _one(f, spot: float, strike: float, t_years: float, sigma: float) -> float | None:
    v = float(f(spot, np.array([strike]), np.array([t_years]), np.array([sigma]))[0])
    return None if math.isnan(v) else v


def charm(spot: float, strike: float, t_years: float, sigma: float) -> float | None:
    return _one(bs_charm_array, spot, strike, t_years, sigma)


def vanna(spot: float, strike: float, t_years: float, sigma: float) -> float | None:
    return _one(bs_vanna_array, spot, strike, t_years, sigma)
