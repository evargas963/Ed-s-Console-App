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


def test_resolve_spot_never_serves_a_rest_quote(monkeypatch) -> None:
    """SPOT is the streamed LAST_PRICE only (operator rule 2026-09-23: no fallbacks). A REST
    quote being available changes nothing: with no fresh streamed row, spot is UNAVAILABLE."""
    import live_market_plane as L
    L._by_ticker.pop("ZZRESTONLY", None)
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(
        server, "safe_get_quote",
        lambda _client, tk, **_kw: _FakeResp({tk: {"quote": {"lastPrice": 999.99}}}),
    )
    assert server.resolve_spot("ZZRESTONLY") == (None, "none", None)

def _streamed_row(tk: str, spot: float, age_sec: float = 0.5) -> dict:
    """A plane row as the Schwab LEVELONE_EQUITIES stream writes it."""
    import time as _t
    return {"ticker": tk, "spot": spot, "server_received_ts": _t.time() - age_sec, "spot_received_ts": _t.time() - age_sec,
            "exchange_quote_ts": _t.time() - age_sec,
            "quote_source_detail": {"spot": "LAST_PRICE"},
            "quote_ingestion": "schwab_streaming_level_one"}


def test_resolve_spot_prefers_a_fresh_streaming_plane_row_over_the_rest_quote(monkeypatch) -> None:
    """Operator-reproduced defect (2026-09-14, "360 audit... spot can be a different number
    on the gamma chart"): resolve_spot's own docstring has said "THE single spot authority"
    since RC-14, but it never consulted live_market_plane (Layer A) -- a SEPARATE,
    independently-governed live quote store fed primarily by the Schwab streaming websocket
    that the header/analytics stack (Tier A/B/C) reads directly. Two disciplined producers
    that never checked each other is RC-14's shape one layer up. The plane is now this
    function's own highest-precedence source when fresh."""
    from tests.feed_live_helper import mark_feed_live
    mark_feed_live('ZZPLANESPOT')   # the daemon holds it on a live feed
    import time as _t

    import live_market_plane as L

    tk = "ZZPLANESPOT"
    L._by_ticker[tk] = {"ticker": tk, "spot": 700.42, "server_received_ts": _t.time(), "spot_received_ts": _t.time(),
                         "exchange_quote_ts": 1_800_000_000.0,
                         "quote_source_detail": {"spot": "LAST_PRICE"},
                         "quote_ingestion": "schwab_streaming_level_one"}
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


def test_resolve_spot_withholds_a_stale_streamed_price(monkeypatch) -> None:
    """A streamed row past its freshness bound is not current spot, and nothing replaces it:
    no REST quote, no stale value. The broken feed must look broken."""
    import live_market_plane as L

    tk = "ZZPLANESTALE"
    L._by_ticker[tk] = _streamed_row(tk, 700.42, server._CARD_FRESHNESS_V1_QUOTE_STALE_SEC + 5.0)
    try:
        monkeypatch.setattr(server, "get_client", lambda: object())
        monkeypatch.setattr(
            server, "safe_get_quote",
            lambda _client, _tk, **_kw: _FakeResp({tk: {"quote": {"lastPrice": 111.11}}}),
        )
        assert server.resolve_spot(tk) == (None, "none", None)
    finally:
        L._by_ticker.pop(tk, None)


def test_resolve_spot_with_no_streamed_row_is_unavailable(monkeypatch) -> None:
    """No streaming row at all (never subscribed, or a cold ticker): UNAVAILABLE, never raises."""
    import live_market_plane as L

    tk = "ZZPLANENONE"
    L._by_ticker.pop(tk, None)
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(
        server, "safe_get_quote",
        lambda _client, _tk, **_kw: _FakeResp({tk: {"quote": {"lastPrice": 222.22}}}),
    )
    assert server.resolve_spot(tk) == (None, "none", None)


