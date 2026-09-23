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
import app.api.routes.terrain
import tier_a_live_state


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


def test_quote_parser_never_promotes_mark_or_close_to_spot() -> None:
    """Current spot is lastPrice only. MARK and regular close stay distinct fields."""
    only_mark = server._parse_quote_node_session_fields({"quote": {"mark": 100.25}})
    assert only_mark["spot"] is None
    assert only_mark["spot_source"] is None
    assert only_mark["mark"] == 100.25

    only_close = server._parse_quote_node_session_fields(
        {"regular": {"regularMarketLastPrice": 99.0}}
    )
    assert only_close["spot"] is None
    assert only_close["regular_close"] == 99.0

    neither = server._parse_quote_node_session_fields({"quote": {}})
    assert neither["spot"] is None
    assert neither["spot_source"] is None


def test_resolve_spot_reports_its_source() -> None:
    """Every spot carries provenance, so a divergence can never hide again."""
    spot, source, _ts = server.resolve_spot("SPY")
    assert source in (
        server.SPOT_SOURCE_QUOTE,
        server.SPOT_SOURCE_PLANE,
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


def test_resolve_spot_prefers_a_fresh_streaming_plane_row_over_the_rest_quote(monkeypatch) -> None:
    """Operator-reproduced defect (2026-09-14, "360 audit... spot can be a different number
    on the gamma chart"): resolve_spot's own docstring has said "THE single spot authority"
    since RC-14, but it never consulted live_market_plane (Layer A) -- a SEPARATE,
    independently-governed live quote store fed primarily by the Schwab streaming websocket
    that the header/analytics stack (Tier A/B/C) reads directly. Two disciplined producers
    that never checked each other is RC-14's shape one layer up. The plane is now this
    function's own highest-precedence source when fresh."""
    import time as _t

    import live_market_plane as L

    tk = "ZZPLANESPOT"
    L._by_ticker[tk] = {"spot": 700.42, "server_received_ts": _t.time(),
                         "exchange_quote_ts": 1_800_000_000.0,
                         "quote_source_detail": {"spot": "LAST_PRICE"}}
    try:
        monkeypatch.setattr(server, "get_client", lambda: object())
        monkeypatch.setattr(
            server, "safe_get_quote",
            lambda _client, _tk, **_kw: _FakeResp({tk: {"quote": {"lastPrice": 111.11}}}),
        )
        spot, source, _ts = server.resolve_spot(tk)
        assert spot == 700.42, "a fresh plane row must beat a REST quote, not the other way around"
        assert source == server.SPOT_SOURCE_PLANE
    finally:
        L._by_ticker.pop(tk, None)


def test_resolve_spot_falls_through_when_the_plane_row_is_stale(monkeypatch) -> None:
    """A plane row this old is no longer meaningfully "streaming" -- serving a stopped
    stream as live would just move the divergence to the opposite direction (header frozen
    on an old tick, terrain correctly moving on). Falling through to the REST leg is more
    honest and keeps every consumer converged on the same, still-live number.

    2026-09-21: was `server._CARD_FRESHNESS_V1_QUOTE_STALE_SEC + 5.0` -- that constant was
    deleted along with the confirmed-dead card_freshness_v1 system; this test only ever
    borrowed its value as a convenient "definitely stale" duration. Replaced with the
    literal it evaluated to."""
    import time as _t

    import live_market_plane as L

    tk = "ZZPLANESTALE"
    L._by_ticker[tk] = {"spot": 700.42,
                         "server_received_ts": _t.time() - 35.0,
                         "exchange_quote_ts": 1_800_000_000.0,
                         "quote_source_detail": {"spot": "LAST_PRICE"}}
    try:
        monkeypatch.setattr(server, "get_client", lambda: object())
        monkeypatch.setattr(
            server, "safe_get_quote",
            lambda _client, _tk, **_kw: _FakeResp({tk: {"quote": {"lastPrice": 111.11}}}),
        )
        spot, source, _ts = server.resolve_spot(tk)
        assert spot == 111.11, "a stale plane row must not be preferred over a live REST quote"
        assert source == server.SPOT_SOURCE_QUOTE
    finally:
        L._by_ticker.pop(tk, None)


def test_resolve_spot_falls_through_when_the_plane_has_no_row(monkeypatch) -> None:
    """No streaming row at all (never subscribed, or a genuinely cold ticker) must fall
    through cleanly -- the new plane leg must never raise or fabricate on absence."""
    import live_market_plane as L

    tk = "ZZPLANENONE"
    L._by_ticker.pop(tk, None)   # ensure a clean slate regardless of prior test ordering
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(
        server, "safe_get_quote",
        lambda _client, _tk, **_kw: _FakeResp({tk: {"quote": {"lastPrice": 222.22}}}),
    )
    spot, source, _ts = server.resolve_spot(tk)
    assert spot == 222.22
    assert source == server.SPOT_SOURCE_QUOTE


def test_header_and_terrain_cannot_diverge_on_a_fresh_plane_row(monkeypatch) -> None:
    """THE regression this whole audit is about, proven directly: given the SAME fresh
    streaming plane row, resolve_spot() (terrain / Gamma Chart's own inputs) and
    _tier_a_live_state_dict() (the console header) must return the IDENTICAL spot -- not
    two independently-computed numbers that usually happen to agree."""
    import time as _t

    import live_market_plane as L

    tk = "ZZCONVERGE"
    L._by_ticker[tk] = {"spot": 812.5, "server_received_ts": _t.time(),
                         "exchange_quote_ts": 1_800_000_000.0, "bid": 812.4, "ask": 812.6,
                         "spot_disp": "812.50", "bid_disp": "812.40", "ask_disp": "812.60",
                         "quote_source_detail": {"spot": "LAST_PRICE"}}
    try:
        # A REST call here would prove nothing (the plane must win first) -- if either
        # consumer fell through to it, this distinct value would surface the divergence.
        monkeypatch.setattr(server, "get_client", lambda: object())
        monkeypatch.setattr(
            server, "safe_get_quote",
            lambda _client, _tk, **_kw: _FakeResp({tk: {"quote": {"lastPrice": 1.0}}}),
        )
        terrain_spot, terrain_source, _ts = server.resolve_spot(tk)
        header_out = tier_a_live_state._tier_a_live_state_dict(tk, None)
        assert terrain_spot == 812.5 and terrain_source == server.SPOT_SOURCE_PLANE
        assert header_out.get("spot") == terrain_spot, (
            f"header spot {header_out.get('spot')} != terrain/resolve_spot spot {terrain_spot} "
            "-- the exact divergence this audit exists to close"
        )
    finally:
        L._by_ticker.pop(tk, None)


def test_resolve_spot_never_promotes_stored_or_chain_when_last_price_is_absent(monkeypatch) -> None:
    """A missing LAST_PRICE is UNAVAILABLE. Stored snapshot and chain close stay unused."""
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "safe_get_quote",
                        lambda _client, tk, **_kw: _FakeResp({tk: {"quote": {"mark": 111.11}}}))
    monkeypatch.setattr(server, "_spot_from_stored", lambda _tk: (111.11, 0.0))
    spot, source, _ts = server.resolve_spot(
        "SPY", chain_json={"underlying": {"last": 743.29, "mark": 743.20, "close": 743.10}}
    )
    assert spot is None
    assert source == "none"


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


