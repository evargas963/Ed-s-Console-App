"""OPTIONS_ORDER_FLOW_V1 — schwab_client.safe_get_chain's strike_range support.

strike_range is a DIFFERENT vendor selection dimension than strike_count (MEASURED live:
strike_count=250 alone missed 69 real SPY strikes strike_range="ALL" correctly returned,
see tests/fixtures/real_spy_strike_count_vs_strike_range_all_evidence.json). This file
proves the exact kwarg-passing contract the completeness fix depends on: when strike_range
is given, strike_count is OMITTED entirely — never sent alongside it, since that combination
was never the one measured live.
"""

from __future__ import annotations

from datetime import date

from schwab_client import safe_get_chain


class _FakeClient:
    def __init__(self):
        self.calls = []

    def get_option_chain(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))
        return object()


def test_default_call_shape_is_unchanged(monkeypatch):
    """Every EXISTING caller passes strike_count with no strike_range — that shape must
    be byte-for-byte unchanged by this addition."""
    monkeypatch.setattr("schwab_client._block_live_schwab_in_ci_offline", lambda: None)
    monkeypatch.setattr("schwab_client._schwab_auth_latched", lambda: False)
    client = _FakeClient()
    safe_get_chain(client, "SPY", strike_count=20)
    symbol, kwargs = client.calls[0]
    assert symbol == "SPY"
    assert kwargs["strike_count"] == 20
    assert "strike_range" not in kwargs


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


def test_strike_range_takes_precedence_if_both_somehow_given(monkeypatch):
    """Defensive: if a caller passes both (never done by any current call site), the
    vendor-proven shape (range only) wins — never an untested combined request."""
    monkeypatch.setattr("schwab_client._block_live_schwab_in_ci_offline", lambda: None)
    monkeypatch.setattr("schwab_client._schwab_auth_latched", lambda: False)
    client = _FakeClient()
    safe_get_chain(client, "SPY", strike_count=20, strike_range="ALL")
    _symbol, kwargs = client.calls[0]
    assert kwargs["strike_range"] == "ALL"
    assert "strike_count" not in kwargs
