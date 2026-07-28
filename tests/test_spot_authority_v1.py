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

import pytest

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


@pytest.fixture(autouse=True)
def _cold_quote_memo():
    """RC-112: the vendor memo is process state; every test starts cold so a stub cached by
    one test can never satisfy (or poison) the next within the 1s TTL."""
    with server._quote_memo_lock:
        server._quote_memo.clear()
    yield
    with server._quote_memo_lock:
        server._quote_memo.clear()


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
        lambda _client, tk, **_kw: _FakeResp({tk: {"quote": {"lastPrice": 742.49,
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
        lambda _client, tk, **_kw: _FakeResp({tk: {"quote": {"lastPrice": 999.99}}}),
    )
    monkeypatch.setattr(server, "_spot_from_stored", lambda _tk: (111.11, 0.0))
    spot, source, _ts = server.resolve_spot("SPY")
    assert spot == 999.99
    assert source == server.SPOT_SOURCE_QUOTE


def test_resolve_spot_falls_through_when_the_quote_is_unusable(monkeypatch) -> None:
    """A dead quote leg must degrade to a LOWER-precedence source, still labelled."""
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "safe_get_quote",
                        lambda _client, tk, **_kw: _FakeResp({tk: {"quote": {}}}))
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
                        lambda _c, tk, **_kw: _FakeResp({tk: {"quote": {}}}))       # no live trade
    monkeypatch.setattr(server, "_spot_from_stored", lambda _tk: (742.4861, 0.0))

    spot, source, _ts = server.resolve_spot("SPY", chain_json={"underlying": {"last": 743.29}})
    assert spot == 742.4861, "a stale real TRADE must beat a session CLOSE"
    assert source == server.SPOT_SOURCE_SNAPSHOT
    assert not server.spot_is_a_close(source)


def test_chain_close_is_used_last_and_flagged_as_a_close(monkeypatch) -> None:
    """When nothing else exists the close may be shown, but never unlabelled."""
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "safe_get_quote",
                        lambda _c, tk, **_kw: _FakeResp({tk: {"quote": {}}}))
    monkeypatch.setattr(server, "_spot_from_stored", lambda _tk: (None, None))

    spot, source, _ts = server.resolve_spot("SPY", chain_json={"underlying": {"last": 743.29}})
    assert spot == 743.29
    assert source == server.SPOT_SOURCE_CHAIN
    assert server.spot_is_a_close(source), "a close must be flagged so the UI can say so"


def test_cached_terrain_is_repriced_against_a_live_spot(monkeypatch) -> None:
    """RC-28: cached LEVELS, live SPOT — the card must never lag the header.

    The terrain loop caches a payload every 60 s and the UI polls it, so spot was frozen
    into that payload and the card ran up to 75 s behind the sub-second header (observed
    745.10 on the card against 744.88 live). Levels are slow-moving and stay cached; spot
    is re-resolved per request and the regime is recomputed as the sign of the cached
    gamma profile AT that fresh spot, so the regime can never disagree with the price
    printed beside it.
    """
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "safe_get_quote",
                        lambda _c, tk, **_kw: _FakeResp({tk: {"quote": {"lastPrice": 744.93}}}))

    cached = {
        "ticker": "SPY", "spot": 745.10, "spot_source": server.SPOT_SOURCE_SNAPSHOT,
        "confidence": "TRUSTED", "regime": "LONG_GAMMA_CHOP", "posture": "FADE_EDGES",
        "gamma_flip": 745.00, "call_wall": 750.0, "put_wall": 740.0,
        "headline": "stale", "lines": ["stale"],
    }
    # profile negative at 744.93 -> dealers short gamma there
    profile = [(700.0, -5.0), (745.00, 0.0), (760.0, 5.0)]
    monkeypatch.setitem(server._terrain_profile_cache, "SPY", profile)

    out = server._reprice_cached_terrain(cached, "SPY")

    assert out["spot"] == 744.93, "spot must be the live quote, not the cached one"
    assert out["spot_source"] == server.SPOT_SOURCE_QUOTE
    # levels are untouched — they are the slow-moving part
    assert out["call_wall"] == 750.0 and out["put_wall"] == 740.0
    assert out["gamma_flip"] == 745.00
    # regime recomputed BELOW the flip -> short gamma, not the cached long-gamma value
    assert out["regime"] == "SHORT_GAMMA_TREND", "regime must track the live spot"
    assert out["headline"] != "stale"


