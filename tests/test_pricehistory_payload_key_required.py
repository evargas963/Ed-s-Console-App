"""Fail-closed: Schwab pricehistory responses must include a ``candles`` key."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from polling_adapter import fetch_bars_via_schwab


def test_fetch_bars_via_schwab_raises_when_candles_key_missing():
    client = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"symbol": "SPY", "empty": True}
    client.get_price_history.return_value = resp

    with pytest.raises(ValueError, match="missing 'candles' key"):
        fetch_bars_via_schwab(client, "SPY", period_days=1)
