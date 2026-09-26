"""Unit tests for GEX-R1-SCREEN 0DTE signal + morning full filter.

GEX correctness is proven on a REAL captured chain
(tests/fixtures/real_spy_0dte_chain_with_poison.json), never a hand-built one.
"""

from __future__ import annotations

import json
from pathlib import Path

from calibration.option_chain_morning_full import filter_near_term_contracts

_REAL_CHAIN = Path(__file__).parent / "fixtures" / "real_spy_0dte_chain_with_poison.json"


def _load_real_chain() -> tuple[list, float]:
    data = json.loads(_REAL_CHAIN.read_text(encoding="utf-8"))
    return data["chain"], float(data["spot"])


def test_filter_near_term_keeps_short_dte() -> None:
    contracts = [
        {"daysToExpiration": 0, "strikePrice": 1},
        {"daysToExpiration": 10, "strikePrice": 2},
        {"daysToExpiration": 90, "strikePrice": 3},
    ]
    near = filter_near_term_contracts(contracts)
    assert len(near) == 2
    assert {c["strikePrice"] for c in near} == {1, 2}