def test_reprice_does_not_keep_cached_spot_as_current_when_last_price_is_unavailable(monkeypatch) -> None:
    """A cached terrain spot must not silently become current live spot."""
    monkeypatch.setattr(server, "resolve_spot", lambda _tk, **_kw: (None, "none", None))
    cached = {"ticker": "SPY", "spot": 745.10, "regime": "LONG_GAMMA_CHOP"}
    out = server._reprice_cached_terrain(cached, "SPY")
    assert out["spot"] is None
    assert out["spot_source"] == "none"
    assert out["spot_state"] == "unavailable"
    assert out["regime"] == "LONG_GAMMA_CHOP"


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

    served = app.api.routes.terrain.get_terrain(ticker="SPY")

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


def test_merge_into_state_skips_a_stale_plane_row(monkeypatch) -> None:
    """Operator-reproduced defect (2026-09-14, spot 360 audit, round 2): merge_into_state
    overlaid the plane's spot onto an analytical payload UNCONDITIONALLY, with no age check
    -- _fetch_state's own resolve_spot()-computed spot (its "SINGLE SPOT AUTHORITY" comment)
    was clobbered by a stalled stream's last tick on every single build. A stale row must be
    treated exactly like no row: the caller's own already-correct spot stands."""
    import time as _t

    import live_market_plane as L

    tk = "ZZMERGESTALE"
    L._by_ticker[tk] = {"spot": 999.0, "server_received_ts": _t.time() - (L.PLANE_QUOTE_STALE_SEC + 5.0)}
    try:
        ms = {"spot": 700.42, "ticker": tk}
        L.merge_into_state(ms, tk)
        assert ms["spot"] == 700.42, "a stale plane row must not clobber the caller's own resolved spot"
    finally:
        L._by_ticker.pop(tk, None)


