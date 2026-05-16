"""DFR-006 / OP-007: contract vs underlying spread precedence."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_decision.a2_option_expression import build_a2_option_expression
from v2_decision.a2_price_precedence import (
    resolve_a2_contract_spread,
    resolve_a2_underlying_spread_pts,
)
from v2_decision.module_a_adapter import build_module_a_a1_decision


def _sample_a1() -> dict:
    return build_module_a_a1_decision(
        {
            "ticker": "SPY",
            "fusion_available": True,
            "fusion_dominant_direction": "up",
            "fusion_dominant_prob": 0.64,
            "fusion_confidence": "high",
            "is_no_trade": False,
            "execution_mode": "STANDARD",
        }
    )


def _winner() -> dict:
    return {
        "expression": "500 CALL",
        "strike": 500.0,
        "side": "CALL",
        "chain_row": {
            "putCall": "CALL",
            "strikePrice": 500.0,
            "bid": 1.2,
            "ask": 1.3,
            "daysToExpiration": 0,
            "expirationDate": "2026-05-05",
            "quoteTimeInLong": 1778018399000,
        },
    }


def _ms(**overrides) -> dict:
    base = {
        "ticker": "SPY",
        "selected_exp": "2026-05-05",
        "call_option_expiry": "2026-05-05",
        "call_signal": "long",
        "is_no_trade": False,
        "liq_ok": True,
        "spread": 0.1,
        "option_chain_selection_proof": {
            "status": "ok",
            "winner": _winner(),
            "liquidity_summary": {"any_candidate_passed_liq_gate": True},
        },
    }
    base.update(overrides)
    return base


def test_contract_spread_never_reads_ms_dict_underlying():
    pts, src = resolve_a2_contract_spread(bid=1.2, ask=1.3)
    assert pts == 0.1
    assert src == "schwab_chain_bid_ask_pts"
    und, und_src = resolve_a2_underlying_spread_pts(ms_dict={"spread": 99.0, "spread_pts": 0.05})
    assert und == 0.05
    assert und_src == "underlying_spread_pts"


def test_a2_hard_gate_uses_chain_spread_not_ms_dict():
    ms = _ms(spread=99.0)
    a2 = build_a2_option_expression(ms, _sample_a1())
    oe = a2["option_expression"]
    assert oe["spread"]["value"] == 0.1
    assert oe["spread_source"]["value"] == "schwab_chain_bid_ask_pts"
    assert oe["underlying_spread_pts"]["value"] == 99.0
    assert "spread_exceeds_hard_threshold" not in a2["health"]["hard_gates_failed"]["value"]
