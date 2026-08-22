from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from server import _update_rest_cum_delta


def test_rest_cum_delta_producer_retired_returns_none():
    src = Path("server.py").read_text(encoding="utf-8")
    assert "def _update_rest_cum_delta" in src
    assert "Retired second CVD producer. Always None." in src
    assert "last_price >= ask_price" not in src
    assert "_rest_cum_delta[" not in src
    assert "ms.cum_delta_proxy = _rest_cum_delta" not in src
    now = datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc)
    assert _update_rest_cum_delta("SPY", {"lastPrice": 500.0, "askPrice": 499.0}, now) is None
    assert _update_rest_cum_delta("QQQ", {}, now) is None
    assert _update_rest_cum_delta("IWM", {"lastPrice": 1, "bidPrice": 1, "askPrice": 2}, now) is None
