from __future__ import annotations

from pathlib import Path


def test_rest_cum_delta_producer_retired_returns_none():
    src = Path("server.py").read_text(encoding="utf-8")
    assert "def _update_rest_cum_delta" in src
    assert "Retired second CVD producer. Always None." in src
    assert "last_price >= ask_price" not in src
    assert "_rest_cum_delta[" not in src
    assert "ms.cum_delta_proxy = _rest_cum_delta" not in src
