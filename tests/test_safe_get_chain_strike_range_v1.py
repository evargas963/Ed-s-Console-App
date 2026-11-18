"""OPTIONS_ORDER_FLOW_V1 — schwab_client.safe_get_chain's strike_range support.

strike_range is a DIFFERENT vendor selection dimension than strike_count (MEASURED live:
strike_count=250 alone missed 69 real SPY strikes strike_range="ALL" correctly returned,
see tests/fixtures/real_spy_strike_count_vs_strike_range_all_evidence.json). This file
proves the exact request the completeness fix depends on, as Schwab receives it from the
daemon's own schwab-py client (tests/schwab_rest_standin.LocalSchwab): when strike_range is
given, strike_count is OMITTED entirely — never sent alongside it, since that combination was
never the one measured live.
"""

from __future__ import annotations

from datetime import date

import pytest

from feed.schwab_client import safe_get_chain
from tests.schwab_rest_standin import CHAIN, LocalSchwab


@pytest.fixture
def asked(tmp_path):
    """Send safe_get_chain's requests to the local Schwab; return each /chains query it took."""
    schwab = LocalSchwab("ws://127.0.0.1:1")  # REST only: no stream connection is opened
    client = schwab.client(tmp_path)
    try:
        yield lambda *a, **k: (safe_get_chain(client, *a, **k), schwab.asked(CHAIN)[-1])[1]
    finally:
        schwab.close()


def test_default_call_shape_is_unchanged(asked):
    """Every EXISTING caller passes strike_count with no strike_range.

    That shape must be byte-for-byte unchanged by this addition.
    """
    q = asked("SPY", strike_count=20)
    assert q["symbol"] == "SPY"
    assert q["strikeCount"] == "20"
    assert "range" not in q


def test_strike_range_omits_strike_count_entirely(asked):
    """The exact combination proven live: strike_range='ALL' alone.

    strike_count is never sent alongside it.
    """
    d = date(2026, 10, 9)
    q = asked("TSLA", strike_range="ALL", from_date=d, to_date=d)
    assert q["symbol"] == "TSLA"
    assert q["range"] == "ALL"
    assert "strikeCount" not in q
    assert q["fromDate"] == "2026-10-09"
    assert q["toDate"] == "2026-10-09"


def test_the_stock_quote_the_stream_pushes_is_not_asked_of_chains(asked):
    """A chain request does not ask for the underlying's quote: LEVELONE_EQUITIES pushes it.

    Every chain request the program sends, in both shapes, leaves `includeUnderlyingQuote` out.
    """
    d = date(2026, 10, 9)
    shapes = [asked("SPY", strike_count=20), asked("TSLA", strike_range="ALL", from_date=d)]
    assert ["includeUnderlyingQuote" in q for q in shapes] == [False, False]


def test_strike_range_takes_precedence_if_both_somehow_given(asked):
    """Defensive: if a caller passes both, the vendor-proven shape (range only) wins.

    No current call site passes both. Never an untested combined request.
    """
    q = asked("SPY", strike_count=20, strike_range="ALL")
    assert q["range"] == "ALL"
    assert "strikeCount" not in q
