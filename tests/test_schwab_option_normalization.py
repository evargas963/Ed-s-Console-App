from __future__ import annotations

import json

from chains import contract_fields
import realized_contract_eval as rce
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


def test_serialize_option_chain_for_eval_uses_normalized_contract_accessor(monkeypatch):
    raw = _schwab_contract()
    calls: list[str | None] = []
    real_contract_fields = rce.contract_fields

    def tracking_contract_fields(ct: dict) -> dict:
        calls.append(ct.get("symbol"))
        return real_contract_fields(ct)

    monkeypatch.setattr(rce, "contract_fields", tracking_contract_fields)

    payload = serialize_option_chain_for_eval([raw], "2026-05-05")

    rows = json.loads(payload or "[]")
    assert calls == ["SPY260505C00500000"]
    assert rows[0]["ask"] == raw["ask"]
    assert rows[0]["bid"] == raw["bid"]
    assert rows[0]["quoteTimeInLong"] == raw["quoteTimeInLong"]
    assert "raw" not in rows[0]


def test_replay_contract_selection_and_pnl_match_raw_and_normalized_rows():
    entry_raw = _schwab_contract()
    exit_raw = {**_schwab_contract(), "bid": 1.55, "ask": 1.65}
    entry_normalized = contract_fields(entry_raw)
    exit_normalized = contract_fields(exit_raw)

    raw_pnl = rce._contract_pnl_at_horizon(
        strike=500.0,
        put_call="CALL",
        entry_chain=[entry_raw],
        exit_chain=[exit_raw],
        symbol_hint=entry_raw["symbol"],
    )
    normalized_pnl = rce._contract_pnl_at_horizon(
        strike=500.0,
        put_call="CALL",
        entry_chain=[entry_normalized],
        exit_chain=[exit_normalized],
        symbol_hint=entry_raw["symbol"],
    )

    assert raw_pnl == normalized_pnl
    assert raw_pnl == 25.0


def test_normalize_contract_chain_uses_accessor_for_replay_archive(monkeypatch):
    raw = _schwab_contract()
    calls = 0
    real_contract_fields = rce.contract_fields

    def tracking_contract_fields(ct: dict) -> dict:
        nonlocal calls
        calls += 1
        return real_contract_fields(ct)

    monkeypatch.setattr(rce, "contract_fields", tracking_contract_fields)

    normalized = rce._normalize_contract_chain([raw])

    assert calls == 1
    assert normalized[0]["symbol"] == raw["symbol"]
    assert normalized[0]["bid"] == raw["bid"]
    assert normalized[0]["ask"] == raw["ask"]
    assert "raw" not in normalized[0]

