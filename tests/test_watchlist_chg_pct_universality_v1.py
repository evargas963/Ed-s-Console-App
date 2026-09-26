"""Universal per-ticker percent-change: one REST parser (quote.netPercentChange, for
symbols the stream does not carry) and one streamed reader
(live_market_plane.streamed_chg_pct, NET_CHANGE_PERCENT from a fresh streamed row)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))





























def test_streamed_chg_pct_serves_only_a_fresh_streamed_row(monkeypatch):
    import time as _t

    from live_market_plane import streamed_chg_pct

    from tests.feed_live_helper import mark_feed_live
    mark_feed_live("ZZTEST")
    fresh = {"ticker": "ZZTEST", "spot": 10.0, "chg_pct": 3.33, "server_received_ts": _t.time(), "spot_received_ts": _t.time(),
             "quote_source_detail": {"spot": "LAST_PRICE"},
             "quote_ingestion": "schwab_streaming_level_one"}
    assert streamed_chg_pct(fresh) == 3.33
    assert streamed_chg_pct(dict(fresh, chg_pct=0.0)) == 0.0          # a flat day is a value
    assert streamed_chg_pct(dict(fresh, quote_ingestion="rest_tier_a")) is None
    assert streamed_chg_pct(dict(fresh, ticker="ZZNOTHELD")) is None   # the daemon does not hold it
    assert streamed_chg_pct(None) is None


def _streamed_plane_row(spot, chg_pct, ticker="ZZZTEST"):
    import time as _t
    now = _t.time()
    return {"ticker": ticker, "spot": spot, "spot_disp": f"{spot:.2f}", "chg_pct": chg_pct,
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
    from tests.feed_live_helper import feed_live_during
    feed_live_during(monkeypatch, 'ZZZTEST')   # the daemon holds it on a live feed
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




def test_watchlist_quotes_withholds_a_symbol_the_stream_is_not_answering(monkeypatch):
    """One symbol streamed, one not (or its last trade too old): the streamed one is
    served, the other is simply absent (its row reads UNAVAILABLE) -- nothing is fetched
    or written into the plane on its behalf."""
    from tests.feed_live_helper import feed_live_during
    feed_live_during(monkeypatch, 'ZZWLLIVE')   # the daemon holds it on a live feed

    import live_market_plane as L
    import server as srv
    from starlette.testclient import TestClient

    monkeypatch.setitem(L._by_ticker, "ZZWLLIVE", _streamed_plane_row(61.5, -0.2, "ZZWLLIVE"))
    old = _streamed_plane_row(70.0, 0.1, "ZZWLOLD")     # streamed, but the daemon does not hold it
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
        monkeypatch.setitem(L._by_ticker, t, _streamed_plane_row(10.0, 0.0, t))
    from tests.feed_live_helper import feed_live_during
    with TestClient(srv.app) as client:
        feed_live_during(monkeypatch, *many)
        r = client.get("/api/watchlist-quotes", params={"tickers": ",".join(many)})
    assert r.status_code == 200
    assert len(r.json()["quotes"]) == 600  # nothing silently dropped


