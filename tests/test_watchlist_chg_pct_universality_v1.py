"""Universal per-ticker percent-change: one parser, one precedence authority, and proof
that the /api/live/state route's REST backfill survives the plane overlay that runs
after it -- an independent review found the route computed a replacement chg_pct and
then let live_market_plane.merge_into_state's unconditional-overwrite-on-presence
overlay silently undo it. Negative-controlled below (test_..._survives_merge_into_state
fails against the pre-fix ordering, restored immediately after)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import market_context as mc


def test_extract_pct_change_prefers_net_percent_change():
    assert mc.extract_pct_change({"netPercentChange": 1.23}, {}, 100.0) == 1.23


def test_extract_pct_change_falls_back_to_regular_session_leaf():
    assert mc.extract_pct_change({}, {"regularMarketPercentChange": 0.45}, 100.0) == 0.45


def test_extract_pct_change_derives_from_net_change_when_no_percent_leaf():
    # last=102, netChange=2 -> prior close 100 -> +2.0%
    got = mc.extract_pct_change({"netChange": 2.0}, {}, 102.0)
    assert got is not None and abs(got - 2.0) < 1e-9


def test_extract_pct_change_preserves_a_real_zero():
    """A flat (0.0) percent change must not be treated as absent."""
    assert mc.extract_pct_change({"netPercentChange": 0.0}, {}, 100.0) == 0.0


def test_extract_pct_change_absent_when_nothing_usable():
    assert mc.extract_pct_change({}, {}, None) is None


def test_extract_pct_change_is_the_one_parser_both_files_call():
    """market_context._extract_quote and server._parse_quote_node_session_fields must
    both go through extract_pct_change -- not two independently-maintained copies of the
    same netPercentChange/netChange formula (an independent review found the formula
    duplicated across both files before this test existed)."""
    import inspect
    import server as srv

    assert "extract_pct_change" in inspect.getsource(mc._extract_quote)
    assert "extract_pct_change" in inspect.getsource(srv._parse_quote_node_session_fields)


def test_resolve_chg_pct_prefers_stream_when_present():
    got = mc.resolve_chg_pct("SPY", 9.99, stream_chg_pct_fn=lambda t: 1.5)
    assert got == 1.5


def test_resolve_chg_pct_preserves_a_real_zero_from_stream():
    got = mc.resolve_chg_pct("SPY", 9.99, stream_chg_pct_fn=lambda t: 0.0)
    assert got == 0.0


def test_resolve_chg_pct_falls_back_to_rest_when_stream_absent():
    got = mc.resolve_chg_pct("SPY", 3.21, stream_chg_pct_fn=lambda t: None)
    assert got == 3.21


def test_resolve_chg_pct_is_generic_not_a_preferred_symbol_map():
    """No branch on ticker identity -- an arbitrary, never-listed symbol resolves the
    same way SPY does."""
    got = mc.resolve_chg_pct("ZZZTEST_NOT_A_REAL_SYMBOL", 4.56, stream_chg_pct_fn=lambda t: None)
    assert got == 4.56


def test_live_state_never_backfills_chg_pct_from_rest(monkeypatch):
    """chg_pct is the streamed REGULAR_MARKET_CHANGE_PERCENT only (operator rule 2026-09-23:
    no fallbacks). A fresh streamed row that carries no chg_pct serves chg_pct=None even when
    a REST quote with netPercentChange is available -- the gap stays visible."""
    import time as _t

    import server as srv

    ticker = "ZZZTEST"
    plane_row = {"ticker": ticker, "spot": 55.0, "chg_pct": None,
                 "server_received_ts": _t.time(), "spot_received_ts": _t.time(), "exchange_quote_ts": _t.time(),
                 "quote_source_detail": {"spot": "LAST_PRICE"},
                 "quote_ingestion": "schwab_streaming_level_one"}
    monkeypatch.setattr(srv._lmp, "get_quote", lambda t: dict(plane_row))

    class _FakeResp:
        status_code = 200

        def json(self):
            return {ticker: {"quote": {"netPercentChange": 7.77, "lastPrice": 55.0}}}

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_memoized_quote_response", lambda t, client=None: _FakeResp())
    out = srv._tier_a_live_state_dict(ticker, None)
    assert out["spot"] == 55.0
    assert out.get("chg_pct") is None, "REST netPercentChange must never stand in for the stream"


def test_merge_into_state_chg_pct_overwrites_unconditionally_including_none(monkeypatch):
    """The overlay's chg_pct handling must be an authoritative overwrite (including to
    None when the plane row's newest fetch genuinely has none), not a sparse fill-gaps
    merge -- a sparse merge would let a stale percentage from a PREVIOUS call survive a
    fetch that came back honestly without one."""
    import live_market_plane as lmp

    monkeypatch.setattr(lmp, "get_quote", lambda t: {"chg_pct": None})
    ms_dict = {"chg_pct": 99.9}  # stale value from an earlier merge
    lmp.merge_into_state(ms_dict, "SPY")
    assert ms_dict["chg_pct"] is None


def test_apply_l1_live_quote_overlay_chg_pct_overwrites_unconditionally_including_none(monkeypatch):
    import live_market_plane as lmp

    monkeypatch.setattr(lmp, "get_quote", lambda t: {"chg_pct": None})
    l1_payload = {"chg_pct": 99.9}
    lmp.apply_l1_live_quote_overlay(l1_payload, "SPY")
    assert l1_payload["chg_pct"] is None


def test_safe_get_quote_and_safe_get_quotes_share_one_retry_implementation():
    """An independent review found safe_get_quotes duplicating safe_get_quote's
    token-refresh-and-retry structure verbatim. Both must now route through the same
    _quote_call_with_retry rather than each carrying its own copy."""
    import inspect
    import schwab_client as sc

    assert "_quote_call_with_retry" in inspect.getsource(sc.safe_get_quote)
    assert "_quote_call_with_retry" in inspect.getsource(sc.safe_get_quotes)


def test_safe_get_quotes_retries_once_after_token_refresh(monkeypatch):
    import schwab_client as sc

    calls = {"n": 0}

    class _TokenErr(Exception):
        pass

    class _BadClient:
        def get_quotes(self, tickers):
            calls["n"] += 1
            raise _TokenErr("expired")

    class _GoodClient:
        def get_quotes(self, tickers):
            calls["n"] += 1
            return "ok-response"

    monkeypatch.setattr(sc, "_is_token_error", lambda e: True)
    monkeypatch.setattr(sc, "_block_live_schwab_in_ci_offline", lambda: None)
    resp = sc.safe_get_quotes(_BadClient(), ["SPY", "QQQ"], refresh_client_fn=lambda: _GoodClient())
    assert resp == "ok-response"
    assert calls["n"] == 2  # one failed attempt on the bad client, one retry on the refreshed one


def test_streamed_chg_pct_is_the_one_authority_for_live_state_and_l1(monkeypatch):
    """/api/live/state and both L1 builds read chg_pct through the ONE stream-only
    _streamed_chg_pct -- none of them keeps a REST backfill of its own."""
    import inspect
    import server as srv

    for fn in (srv._tier_a_live_state_dict, srv._project_l1, srv._l1_http_get_projection):
        src = inspect.getsource(fn)
        assert "_streamed_chg_pct" in src, fn.__name__
        assert "_memoized_quote_response" not in src or fn is not srv._tier_a_live_state_dict


def test_streamed_chg_pct_serves_only_a_fresh_streamed_row(monkeypatch):
    import time as _t

    import server as srv

    fresh = {"spot": 10.0, "chg_pct": 3.33, "server_received_ts": _t.time(), "spot_received_ts": _t.time(),
             "quote_source_detail": {"spot": "LAST_PRICE"},
             "quote_ingestion": "schwab_streaming_level_one"}
    assert srv._streamed_chg_pct("ZZZTEST", fresh) == 3.33
    assert srv._streamed_chg_pct("ZZZTEST", dict(fresh, quote_ingestion="rest_tier_a")) is None
    assert srv._streamed_chg_pct("ZZZTEST", dict(fresh, server_received_ts=0.0, spot_received_ts=0.0)) is None
    assert srv._streamed_chg_pct("ZZZTEST", None) is None


def _streamed_plane_row(spot, chg_pct):
    import time as _t
    now = _t.time()
    return {"spot": spot, "spot_disp": f"{spot:.2f}", "chg_pct": chg_pct,
            "exchange_quote_ts": now, "server_received_ts": now, "spot_received_ts": now,
            "quote_source_detail": {"spot": "LAST_PRICE"},
            "quote_ingestion": "schwab_streaming_level_one"}


def test_watchlist_quotes_route_reports_a_dead_stream_distinctly(monkeypatch):
    """With no fresh streamed row for ANY requested symbol the whole live feed is down:
    ok:false + error "stream_unavailable" -- distinct from a per-symbol gap -- and no vendor
    call is made to paper over it (operator rule 2026-09-23: no fallbacks)."""
    import live_market_plane as L
    import server as srv
    from starlette.testclient import TestClient

    tks = ["ZZWLDEAD1", "ZZWLDEAD2"]
    for tk in tks:
        L._by_ticker.pop(tk, None)
    monkeypatch.setattr(srv, "get_client", lambda: (_ for _ in ()).throw(
        AssertionError("the watchlist must not reach for a Schwab client")))
    with TestClient(srv.app) as client:
        r = client.get("/api/watchlist-quotes", params={"tickers": ",".join(tks)})
    assert r.status_code == 200
    assert r.json() == {"ok": False, "error": "stream_unavailable", "quotes": {}}


def test_watchlist_quotes_route_success_shape(monkeypatch):
    import live_market_plane as L
    import server as srv
    from starlette.testclient import TestClient

    monkeypatch.setitem(L._by_ticker, "ZZZTEST", _streamed_plane_row(55.0, 1.11))
    with TestClient(srv.app) as client:
        body = client.get("/api/watchlist-quotes", params={"tickers": "ZZZTEST"}).json()
    assert body["ok"] is True and body["error"] is None
    q = body["quotes"]["ZZZTEST"]
    assert (q["spot"], q["chg_pct"], q["spot_state"], q["spot_source"]) == (
        55.0, 1.11, "live", srv.SPOT_SOURCE_PLANE)


def test_watchlist_quotes_serves_the_streamed_row_with_no_vendor_call(monkeypatch):
    """The watchlist's SPY row and every other screen's SPY spot are the SAME streamed
    LAST_PRICE -- no vendor round trip of its own."""
    import live_market_plane as L
    import server as srv
    from starlette.testclient import TestClient

    tk = "ZZWLPLANE"
    monkeypatch.setitem(L._by_ticker, tk, _streamed_plane_row(812.5, 0.42))
    monkeypatch.setattr("schwab_client.safe_get_quotes", lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("no vendor call")))
    with TestClient(srv.app) as client:
        body = client.get("/api/watchlist-quotes", params={"tickers": tk}).json()
    assert body["ok"] is True
    assert body["quotes"][tk]["spot"] == 812.5
    assert body["quotes"][tk]["chg_pct"] == 0.42


def test_watchlist_quotes_withholds_a_symbol_the_stream_is_not_answering(monkeypatch):
    """One symbol streamed, one not (or its last trade too old): the streamed one is
    served, the other is simply absent (its row reads UNAVAILABLE) -- nothing is fetched
    or written into the plane on its behalf."""
    import time as _t

    import live_market_plane as L
    import server as srv
    from starlette.testclient import TestClient

    monkeypatch.setitem(L._by_ticker, "ZZWLLIVE", _streamed_plane_row(61.5, -0.2))
    old = dict(_streamed_plane_row(70.0, 0.1), spot_received_ts=_t.time() - 120.0)
    monkeypatch.setitem(L._by_ticker, "ZZWLOLD", old)
    L._by_ticker.pop("ZZWLNONE", None)
    with TestClient(srv.app) as client:
        body = client.get("/api/watchlist-quotes",
                          params={"tickers": "ZZWLLIVE,ZZWLOLD,ZZWLNONE"}).json()
    assert body["ok"] is True
    assert set(body["quotes"]) == {"ZZWLLIVE"}
    assert L.get_quote("ZZWLNONE") is None


def test_watchlist_quotes_route_no_invented_count_cap(monkeypatch):
    """A prior version silently truncated the ticker list at an invented 500-symbol cap. A
    large request is answered in full, not cut down."""
    import live_market_plane as L
    import server as srv
    from starlette.testclient import TestClient

    many = ["ZZT{}".format(i) for i in range(600)]
    for t in many:
        monkeypatch.setitem(L._by_ticker, t, _streamed_plane_row(10.0, 0.0))
    with TestClient(srv.app) as client:
        r = client.get("/api/watchlist-quotes", params={"tickers": ",".join(many)})
    assert r.status_code == 200
    assert len(r.json()["quotes"]) == 600  # nothing silently dropped


