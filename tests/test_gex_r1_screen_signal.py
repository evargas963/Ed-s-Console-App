"""Unit tests for GEX-R1-SCREEN 0DTE signal + morning full filter.

GEX correctness is proven on a REAL captured chain
(tests/fixtures/real_spy_0dte_chain_with_poison.json), never a hand-built one.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from calibration.option_chain_morning_full import filter_near_term_contracts
from research.gex_r1_screen_v1.signal import gex_0dte_from_chain

_REAL_CHAIN = Path(__file__).parent / "fixtures" / "real_spy_0dte_chain_with_poison.json"


def _load_real_chain() -> tuple[list, float]:
    data = json.loads(_REAL_CHAIN.read_text(encoding="utf-8"))
    return data["chain"], float(data["spot"])


def test_gex_0dte_is_the_live_exposure_faucet() -> None:
    """ONE-FAUCET identity: the screen must call the live exposure functions.

    This is not an independent mathematical oracle — ``gex_0dte_from_chain``
    delegates to those functions. The independent formula lock is
    ``test_gex_dollar_formula_independent_oracle``.
    """
    from math_exposure_core import aggregate_net_gex, compute_exposures_by_strike

    chain, spot = _load_real_chain()
    gex, n_c, n_p = gex_0dte_from_chain(chain, spot)
    exposures, _diag = compute_exposures_by_strike(chain, spot=spot, require_oi=False)
    live = aggregate_net_gex(exposures, sorted(exposures.keys()))
    assert math.isfinite(gex)
    assert gex == live
    assert n_c >= 1 and n_p >= 1


def test_gex_dollar_formula_independent_oracle() -> None:
    """Hand-derived GEX$ per 1%: gamma * OI * mult * spot² * 0.01; net = call − put.

    Expected values are computed in this test, not by calling production.
    """
    from math_exposure_core import aggregate_net_gex, compute_exposures_by_strike

    spot = 100.0
    call_gex = 0.05 * 200 * 100 * spot * spot * 0.01  # 100_000
    put_gex = 0.04 * 100 * 100 * spot * spot * 0.01   # 40_000
    expected_net = call_gex - put_gex                 # 60_000
    chain = [
        {
            "strikePrice": 100.0,
            "putCall": "CALL",
            "gamma": 0.05,
            "delta": 0.50,
            "openInterest": 200,
            "multiplier": 100,
        },
        {
            "strikePrice": 100.0,
            "putCall": "PUT",
            "gamma": 0.04,
            "delta": -0.45,
            "openInterest": 100,
            "multiplier": 100,
        },
    ]
    screen, n_c, n_p = gex_0dte_from_chain(chain, spot)
    exposures, _diag = compute_exposures_by_strike(chain, spot=spot, require_oi=False)
    core = aggregate_net_gex(exposures, sorted(exposures.keys()))
    assert n_c == 1 and n_p == 1
    assert screen == expected_net == core
    # Sign / convention mutations that must not survive.
    assert screen != call_gex + put_gex
    assert screen != -expected_net
    missing_spot_sq = (0.05 * 200 * 100 * spot * 0.01) - (0.04 * 100 * 100 * spot * 0.01)
    assert screen != missing_spot_sq
    nan_gex, zc, zp = gex_0dte_from_chain(chain, 0.0)
    assert math.isnan(nan_gex) and zc == 0 and zp == 0


def test_filter_near_term_keeps_short_dte() -> None:
    contracts = [
        {"daysToExpiration": 0, "strikePrice": 1},
        {"daysToExpiration": 10, "strikePrice": 2},
        {"daysToExpiration": 90, "strikePrice": 3},
    ]
    near = filter_near_term_contracts(contracts)
    assert len(near) == 2
    assert {c["strikePrice"] for c in near} == {1, 2}