def test_merge_into_state_applies_a_fresh_plane_row(monkeypatch) -> None:
    """The other half of the same contract: a genuinely fresh row SHOULD overlay -- this
    isn't "never trust the plane", it's "never trust it blindly"."""
    import time as _t

    import live_market_plane as L

    tk = "ZZMERGEFRESH"
    L._by_ticker[tk] = {"spot": 850.0, "server_received_ts": _t.time(),
                         "quote_source_detail": {"spot": "LAST_PRICE"}}
    try:
        ms = {"spot": 700.42, "ticker": tk}
        L.merge_into_state(ms, tk)
        assert ms["spot"] == 850.0, "a fresh plane row must overlay onto the analytical payload"
    finally:
        L._by_ticker.pop(tk, None)


def test_apply_l1_live_quote_overlay_skips_a_stale_plane_row() -> None:
    """Same contract as merge_into_state, for the L1/Tier B cache-hit read path."""
    import time as _t

    import live_market_plane as L

    tk = "ZZL1STALE"
    L._by_ticker[tk] = {"spot": 999.0, "server_received_ts": _t.time() - (L.PLANE_QUOTE_STALE_SEC + 5.0)}
    try:
        l1 = {"spot": 700.42}
        L.apply_l1_live_quote_overlay(l1, tk)
        assert l1["spot"] == 700.42, "a stale plane row must not clobber the cached L1 snapshot's own spot"
        assert "l1_live_overlay_applied" not in l1
    finally:
        L._by_ticker.pop(tk, None)


def test_quote_is_fresh_does_not_treat_carried_forward_as_live() -> None:
    """A carried-forward LAST_PRICE may still be shown as STALE. It is not LIVE."""
    import live_market_plane as L

    q = {"spot": 700.0, "server_received_ts": 1.0,
         "quote_source_detail": {"spot": "LAST_PRICE", "carried_forward": True,
                                 "schwab_auth_degraded": True}}
    assert L.quote_is_fresh(q) is False
    assert L.plane_spot_is_last_price(q) is True


def test_project_l1_corrects_a_stale_plane_spot_via_resolve_spot(monkeypatch) -> None:
    """Operator-reproduced defect (2026-09-14, spot 360 audit, round 2): build_l1_context is
    deliberately PURE (no chain/DB/ML/REST) and reads ctx.l0_row.spot verbatim with no
    fallback -- a stalled stream's last tick would sit in every L1 build (GET
    /api/analytics/light and its SSE stream) indefinitely. _project_l1 must correct the spot
    BEFORE the pure build, using the same resolve_spot() authority everything else uses."""
    import time as _t

    import live_market_plane as L
    import server

    tk = "ZZL1PROJECT"
    L._by_ticker[tk] = {"spot": 999.0, "server_received_ts": _t.time() - (L.PLANE_QUOTE_STALE_SEC + 5.0)}
    try:
        monkeypatch.setattr(server, "get_client", lambda: object())
        monkeypatch.setattr(
            server, "safe_get_quote",
            lambda _client, _tk, **_kw: _FakeResp({tk: {"quote": {"lastPrice": 123.45}}}),
        )
        out = server._project_l1(tk, None, reason="test")
        assert out.get("spot") == 123.45, (
            f"expected the resolve_spot-corrected spot 123.45, got {out.get('spot')} -- "
            "the stale plane tick must not reach the L1 payload"
        )
    finally:
        L._by_ticker.pop(tk, None)
        server._l1_snapshot_cache.pop((tk, "__auto__"), None)


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


def test_carried_forward_quote_is_recorded_with_its_degradation(monkeypatch):
    """RC-121 (W3-C4): serving a degraded carry-forward without RECORDING it left every plane
    reader (Tier C merge, SSE, L1) with an undegraded picture under an advanced generation."""
    import server as S
    captured = {}
    class _Lmp:
        def next_fast_generation(self, tk): return 42
        def record_quote(self, tk, row): captured["tk"] = tk; captured["row"] = row
    monkeypatch.setattr(S, "_lmp", _Lmp())
    out = S._stale_fast_quote_carried_forward({"spot": 700.0}, "SPY")
    assert captured, "the carry-forward was served but never recorded to the plane"
    assert captured["tk"] == "SPY"
    assert captured["row"]["quote_source_detail"]["carried_forward"] is True
    assert captured["row"]["quote_source_detail"]["schwab_auth_degraded"] is True
    assert captured["row"]["fast_generation_id"] == out["fast_generation_id"] == 42, (
        "the recorded row and the served row must be the SAME generation"
    )