def test_reprice_keeps_cached_payload_when_spot_is_unavailable(monkeypatch) -> None:
    """No live spot means serve the cache unchanged — never blank the card."""
    monkeypatch.setattr(server, "resolve_spot", lambda _tk, **_kw: (None, "none", None))
    cached = {"ticker": "SPY", "spot": 745.10, "regime": "LONG_GAMMA_CHOP"}
    assert server._reprice_cached_terrain(cached, "SPY") == cached


def test_terrain_ENDPOINT_serves_live_spot_from_a_cached_payload(monkeypatch) -> None:
    """RC-28 regression at the level that actually broke: the ENDPOINT, not the helper.

    The first test written for this called `_reprice_cached_terrain` directly and passed
    even with the endpoint reverted to `return cached` — a test that cannot fail where the
    bug lives. This drives `get_terrain()` with a warm cache, which is the exact path the
    UI polls.
    """
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "safe_get_quote",
                        lambda _c, tk, **_kw: _FakeResp({tk: {"quote": {"lastPrice": 744.93}}}))
    monkeypatch.setitem(server._terrain_cache, "SPY", {
        "ticker": "SPY", "spot": 745.10, "spot_source": server.SPOT_SOURCE_SNAPSHOT,
        "confidence": "TRUSTED", "regime": "LONG_GAMMA_CHOP", "posture": "FADE_EDGES",
        "gamma_flip": 745.00, "call_wall": 750.0, "put_wall": 740.0,
        "headline": "stale", "lines": ["stale"],
    })
    monkeypatch.setitem(server._terrain_profile_cache, "SPY",
                        [(700.0, -5.0), (745.00, 0.0), (760.0, 5.0)])

    served = server.get_terrain(ticker="SPY")

    assert served["spot"] == 744.93, (
        "the endpoint served a frozen cached spot; the card would lag the header"
    )
    assert served["spot_source"] == server.SPOT_SOURCE_QUOTE
    assert served["call_wall"] == 750.0, "levels must still come from the cache"
    assert served["regime"] == "SHORT_GAMMA_TREND", "regime must track the live spot"
    # Bugbot 2026-07-20 (confirmed): flip_diag.gamma_at_spot is RENDERED by the dealer
    # tile, and the reprice used to leave the loop-time value beside the live regime —
    # they could disagree in sign. At 744.93 on this profile gamma is negative.
    served_gamma = (served.get("flip_diag") or {}).get("gamma_at_spot")
    assert served_gamma is not None and served_gamma < 0, (
        f"flip_diag.gamma_at_spot must be recomputed at the live spot, got {served_gamma}"
    )


# ── STORED-SNAPSHOT READS MUST BE INDEX-SERVED ──────────────────────────────
# MEASURED 2026-07-20: omitting `timeframe` from a snapshots query that orders by ts_utc
# made idx_snap_ticker_tf_ts (ticker, timeframe, ts_utc) unusable for ordering, because
# timeframe sits between the two columns the query did use. SQLite fell back to reading
# EVERY row for the ticker (70,556 for SPY, each carrying a ~50 KB inline chain blob) into
# a temp B-tree. `_latest_chain_and_spot` did not complete inside a 300 s timeout; naming
# the timeframe took it to 0.002 s.
#
# Asserting the PLAN, not the wall clock: a timing test would be flaky and would pass on a
# small database. A temp B-tree in the plan is the defect itself.

import sqlite3


def _snapshots_fixture() -> sqlite3.Connection:
    """Minimal table + the real production index, so the plan is the production plan."""
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE snapshots (snapshot_id INTEGER PRIMARY KEY, ticker TEXT, "
        "timeframe TEXT, ts_utc REAL, spot REAL, option_chain_json TEXT)"
    )
    con.execute(
        "CREATE INDEX idx_snap_ticker_tf_ts ON snapshots(ticker, timeframe, ts_utc)"
    )
    return con


def _plan(con: sqlite3.Connection, sql: str, params: tuple) -> str:
    return " | ".join(str(r[3]) for r in con.execute("EXPLAIN QUERY PLAN " + sql, params))


def test_omitting_timeframe_forces_a_temp_btree_sort():
    """Proves the defect is real and that this test can see it."""
    con = _snapshots_fixture()
    try:
        plan = _plan(
            con,
            "SELECT spot FROM snapshots WHERE ticker=? AND spot IS NOT NULL "
            "ORDER BY ts_utc DESC LIMIT 1",
            ("SPY",),
        )
        assert "TEMP B-TREE" in plan.upper(), plan
    finally:
        con.close()


