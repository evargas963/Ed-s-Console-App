"""schwab_client.safe_get_chain asks Schwab for a strike range and never a strike count."""

from __future__ import annotations

from datetime import date

from schwab_client import safe_get_chain


class _FakeClient:
    def __init__(self):
        self.calls = []

    def get_option_chain(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))
        return object()


def test_strike_range_omits_strike_count_entirely(monkeypatch):
    """The exact combination proven live: strike_range='ALL' alone, strike_count never
    sent alongside it."""
    monkeypatch.setattr("schwab_client._block_live_schwab_in_ci_offline", lambda: None)
    monkeypatch.setattr("schwab_client._schwab_auth_latched", lambda: False)
    client = _FakeClient()
    d = date(2026, 8, 31)
    safe_get_chain(client, "TSLA", strike_range="ALL", from_date=d, to_date=d)
    symbol, kwargs = client.calls[0]
    assert symbol == "TSLA"
    assert kwargs["strike_range"] == "ALL"
    assert "strike_count" not in kwargs
    assert kwargs["from_date"] == d
    assert kwargs["to_date"] == d