def test_header_and_terrain_cannot_diverge_on_a_fresh_plane_row(monkeypatch) -> None:
    """THE regression this whole audit is about, proven directly: given the SAME fresh
    streaming plane row, resolve_spot() (terrain / Gamma Chart's own inputs) and
    _tier_a_live_state_dict() (the console header) must return the IDENTICAL spot -- not
    two independently-computed numbers that usually happen to agree."""
    from tests.feed_live_helper import mark_feed_live
    mark_feed_live('ZZCONVERGE')   # the daemon holds it on a live feed
    import time as _t

    import live_market_plane as L

    tk = "ZZCONVERGE"
    L._by_ticker[tk] = {"ticker": tk, "spot": 812.5, "server_received_ts": _t.time(), "spot_received_ts": _t.time(),
                         "exchange_quote_ts": 1_800_000_000.0, "bid": 812.4, "ask": 812.6,
                         "spot_disp": "812.50", "bid_disp": "812.40", "ask_disp": "812.60",
                         "quote_source_detail": {"spot": "LAST_PRICE"},
                         "quote_ingestion": "schwab_streaming_level_one"}
    try:
        # A REST call here would prove nothing (the plane must win first) -- if either
        # consumer fell through to it, this distinct value would surface the divergence.
        monkeypatch.setattr(server, "get_client", lambda: object())
        monkeypatch.setattr(
            server, "safe_get_quote",
            lambda _client, _tk, **_kw: _FakeResp({tk: {"quote": {"lastPrice": 1.0}}}),
        )
        terrain_spot, terrain_source, _ts = server.resolve_spot(tk)
        header_out = server._tier_a_live_state_dict(tk, None)
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
    from tests.feed_live_helper import mark_feed_live
    mark_feed_live('SPY')   # the daemon holds it on a live feed
    import live_market_plane as L
    monkeypatch.setitem(L._by_ticker, "SPY", _streamed_row("SPY", 744.93))

    cached = {
        "ticker": "SPY", "spot": 745.10, "spot_source": server.SPOT_SOURCE_PLANE,  # the loop's own stamp, 60s old
        "confidence": "TRUSTED", "regime": "LONG_GAMMA_CHOP", "posture": "FADE_EDGES",
        "gamma_flip": 745.00, "call_wall": 750.0, "put_wall": 740.0,
        "headline": "stale", "lines": ["stale"],
    }
    # profile negative at 744.93 -> dealers short gamma there
    profile = [(700.0, -5.0), (745.00, 0.0), (760.0, 5.0)]
    monkeypatch.setitem(server._terrain_profile_cache, "SPY", profile)

    out = server._reprice_cached_terrain(cached, "SPY")

    assert out["spot"] == 744.93, "spot must be the streamed LAST_PRICE, not the cached one"
    assert out["spot_source"] == server.SPOT_SOURCE_PLANE
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
    from tests.feed_live_helper import mark_feed_live
    mark_feed_live('SPY')   # the daemon holds it on a live feed
    import live_market_plane as L
    monkeypatch.setitem(L._by_ticker, "SPY", _streamed_row("SPY", 744.93))
    monkeypatch.setitem(server._terrain_cache, "SPY", {
        "ticker": "SPY", "spot": 745.10, "spot_source": server.SPOT_SOURCE_PLANE,  # the loop's own stamp, 60s old
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
    assert served["spot_source"] == server.SPOT_SOURCE_PLANE
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
    L._by_ticker[tk] = {"ticker": tk, "spot": 999.0, "server_received_ts": _t.time() - (L.PLANE_QUOTE_STALE_SEC + 5.0), "spot_received_ts": _t.time() - (L.PLANE_QUOTE_STALE_SEC + 5.0)}
    try:
        ms = {"spot": 700.42, "ticker": tk}
        L.merge_into_state(ms, tk)
        assert ms["spot"] == 700.42, "a stale plane row must not clobber the caller's own resolved spot"
    finally:
        L._by_ticker.pop(tk, None)


def test_merge_into_state_applies_a_fresh_plane_row(monkeypatch) -> None:
    """The other half of the same contract: a genuinely fresh row SHOULD overlay -- this
    isn't "never trust the plane", it's "never trust it blindly"."""
    from tests.feed_live_helper import mark_feed_live
    mark_feed_live('ZZMERGEFRESH')   # the daemon holds it on a live feed
    import time as _t

    import live_market_plane as L

    tk = "ZZMERGEFRESH"
    L._by_ticker[tk] = {"ticker": tk, "spot": 850.0, "server_received_ts": _t.time(), "spot_received_ts": _t.time(),
                         "quote_source_detail": {"spot": "LAST_PRICE"},
                         "quote_ingestion": "schwab_streaming_level_one"}
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
    L._by_ticker[tk] = {"ticker": tk, "spot": 999.0, "server_received_ts": _t.time() - (L.PLANE_QUOTE_STALE_SEC + 5.0), "spot_received_ts": _t.time() - (L.PLANE_QUOTE_STALE_SEC + 5.0)}
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

    q = {"spot": 700.0, "server_received_ts": 1.0, "spot_received_ts": 1.0,
         "quote_source_detail": {"spot": "LAST_PRICE", "carried_forward": True,
                                 "schwab_auth_degraded": True}}
    assert L.quote_is_fresh(q) is False
    assert L.plane_spot_is_last_price(q) is True


def test_project_l1_withholds_a_stale_plane_spot(monkeypatch) -> None:
    """A stalled stream's last tick must not reach the L1 payload, and nothing may replace it
    (no REST quote): the L1 spot is withheld until the stream delivers again."""
    import time as _t

    import live_market_plane as L
    import server

    tk = "ZZL1PROJECT"
    L._by_ticker[tk] = {"ticker": tk, "spot": 999.0, "server_received_ts": _t.time() - (L.PLANE_QUOTE_STALE_SEC + 5.0), "spot_received_ts": _t.time() - (L.PLANE_QUOTE_STALE_SEC + 5.0),
                        "quote_ingestion": "schwab_streaming_level_one",
                        "quote_source_detail": {"spot": "LAST_PRICE"}}
    try:
        monkeypatch.setattr(server, "get_client", lambda: object())
        monkeypatch.setattr(
            server, "safe_get_quote",
            lambda _client, _tk, **_kw: _FakeResp({tk: {"quote": {"lastPrice": 123.45}}}),
        )
        out = server._project_l1(tk, None, reason="test")
        assert out.get("spot") is None, (
            f"the stale tick (999.0) or a REST quote (123.45) reached L1: {out.get('spot')}")
    finally:
        L._by_ticker.pop(tk, None)
        server._l1_snapshot_cache.pop((tk, "__auto__"), None)


# ── RC-112 / AUDIT-QUOTE-MEMO-V1: one vendor read serves display AND math ───────────────────

class _StubQuoteResp:
    status_code = 200
    def json(self):
        return {"SPY": {"quote": {"lastPrice": 700.25, "tradeTime": 1785250000000},
                        "fundamental": {"avg10DaysVolume": 12345.0}}}


def test_quote_memo_one_vendor_call_serves_both_paths(monkeypatch):
    """The OPEN_ITEMS acceptance verbatim: one vendor call serves both paths inside the TTL.

    The second reader used to be `_spot_from_quote` (the REST spot leg); it was deleted with
    the uncalled routes that used it, and spot is the streamed LAST_PRICE only
    (test_schwab_stream_option_budget_v1::test_no_rest_quote_is_ever_consulted_for_spot).
    The live second reader of the same memo is `_daily_quote_reference` (the quote's daily
    fundamental block), so the shared-memo guarantee is proven through it."""
    import server as S
    assert not hasattr(S, "_spot_from_quote"), "the REST spot leg is back"
    calls = {"n": 0}
    def fake(client, tk, attempt_hook=None):
        calls["n"] += 1
        return _StubQuoteResp()
    monkeypatch.setattr(S, "_safe_get_quote_with_retry", fake)
    monkeypatch.setattr(S, "get_client", lambda force_refresh=False: object())
    with S._quote_memo_lock:
        S._quote_memo.clear()
    with S._quote_reference_lock:
        monkeypatch.delitem(S._quote_reference_by_ticker, "SPY", raising=False)
    S._memoized_quote_response("SPY")                   # a direct memo reader
    ref = S._daily_quote_reference("SPY", object())     # the daily-reference reader
    assert calls["n"] == 1, "two vendor calls inside the TTL — the memo is not shared"
    assert ref.get("fundamental") == {"avg10DaysVolume": 12345.0}, (
        "the shared read must still parse for the second reader")
    # Expiry: age the entry past the TTL and the vendor must be consulted again.
    with S._quote_memo_lock:
        k, (t, r) = next(iter(S._quote_memo.items()))
        S._quote_memo[k] = (t - S.QUOTE_MEMO_TTL_SEC - 0.01, r)
    S._memoized_quote_response("SPY")
    assert calls["n"] == 2, "an expired memo entry was served as fresh"


def test_plane_merges_carry_the_quote_provenance():
    """RC-121 (W3-C4): quote_source_detail must survive BOTH overlay functions — a spot
    without its degradation flags is a number stripped of its trust label."""
    import live_market_plane as L
    qsd = {"carried_forward": True, "schwab_auth_degraded": True}
    with L._lock:   # a plane row carrying provenance flags (the stream is the only writer)
        L._by_ticker["ZZQSD"] = {"spot": 1.23, "quote_source_detail": qsd}
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


def test_no_batch_vendor_quote_read_feeds_any_live_value():
    """Operator rule 2026-09-23 (no fallbacks): the watchlist used to fetch Schwab REST batch
    quotes (schwab_client.safe_get_quotes) for every symbol the stream was not answering and
    record them into the plane -- a second spot source. Live values come from the stream
    only, so nothing in server.py may call the batch vendor quote read."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    sites = [ln.strip() for ln in src.splitlines()
             if "safe_get_quotes" in ln and not ln.strip().startswith("#")]
    assert sites == [], f"batch vendor quote read reintroduced: {sites}"


