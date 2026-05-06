from __future__ import annotations

import json

from chains import contract_fields
from realized_contract_eval import serialize_option_chain_for_eval


def _schwab_contract() -> dict:
    return {
        "symbol": "SPY260505C00500000",
        "underlyingSymbol": "SPY",
        "putCall": "CALL",
        "strikePrice": 500.0,
        "expirationDate": "2026-05-05",
        "bid": 1.2,
        "ask": 1.3,
        "bidSize": 10,
        "askSize": 14,
        "mark": 1.25,
        "last": 1.24,
        "totalVolume": 1200,
        "openInterest": 4300,
        "delta": 0.52,
        "gamma": 0.08,
        "theta": -0.18,
        "vega": 0.02,
        "rho": 0.01,
        "volatility": 22.0,
        "theoreticalVolatility": 21.5,
        "theoreticalOptionValue": 1.27,
        "daysToExpiration": 0,
        "quoteTimeInLong": 1778018400000,
        "tradeTimeInLong": 1778018399000,
        "openPrice": 0.9,
        "highPrice": 1.4,
        "lowPrice": 0.8,
        "closePrice": 1.1,
        "lastSize": 3,
        "bidAskSize": "10X14",
        "expirationType": "W",
        "settlementType": "P",
        "exerciseType": "A",
        "inTheMoney": True,
        "nonStandard": False,
        "mini": False,
        "lastTradingDay": 1778025600000,
    }


def test_contract_fields_promotes_schwab_theta_rho_and_timestamps():
    raw = _schwab_contract()
    normalized = contract_fields(raw)

    assert normalized["theta"] == raw["theta"]
    assert normalized["rho"] == raw["rho"]
    assert normalized["quoteTimeInLong"] == raw["quoteTimeInLong"]
    assert normalized["tradeTimeInLong"] == raw["tradeTimeInLong"]
    assert normalized["raw"]["theta"] == raw["theta"]
    assert normalized["raw"]["rho"] == raw["rho"]


def test_contract_fields_promotes_option_chain_context_fields():
    raw = _schwab_contract()
    normalized = contract_fields(raw)

    for field in (
        "theoreticalOptionValue",
        "openPrice",
        "highPrice",
        "lowPrice",
        "closePrice",
        "lastSize",
        "bidAskSize",
        "expirationType",
        "settlementType",
        "exerciseType",
        "inTheMoney",
        "nonStandard",
        "mini",
        "lastTradingDay",
    ):
        assert normalized[field] == raw[field]


def test_serialize_option_chain_for_eval_preserves_schwab_greeks_and_times():
    raw = _schwab_contract()
    payload = serialize_option_chain_for_eval([contract_fields(raw)], "2026-05-05")

    rows = json.loads(payload or "[]")
    assert rows[0]["theta"] == raw["theta"]
    assert rows[0]["rho"] == raw["rho"]
    assert rows[0]["quoteTimeInLong"] == raw["quoteTimeInLong"]
    assert rows[0]["tradeTimeInLong"] == raw["tradeTimeInLong"]

