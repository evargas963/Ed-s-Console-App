"""DFR-007 / OP-010: governed tradeTimeInLong when quoteTimeInLong absent."""

from __future__ import annotations

from v2_decision.a2_option_expression import _quote_staleness_ms


def test_quote_staleness_uses_trade_time_when_quote_time_missing():
    ms = {"decision_time_ms": 1_700_000_010_000}
    chain = {"tradeTimeInLong": 1_700_000_000_000}
    stale_ms, source = _quote_staleness_ms(ms_dict=ms, chain_row=chain)
    assert stale_ms == 10_000
    assert source == "v2_compliant_tradeTimeInLong_governed_fallback"


def test_quote_staleness_prefers_quote_time_over_trade_time():
    ms = {"decision_time_ms": 1_700_000_010_000}
    chain = {
        "quoteTimeInLong": 1_700_000_009_000,
        "tradeTimeInLong": 1_700_000_000_000,
    }
    stale_ms, source = _quote_staleness_ms(ms_dict=ms, chain_row=chain)
    assert stale_ms == 1_000
    assert source == "v2_compliant"
