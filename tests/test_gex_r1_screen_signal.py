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


def test_gex_0dte_equals_live_computation_on_real_chain() -> None:
    """Screen GEX must equal the LIVE computation (single source of truth) on real data."""
    from math_exposure_core import aggregate_net_gex, compute_exposures_by_strike

    chain, spot = _load_real_chain()
    gex, n_c, n_p = gex_0dte_from_chain(chain, spot)
    exposures, _diag = compute_exposures_by_strike(chain, spot=spot, require_oi=False)
    live = aggregate_net_gex(exposures, sorted(exposures.keys()))
    assert math.isfinite(gex)
    assert gex == live
    assert n_c > 0 and n_p > 0


def test_filter_near_term_keeps_short_dte() -> None:
    contracts = [
        {"daysToExpiration": 0, "strikePrice": 1},
        {"daysToExpiration": 10, "strikePrice": 2},
        {"daysToExpiration": 90, "strikePrice": 3},
    ]
    near = filter_near_term_contracts(contracts)
    assert len(near) == 2
    assert {c["strikePrice"] for c in near} == {1, 2}