def test_stored_spot_and_chain_reads_name_the_timeframe():
    """The shipped queries must be fully index-served — no sort, no scan."""
    con = _snapshots_fixture()
    try:
        for sql in (
            "SELECT spot, ts_utc FROM snapshots "
            "WHERE ticker=? AND timeframe=? AND spot IS NOT NULL "
            "ORDER BY ts_utc DESC LIMIT 1",
            "SELECT spot, option_chain_json FROM snapshots "
            "WHERE ticker=? AND timeframe=? "
            "AND option_chain_json IS NOT NULL AND spot IS NOT NULL "
            "ORDER BY ts_utc DESC LIMIT 1",
        ):
            plan = _plan(con, sql, ("SPY", "1m"))
            assert "TEMP B-TREE" not in plan.upper(), plan
            assert "idx_snap_ticker_tf_ts" in plan, plan
            assert "timeframe=?" in plan, plan
    finally:
        con.close()


def test_server_queries_actually_carry_the_timeframe_predicate():
    """Guards the real call sites, not just a query string written in this test."""
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "server.py"
    text = src.read_text(encoding="utf-8", errors="replace")
    for marker in ("def _spot_from_stored", "def _latest_chain_and_spot"):
        i = text.index(marker)
        body = text[i : i + 3000]
        # Match the EXECUTED sql, not prose: these functions document the defect in their
        # docstrings, which quotes both the bad query and "ORDER BY ts_utc". An earlier
        # version of this test scanned for the first "ORDER BY ts_utc" and matched the
        # docstring, failing on correct code.
        executed = body[body.index("con.execute") :]
        assert "AND timeframe=?" in executed[: executed.index("ORDER BY ts_utc")], (
            marker + " orders by ts_utc without naming timeframe — that plan degrades to a "
            "full read of every row for the ticker"
        )


# ── RC-112 / AUDIT-QUOTE-MEMO-V1: one vendor read serves display AND math ───────────────────

class _StubQuoteResp:
    status_code = 200
    def json(self):
        return {"SPY": {"quote": {"lastPrice": 700.25, "tradeTime": 1785250000000}}}


def test_quote_memo_one_vendor_call_serves_both_paths(monkeypatch):
    """The OPEN_ITEMS acceptance verbatim: one vendor call serves both paths inside the TTL."""
    import server as S
    calls = {"n": 0}
    def fake(client, tk, attempt_hook=None):
        calls["n"] += 1
        return _StubQuoteResp()
    monkeypatch.setattr(S, "_safe_get_quote_with_retry", fake)
    monkeypatch.setattr(S, "get_client", lambda force_refresh=False: object())
    with S._quote_memo_lock:
        S._quote_memo.clear()
    S._memoized_quote_response("SPY")          # the fast lane's read
    spot, ts = S._spot_from_quote("SPY")       # the math authority's read
    assert calls["n"] == 1, "two vendor calls inside the TTL — the memo is not shared"
    assert spot == 700.25, "the shared read must still parse to the authority's spot"
    # Expiry: age the entry past the TTL and the vendor must be consulted again.
    with S._quote_memo_lock:
        k, (t, r) = next(iter(S._quote_memo.items()))
        S._quote_memo[k] = (t - S.QUOTE_MEMO_TTL_SEC - 0.01, r)
    S._memoized_quote_response("SPY")
    assert calls["n"] == 2, "an expired memo entry was served as fresh"


def test_quote_memo_never_caches_a_failure(monkeypatch):
    """A vendor failure must NOT be memoized — the next caller goes back to the vendor."""
    import server as S
    calls = {"n": 0}
    class _Bad:
        status_code = 502
        def json(self): return {}
    def fake(client, tk, attempt_hook=None):
        calls["n"] += 1
        return _Bad()
    monkeypatch.setattr(S, "_safe_get_quote_with_retry", fake)
    monkeypatch.setattr(S, "get_client", lambda force_refresh=False: object())
    with S._quote_memo_lock:
        S._quote_memo.clear()
    S._memoized_quote_response("SPY")
    S._memoized_quote_response("SPY")
    assert calls["n"] == 2, "a FAILED response was cached — failures must stay fail-loud"
