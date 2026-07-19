"""RC-14 / RC-15 — ONE spot authority, and the key contract that broke it.

`server.resolve_spot()` is the single source for underlying spot. Two failures are locked
here because both actually happened:

  RC-14  four independent spot sources existed and consumers picked different ones, so the
         terrain card and the console header showed different prices at the same instant.

  RC-15  the fix READ THE WRONG KEY. `_parse_quote_node_session_fields` returns "spot";
         the new code asked for "spot_f" (the local variable name inside that function).
         It returned None on every call, so the authority silently fell through to a stale
         stored snapshot -- and the card still disagreed with the header while the log said
         nothing. A silent fallthrough is worse than a crash.
"""

from __future__ import annotations

import server


def test_quote_parser_key_contract() -> None:
    """The parser's spot key is "spot". Reading any other name is a silent None.

    This is the exact defect of RC-15: a wrong key name is not a type error, not a crash,
    and not a test failure anywhere else -- it just degrades the authority to its stale
    fallback. Lock the contract.
    """
    node = {
        "quote": {"lastPrice": 742.49, "mark": 742.45, "bidPrice": 742.41,
                  "askPrice": 742.50, "tradeTime": 1_784_491_628_000},
    }
    parsed = server._parse_quote_node_session_fields(node)

    assert "spot" in parsed, "the parser's spot key is 'spot'"
    assert "spot_f" not in parsed, "'spot_f' is an internal local, never a returned key"
    assert parsed["spot"] == 742.49
    assert parsed["spot_source"] == "lastPrice"


def test_quote_parser_falls_back_last_then_mark() -> None:
    """Precedence inside the parser: lastPrice, then mark. Both are Schwab leaves."""
    only_mark = server._parse_quote_node_session_fields({"quote": {"mark": 100.25}})
    assert only_mark["spot"] == 100.25
    assert only_mark["spot_source"] == "mark"

    neither = server._parse_quote_node_session_fields({"quote": {}})
    assert neither["spot"] is None
    assert neither["spot_source"] is None


def test_resolve_spot_reports_its_source() -> None:
    """Every spot carries provenance, so a divergence can never hide again."""
    spot, source, _ts = server.resolve_spot("SPY")
    assert source in (
        server.SPOT_SOURCE_QUOTE,
        server.SPOT_SOURCE_CHAIN,
        server.SPOT_SOURCE_SNAPSHOT,
        "none",
    )
    if spot is not None:
        assert spot > 0
        assert source != "none"


def test_resolve_spot_fails_closed_on_empty_ticker() -> None:
    assert server.resolve_spot("") == (None, "none", None)
    assert server.resolve_spot("   ") == (None, "none", None)


def test_chain_leg_is_used_when_supplied() -> None:
    """The chain underlying is a legitimate SECOND-precedence leaf, never the first."""
    chain = {"underlying": {"last": 555.55}}
    assert server.chain_underlying_spot(chain) == 555.55
    assert server.chain_underlying_spot({"underlying": {}}) is None
    assert server.chain_underlying_spot(None) is None


class _FakeResp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_spot_from_quote_actually_returns_the_quote_price(monkeypatch) -> None:
    """THE RC-15 REGRESSION TEST.

    An earlier version of this file only asserted the parser's key contract, which still
    passed when `_spot_from_quote` read the wrong key -- a test that cannot fail is not a
    test. This drives the real function with a stubbed transport and asserts the value
    comes back, which is what actually broke.
    """
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(
        server, "safe_get_quote",
        lambda _client, tk: _FakeResp({tk: {"quote": {"lastPrice": 742.49,
                                                      "tradeTime": 1_784_491_628_000}}}),
    )
    spot, trade_time = server._spot_from_quote("SPY")
    assert spot == 742.49, "the quote leg must return the quote price, not None"
    assert trade_time is not None


def test_resolve_spot_prefers_the_quote_over_the_stored_snapshot(monkeypatch) -> None:
    """Precedence must be observable: a live quote always beats a stale snapshot."""
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(
        server, "safe_get_quote",
        lambda _client, tk: _FakeResp({tk: {"quote": {"lastPrice": 999.99}}}),
    )
    monkeypatch.setattr(server, "_spot_from_stored", lambda _tk: (111.11, 0.0))
    spot, source, _ts = server.resolve_spot("SPY")
    assert spot == 999.99
    assert source == server.SPOT_SOURCE_QUOTE


def test_resolve_spot_falls_through_when_the_quote_is_unusable(monkeypatch) -> None:
    """A dead quote leg must degrade to a LOWER-precedence source, still labelled."""
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "safe_get_quote",
                        lambda _client, tk: _FakeResp({tk: {"quote": {}}}))
    monkeypatch.setattr(server, "_spot_from_stored", lambda _tk: (111.11, 0.0))
    spot, source, _ts = server.resolve_spot("SPY")
    assert spot == 111.11
    assert source == server.SPOT_SOURCE_SNAPSHOT


def test_chain_underlying_is_never_preferred_over_a_stored_trade(monkeypatch) -> None:
    """RC-16: `chain.underlying.last` is a session CLOSE, not a last trade.

    Verified on the wire after hours 2026-07-19: quote.closePrice, quote.mark,
    regularMarketLastPrice, chains.underlying.last and chains.underlyingPrice ALL read
    743.29 (Friday's regular close) while quote.lastPrice read 742.4861 (the true last
    trade). Ranking the chain above a stored snapshot would serve the previous session's
    close as spot -- exactly the 743.29-vs-742.49 divergence the operator reported.
    """
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "safe_get_quote",
                        lambda _c, tk: _FakeResp({tk: {"quote": {}}}))       # no live trade
    monkeypatch.setattr(server, "_spot_from_stored", lambda _tk: (742.4861, 0.0))

    spot, source, _ts = server.resolve_spot("SPY", chain_json={"underlying": {"last": 743.29}})
    assert spot == 742.4861, "a stale real TRADE must beat a session CLOSE"
    assert source == server.SPOT_SOURCE_SNAPSHOT
    assert not server.spot_is_a_close(source)


def test_chain_close_is_used_last_and_flagged_as_a_close(monkeypatch) -> None:
    """When nothing else exists the close may be shown, but never unlabelled."""
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "safe_get_quote",
                        lambda _c, tk: _FakeResp({tk: {"quote": {}}}))
    monkeypatch.setattr(server, "_spot_from_stored", lambda _tk: (None, None))

    spot, source, _ts = server.resolve_spot("SPY", chain_json={"underlying": {"last": 743.29}})
    assert spot == 743.29
    assert source == server.SPOT_SOURCE_CHAIN
    assert server.spot_is_a_close(source), "a close must be flagged so the UI can say so"
