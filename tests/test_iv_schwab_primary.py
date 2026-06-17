"""OP-013: _extract_iv_for_strike uses Schwab volatility only (not theoreticalVolatility)."""

from __future__ import annotations

from math_volatility import _extract_iv_for_strike


def test_extract_iv_uses_volatility_not_theoretical():
    contracts = [
        {
            "strikePrice": 500.0,
            "putCall": "CALL",
            "volatility": 22.0,
            "theoreticalVolatility": 18.0,
        },
        {
            "strikePrice": 500.0,
            "putCall": "PUT",
            "volatility": 24.0,
            "theoreticalVolatility": 19.0,
        },
    ]
    call_iv, put_iv = _extract_iv_for_strike(contracts, 500.0)
    assert call_iv == 22.0
    assert put_iv == 24.0
