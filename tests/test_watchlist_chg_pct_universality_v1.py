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


def test_live_state_rest_backfill_survives_merge_into_state(monkeypatch):
    """MEASURED (independent review, correcting this repair's own first attempt):
    _tier_a_live_state_dict computed a REST-backfilled chg_pct, then called
    live_market_plane.merge_into_state(out, tkr) -- which unconditionally overwrites
    chg_pct from the CURRENT plane row whenever that row carries the key at all,
    including a stale None. The route never wrote its transient backfill back into the
    plane, so a plane row that (legitimately, per streaming's own field gaps) still
    carries chg_pct=None would silently undo the backfill this same call just computed.

    Negative control: temporarily move the `out["chg_pct"] = chg_pct` re-assertion in
    server.py back before the merge_into_state call (its pre-fix position) and this test
    fails -- confirming it actually exercises the ordering bug, not a coincidence of the
    row's default state.
    """
    import server as srv
    import app.options.order_flow.state as ofs

    ticker = "ZZZTEST"
    # Plane row already has a fresh spot (as if actively streamed) but an explicit,
    # present, stale chg_pct=None -- the exact shape that triggers merge_into_state's
    # unconditional-overwrite path.
    plane_row = {"ticker": ticker, "spot": 55.0, "chg_pct": None, "quote_ingestion": "streaming"}
    monkeypatch.setattr(srv._lmp, "get_quote", lambda t: dict(plane_row))
    monkeypatch.setattr(ofs, "get_stream_chg_pct", lambda t: None)  # streaming has nothing either

    class _FakeResp:
        status_code = 200

        def json(self):
            return {ticker: {"quote": {"netPercentChange": 7.77}}}

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_memoized_quote_response", lambda t, client=None: _FakeResp())

    out = srv._tier_a_live_state_dict(ticker, None)
    assert out["chg_pct"] == 7.77, (
        f"REST backfill (7.77) was overwritten by the plane overlay's stale chg_pct=None "
        f"-- got {out['chg_pct']!r}"
    )


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


def test_chg_pct_backfill_is_the_shared_authority_for_live_state_and_l1(monkeypatch):
    """An independent review found /api/live/state getting a real chg_pct after its own
    fix while the SSE-pushed header stayed blank -- the L1 build path had no backfill at
    all, a second, unfixed copy of the same problem. Both must now call the ONE shared
    _chg_pct_with_rest_backfill, not each decide independently (or one of them not decide
    at all)."""
    import inspect
    import server as srv

    assert "_chg_pct_with_rest_backfill" in inspect.getsource(srv._tier_a_live_state_dict)
    assert "_chg_pct_with_rest_backfill" in inspect.getsource(srv._project_l1)
    assert "_chg_pct_with_rest_backfill" in inspect.getsource(srv._l1_http_get_projection)


def test_chg_pct_with_rest_backfill_resolves_via_rest_when_stream_and_row_are_both_empty(monkeypatch):
    import server as srv
    import app.options.order_flow.state as ofs

    monkeypatch.setattr(ofs, "get_stream_chg_pct", lambda t: None)

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"ZZZTEST": {"quote": {"netPercentChange": 3.33}}}

    monkeypatch.setattr(srv, "_memoized_quote_response", lambda t, client=None: _FakeResp())
    got = srv._chg_pct_with_rest_backfill("ZZZTEST", {"spot": 10.0, "chg_pct": None}, client=object())
    assert got == 3.33


def test_watchlist_quotes_route_reports_auth_failure_distinctly(monkeypatch):
    """The pre-review shape collapsed auth/vendor/transport failure into the SAME bare {}
    a genuinely-empty-coverage success would return -- indistinguishable. ok:false + a
    reason must now be present."""
    import server as srv
    from fastapi import HTTPException
    from starlette.testclient import TestClient

    def _raise_auth_unavailable():
        raise HTTPException(status_code=503, detail="Schwab auth failed: token_invalid")

    monkeypatch.setattr(srv, "get_client", _raise_auth_unavailable)
    with TestClient(srv.app) as client:
        r = client.get("/api/watchlist-quotes", params={"tickers": "SPY,QQQ"})
        assert r.status_code == 200  # the route itself succeeds; failure is IN the payload
        body = r.json()
        assert body["ok"] is False
        assert body["error"]
        assert body["quotes"] == {}


def test_watchlist_quotes_route_success_shape(monkeypatch):
    import server as srv
    from starlette.testclient import TestClient

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"ZZZTEST": {"quote": {"lastPrice": 55.0, "netPercentChange": 1.11}}}

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr("schwab_client.safe_get_quotes", lambda client, tickers: _FakeResp())
    with TestClient(srv.app) as client:
        r = client.get("/api/watchlist-quotes", params={"tickers": "ZZZTEST"})
        body = r.json()
        assert body["ok"] is True
        assert body["error"] is None
        assert body["quotes"]["ZZZTEST"]["spot"] == 55.0
        assert body["quotes"]["ZZZTEST"]["chg_pct"] == 1.11


def test_watchlist_quotes_route_no_invented_count_cap(monkeypatch):
    """A prior version of this route silently truncated the ticker list at an invented
    500-symbol cap with no vendor/transport evidence behind the number (caught in review).
    A large request must be passed through, not silently cut down."""
    import server as srv
    from starlette.testclient import TestClient

    requested = {}

    class _FakeResp:
        status_code = 200

        def json(self):
            return {}

    def _fake_safe_get_quotes(client, tickers):
        requested["tickers"] = list(tickers)
        return _FakeResp()

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr("schwab_client.safe_get_quotes", _fake_safe_get_quotes)
    many = ["T{}".format(i) for i in range(600)]
    with TestClient(srv.app) as client:
        r = client.get("/api/watchlist-quotes", params={"tickers": ",".join(many)})
        assert r.status_code == 200
        assert len(requested["tickers"]) == 600  # nothing silently dropped