def test_plane_merges_carry_the_quote_provenance():
    """RC-121 (W3-C4): quote_source_detail must survive BOTH overlay functions — a spot
    without its degradation flags is a number stripped of its trust label."""
    import live_market_plane as L
    qsd = {"carried_forward": True, "schwab_auth_degraded": True}
    L.record_quote("ZZQSD", {"spot": 1.23, "quote_source_detail": qsd})
    md: dict = {}
    L.merge_into_state(md, "ZZQSD")
    assert md.get("quote_source_detail") == qsd, "merge_into_state stripped the provenance"
    l1: dict = {}
    L.apply_l1_live_quote_overlay(l1, "ZZQSD")
    assert l1.get("quote_source_detail") == qsd, "the L1 overlay stripped the provenance"


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


def test_every_vendor_quote_read_goes_through_the_memo():
    """W3-C8 (RC-112 reopened): the first close said 'both paths' while FIVE more direct
    callers existed (_fetch_state, tier A, base capture, bars collector, price levels).
    The class is EVERY vendor quote read; this lock counts the raw call sites — exactly one
    is legal, inside _memoized_quote_response itself."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    # v10 audit lesson: a paren-matching count missed `pool.submit(_safe_get_quote_with_retry,
    # ...)` — the function passed BY REFERENCE. Count NAME references: the def line and the
    # memo's own internal call are the only two legal appearances.
    sites = [ln.strip() for ln in src.splitlines()
             if "_safe_get_quote_with_retry" in ln
             and "def _safe_get_quote_with_retry" not in ln
             and not ln.strip().startswith("#")]
    assert len(sites) == 1, (
        f"{len(sites)} references to the raw vendor fetch — every reader (calls AND "
        f"by-reference handoffs) must go through _memoized_quote_response: {sites}"
    )


def test_every_batch_vendor_quote_read_goes_through_one_call_site():
    """Operator-reproduced defect (2026-09-14, spot 360 audit): this lock's own scope was
    "every VENDOR quote read", but it only ever counted _safe_get_quote_with_retry (the
    single-symbol fetch) -- schwab_client.safe_get_quotes (the BATCH fetch /api/watchlist-
    quotes uses) was a second, completely uncounted raw vendor call, outside both the memo
    AND live_market_plane, that could return a genuinely different tick than every other
    consumer for the exact same ticker at the exact same instant. Same discipline, same
    reasoning, the sibling function this lock's own docstring should have covered from the
    start: exactly one raw call site, and it must record what it fetches into the plane
    (proven behaviourally by test_watchlist_quotes_records_a_fresh_fetch_into_the_plane).

    RC-REHAB-1 (Phase 3, route-extraction, seventeenth slice, predating this decomposition
    session): /api/watchlist-quotes -- and with it, this call site -- moved out of
    server.py into app/api/routes/market_data.py well before this lock was last verified;
    this test was never updated for that move and had been silently checking an empty
    file ever since (0 matches, not 1) until the full suite finally caught it here."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    src = (root / "app" / "api" / "routes" / "market_data.py").read_text(encoding="utf-8")
    sites = [ln.strip() for ln in src.splitlines()
             if "safe_get_quotes" in ln
             and "def safe_get_quotes" not in ln
             and "import safe_get_quotes" not in ln
             and not ln.strip().startswith("#")]
    assert len(sites) == 1, (
        f"{len(sites)} references to the raw batch vendor fetch — exactly one disciplined "
        f"call site (the one that checks the plane first and records its results back into "
        f"it) may call schwab_client.safe_get_quotes: {sites}"
    )
    # Also confirm the OLD location is genuinely clean, not just relocated-and-duplicated.
    server_src = (root / "server.py").read_text(encoding="utf-8")
    server_sites = [ln.strip() for ln in server_src.splitlines()
                    if "safe_get_quotes" in ln
                    and "def safe_get_quotes" not in ln
                    and "import safe_get_quotes" not in ln
                    and not ln.strip().startswith("#")]
    assert server_sites == [], (
        f"server.py must not carry a second, duplicate raw batch vendor fetch: {server_sites}"
    )
