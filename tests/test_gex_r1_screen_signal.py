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


def _first_usable_side(chain: list, side: str) -> dict:
    """First real fixture contract on ``side`` that the live sanitizer would count."""
    from math_exposure_core import gamma_is_plausible

    for row in chain:
        if str(row.get("putCall") or "").upper() != side:
            continue
        try:
            gamma = float(row["gamma"])
            oi = float(row["openInterest"])
        except (KeyError, TypeError, ValueError):
            continue
        try:
            delta = float(row["delta"]) if row.get("delta") is not None else None
        except (TypeError, ValueError):
            delta = None
        if gamma > 0.0 and oi > 0.0 and gamma_is_plausible(gamma, delta):
            return row
    raise AssertionError(f"real fixture has no usable {side} (plausible gamma and OI>0)")


def test_gex_dollar_formula_independent_oracle() -> None:
    """Hand-derived GEX$ per 1%: gamma * OI * mult * spot² * 0.01; net = call − put.

    Contracts come from the captured chain (no inline synthetic option dict).
    Expected values are computed in this test, not by calling production.
    """
    from math_exposure_core import aggregate_net_gex, compute_exposures_by_strike

    full, spot = _load_real_chain()
    call_row = _first_usable_side(full, "CALL")
    put_row = _first_usable_side(full, "PUT")
    chain = [call_row, put_row]
    call_gex = (
        float(call_row["gamma"]) * float(call_row["openInterest"])
        * float(call_row.get("multiplier") or 100)
        * spot * spot * 0.01
    )
    put_gex = (
        float(put_row["gamma"]) * float(put_row["openInterest"])
        * float(put_row.get("multiplier") or 100)
        * spot * spot * 0.01
    )
    expected_net = call_gex - put_gex
    screen, n_c, n_p = gex_0dte_from_chain(chain, spot)
    exposures, _diag = compute_exposures_by_strike(chain, spot=spot, require_oi=False)
    core = aggregate_net_gex(exposures, sorted(exposures.keys()))
    assert n_c == 1 and n_p == 1
    assert screen == expected_net == core
    # Sign / convention mutations that must not survive.
    assert screen != call_gex + put_gex
    assert screen != -expected_net
    missing_spot_sq = (
        float(call_row["gamma"]) * float(call_row["openInterest"])
        * float(call_row.get("multiplier") or 100) * spot * 0.01
    ) - (
        float(put_row["gamma"]) * float(put_row["openInterest"])
        * float(put_row.get("multiplier") or 100) * spot * 0.01
    )
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
