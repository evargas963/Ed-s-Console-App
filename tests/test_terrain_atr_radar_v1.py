"""ATR rings and radar contact selection.

WHY ATR: percent means different things across instruments — 0.5% is a normal hour on SPY
and noise on TSLA. ATR normalises distance into "can price actually get there", which is
the only question the radar answers.

The ring thresholds are derived from meaning, not invented: within a tenth of a day's range
a level is effectively being touched; beyond three quarters of a day's range it cannot
matter today. Regime-change contacts outrank walls because crossing the flip changes what
every other level means.
"""

from __future__ import annotations

















def test_bars1m_endpoint_serves_canonical_bars_shape(monkeypatch):
    """CR-03 pre-work: /api/bars1m returns newest-last {t,o,h,l,c,v} rows from
    price_bars_1m (read-only; index-served: ticker named in the WHERE).

    TEST_SYSTEM_REHAB_V2_RESIDUAL_CLOSURE (TestClient adjudication): REWRITE.
    get_bars1m is a plain sync handler taking only Query params and returning a
    JSONResponse it builds itself -- no auth, middleware, Request, or response_model
    reshaping. This file's own test_spot_endpoint_caches_upstream_within_ttl already
    calls its handler directly, so this is the established pattern here."""
    import json
    from pathlib import Path

    import server as srv

    # Real SPY price_bars_1m rows (tests/fixtures) as the table read returns them. The test read
    # whatever bars the shared database held, and skipped its assertions when there were none.
    fx = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_spy_1m_bars_2026_09_24_25.json")
                    .read_text(encoding="utf-8"))["bars"]
    rows = [(b["timestamp"] / 1000.0, b["open"], b["high"], b["low"], b["close"], b["volume"]) for b in fx]
    monkeypatch.setattr(srv, "_read_bars_1m", lambda tk, limit: rows[-int(limit):] if tk == "SPY" else [])
    body = json.loads(srv.get_bars1m(ticker="SPY", limit=5, tf="1").body)
    assert body["ticker"] == "SPY" and len(body["bars"]) == 5
    row = body["bars"][-1]
    # each bar carries its served change, its label and its volume's text (live_price_rows.
    # served_bar: the page computes and formats nothing; the volume text since 2026-10-01)
    assert set(row) == {"t", "o", "h", "l", "c", "v", "v_text", "chg", "chg_pct", "label"}
    assert (row["t"], row["c"]) == (rows[-1][0], rows[-1][4])
    ts = [b["t"] for b in body["bars"]]
    assert ts == sorted(ts), "bars must be newest-last (ascending time)"
    # the chart's candles are Schwab's completed bars exactly as stored, never altered
    full = json.loads(srv.get_bars1m(ticker="SPY", limit=len(rows), tf="1").body)["bars"]
    assert [(b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]) for b in full] == rows


def test_terrain_strikes_endpoint_shape_and_scopes(monkeypatch, pin_clock):
    """CR-03 histogram feed: per-strike [strike, net_gex, volume] rows in three
    expiry scopes for today + prior capture, sorted by strike, read-only. The real SPY 0DTE chain
    is published first (the test used to read an empty cache and skip every row assertion).
    Stand-in (named): the live price, the chain's own underlying price."""
    import json
    import time
    from pathlib import Path

    import server as srv
    from fastapi.testclient import TestClient

    fx = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_spy_0dte_chain.json")
                    .read_text(encoding="utf-8"))
    pin_clock(2026, 9, 22, 12, 46)                                   # the chain's capture
    monkeypatch.setattr(srv, "_terrain_cache", {})
    monkeypatch.setattr(srv, "last_capture_per_day", lambda *a, **k: [])
    monkeypatch.setattr(srv, "resolve_spot", lambda t, **k: (float(fx["spot"]), srv.SPOT_SOURCE_PLANE, time.time()))
    srv._publish_levels("SPY", [dict(c) for c in fx["chain"]], time.time(), now=time.time())
    client = TestClient(srv.app)
    r = client.get("/api/terrain/strikes?ticker=SPY")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "SPY"
    # today's and the prior day's rows have one shape: the scopes, the count of contracts whose
    # settlement cannot be determined (in no row) and, with no rows, why -- the reason the
    # per-strike gamma panel prints (the fourth review restored it: the page had its own words).
    # No prior capture here: the prior rows are absent with their reason and no count
    shape = {"all", "near", "far", "expiry_unknown", "absent_reason"}
    assert set(body["today"]) == shape and body["today"]["expiry_unknown"] == 0 and body["today"]["absent_reason"] is None
    assert set(body["prior"]) == shape and body["prior"]["expiry_unknown"] is None
    assert body["prior"]["absent_reason"] == "no chain capture from the market day before the chain's"
    rows = body["today"]["all"]
    assert rows and all(len(x) == 3 for x in rows)
    ks = [x[0] for x in rows]
    assert ks == sorted(ks), "strikes must be ascending"
    # near+far partition the chain: no scope may exceed ALL
    assert len(body["today"]["near"]) <= len(rows)
    assert len(body["today"]["far"]) <= len(rows)
