from __future__ import annotations

from market_state import _oe_chain_row_snapshot, recommend_option_expression
from v2_decision.a2_option_expression import build_a2_option_expression
from v2_decision.module_a_adapter import build_module_a_a1_decision


def _rich_contract(**overrides) -> dict:
    base = {
        "symbol": "SPY260505C00500000",
        "putCall": "CALL",
        "strikePrice": 500.0,
        "expirationDate": "2026-05-05T20:00:00.000+00:00",
        "expiration": "2026-05-05",
        "expirationType": "W",
        "settlementType": "P",
        "exerciseType": "A",
        "lastTradingDay": 1778025600000,
        "bid": 1.2,
        "ask": 1.3,
        "mark": 1.25,
        "last": 1.24,
        "openPrice": 0.9,
        "highPrice": 1.4,
        "lowPrice": 0.8,
        "closePrice": 1.1,
        "bidSize": 10,
        "askSize": 14,
        "bidAskSize": "10X14",
        "lastSize": 3,
        "totalVolume": 1200,
        "volume": 1200,
        "openInterest": 4300,
        "delta": 0.52,
        "gamma": 0.08,
        "theta": -0.18,
        "vega": 0.02,
        "rho": 0.01,
        "volatility": 22.0,
        "theoreticalVolatility": 21.5,
        "theoreticalOptionValue": 1.27,
        "quoteTimeInLong": 1778018399000,
        "tradeTimeInLong": 1778018398500,
        "multiplier": 100,
        "extrinsicValue": 1.0,
        "timeValue": 1.0,
        "intrinsicValue": 0.25,
        "inTheMoney": True,
        "nonStandard": False,
        "mini": False,
        "pennyPilot": True,
        "deliverableNote": "",
        "raw": {"theta": -0.19, "quoteTimeInLong": 1778018398000},
    }
    base.update(overrides)
    return base


def _a1_trade() -> dict:
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


def _ms_from_proof(proof: dict) -> dict:
    return {
        "ticker": "SPY",
        "selected_exp": "2026-05-05",
        "call_option_expiry": "2026-05-05",
        "dte_warn": "0DTE",
        "call_signal": "long",
        "is_no_trade": False,
        "rec_strike": 500.0,
        "rec_side": "CALL",
        "call_option_right": "CALL",
        "liq_ok": True,
        "spread": 0.1,
        "ratio": 6.5,
        "vol_oi": 0.279,
        "spot": 499.5,
        "mins_to_close": 120.0,
        "decision_time_ms": 1778018400000,
        "option_chain_selection_proof": proof,
        "contract_context": "SPY 2026-05-05 500C · 0DTE · mid≈1.25",
    }


def test_oe_chain_row_snapshot_preserves_a2_required_schwab_fields():
    """Contract: A2_MARKET_STATE_PROOF_ROW_COMPLETENESS_CONTRACT.md - required fields."""
    raw = _rich_contract()
    snapshot = _oe_chain_row_snapshot(raw)

    required = {
        "symbol",
        "putCall",
        "strikePrice",
        "expirationDate",
        "expiration",
        "expirationType",
        "settlementType",
        "exerciseType",
        "lastTradingDay",
        "bid",
        "ask",
        "mark",
        "last",
        "openPrice",
        "highPrice",
        "lowPrice",
        "closePrice",
        "bidSize",
        "askSize",
        "bidAskSize",
        "lastSize",
        "totalVolume",
        "volume",
        "openInterest",
        "delta",
        "gamma",
        "theta",
        "vega",
        "rho",
        "volatility",
        "theoreticalVolatility",
        "theoreticalOptionValue",
        "quoteTimeInLong",
        "tradeTimeInLong",
        "multiplier",
        "extrinsicValue",
        "timeValue",
        "intrinsicValue",
        "inTheMoney",
        "nonStandard",
        "mini",
        "pennyPilot",
        "deliverableNote",
    }
    assert set(snapshot or {}) == required
    assert snapshot["theta"] == raw["theta"]
    assert snapshot["rho"] == raw["rho"]
    assert snapshot["quoteTimeInLong"] == raw["quoteTimeInLong"]
    assert snapshot["tradeTimeInLong"] == raw["tradeTimeInLong"]
    assert "raw" not in snapshot


def test_recommend_option_expression_winner_carries_full_schwab_chain_row():
    """Regression: real market_state proof path must not truncate fields before A2."""
    _, _, proof = recommend_option_expression(
        contracts=[_rich_contract()],
        spot=499.5,
        call_signal="long",
        walls=None,
        selected_expiry="2026-05-05",
    )

    chain_row = proof["winner"]["chain_row"]
    assert chain_row["theta"] == -0.18
    assert chain_row["rho"] == 0.01
    assert chain_row["volatility"] == 22.0
    assert chain_row["quoteTimeInLong"] == 1778018399000
    assert chain_row["tradeTimeInLong"] == 1778018398500
    assert proof["chain_rows_scored"][0]["chain_row"]["theta"] == -0.18
    assert proof["ranked_candidates_top5"][0]["chain_row"]["quoteTimeInLong"] == 1778018399000


def test_market_state_proof_feeds_schwab_theta_and_quote_timestamp_to_a2():
    """V3 I-01: no silent substitution when Schwab theta/timestamps are available."""
    _, _, proof = recommend_option_expression(
        contracts=[_rich_contract()],
        spot=499.5,
        call_signal="long",
        walls=None,
        selected_expiry="2026-05-05",
    )

    a2 = build_a2_option_expression(_ms_from_proof(proof), _a1_trade())

    assert a2["option_expression"]["option_action"]["value"] == "TRADE"
    assert "theta_unavailable" not in a2["health"]["hard_gates_failed"]["value"]
    assert "missing_quote_timestamp" not in a2["health"]["hard_gates_failed"]["value"]
    assert a2["greeks"]["theta"] == {
        "value": -0.18,
        "source": "v2_compliant",
        "detail": "schwab_chain_theta",
    }
    assert a2["execution"]["quote_staleness_ms"] == {
        "value": 1000,
        "source": "v2_compliant",
    }


def test_recommend_option_expression_no_contract_path_does_not_fabricate_chain_row():
    """Contract: missing selected row must fail closed without fabricated Schwab fields."""
    _, _, proof = recommend_option_expression(
        contracts=[],
        spot=499.5,
        call_signal="long",
        walls=None,
        selected_expiry="2026-05-05",
    )

    assert proof["status"] == "no_trade"
    assert proof["reason"] == "no_contracts_for_side"
    assert "winner" not in proof
