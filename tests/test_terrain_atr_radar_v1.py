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
    # each bar carries its served change (live_price_rows.with_change: the bar change is served,
    # the page computes nothing)
    assert set(row) == {"t", "o", "h", "l", "c", "v", "chg", "chg_pct"}
    assert (row["t"], row["c"]) == (rows[-1][0], rows[-1][4])
    ts = [b["t"] for b in body["bars"]]
    assert ts == sorted(ts), "bars must be newest-last (ascending time)"
    # the chart's candles are Schwab's completed bars exactly as stored, never altered
    full = json.loads(srv.get_bars1m(ticker="SPY", limit=len(rows), tf="1").body)["bars"]
    assert [(b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]) for b in full] == rows


def test_terrain_strikes_endpoint_shape_and_scopes():
    """CR-03 histogram feed: per-strike [strike, net_gex, volume] rows in three
    expiry scopes for today + prior capture, sorted by strike, read-only."""
    import server as srv
    from fastapi.testclient import TestClient

    client = TestClient(srv.app)
    r = client.get("/api/terrain/strikes?ticker=SPY")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "SPY"
    for side in ("today", "prior"):
        assert set(body[side]) == {"all", "near", "far"}
    rows = body["today"]["all"]
    if rows:
        assert all(len(x) == 3 for x in rows)
        ks = [x[0] for x in rows]
        assert ks == sorted(ks), "strikes must be ascending"
        # near+far partition the chain: no scope may exceed ALL
        assert len(body["today"]["near"]) <= len(rows)
        assert len(body["today"]["far"]) <= len(rows)
