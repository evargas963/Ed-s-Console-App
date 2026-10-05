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

















def test_bars1m_endpoint_serves_canonical_bars_shape():
    """/api/bars1m returns newest-last {t,o,h,l,c,v} rows with their served change, each minute
    Schwab's newest bar for it exactly as the capture daemon recorded it, for SPY and for TSLA
    (real receipts 2026-09-24/25, loaded as the console loads them at startup)."""
    import json

    import server as srv
    from tests.feed_live_helper import daemon_bars, forget_daemon_bars, record_daemon_bars

    for symbol in ("SPY", "TSLA"):
        receipts = daemon_bars("real_daemon_bars_spy_tsla_2026_09_24_25.json", symbol)
        newest = {}
        for r in sorted(receipts, key=lambda r: r["ts_recv"]):
            newest[r["bar_start_ms"]] = (r["bar_start_ms"] / 1000.0, r["open"], r["high"], r["low"], r["close"],
                                         r["volume"])
        sent = [newest[t] for t in sorted(newest)]
        record_daemon_bars(receipts)
        try:
            srv._load_bars()
            body = json.loads(srv.get_bars1m(ticker=symbol, limit=5, tf="1").body)
            full = json.loads(srv.get_bars1m(ticker=symbol, limit=len(sent), tf="1").body)["bars"]
        finally:
            forget_daemon_bars(receipts)
            srv._bars.pop(symbol, None)
        assert body["ticker"] == symbol and len(body["bars"]) == 5
        # each bar carries its served change (the page computes nothing)
        assert set(body["bars"][-1]) == {"t", "o", "h", "l", "c", "v", "chg", "chg_pct"}
        ts = [b["t"] for b in body["bars"]]
        assert ts == sorted(ts), "bars must be newest-last (ascending time)"
        assert [(b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]) for b in full] == sent, symbol


def test_flip_drift_logger_appends_real_jsonl(tmp_path, monkeypatch):
    """Flip-drift row (register, due 2026-07-31): each terrain compute appends one
    JSONL row; flip=None is absence and appends nothing. Drives the REAL logger."""
    import json as _json

    import server as srv

    # RC-58: the timestamp must be a REAL trading session. The question this log answers is
    # INTRADAY flip drift, and its first week was 784 of 784 rows from one SUNDAY window (spot
    # frozen), which measured a median 0.023% move and would have been read as "the flip is
    # stable intraday". 1784296800.0 = Fri 2026-07-17 10:00 ET, a covered trading day.
    RTH_TS = 1784296800.0
    NON_TRADING_TS = 1784383200.0          # Sat 2026-07-18 10:00 ET

    p = tmp_path / "flip_drift_log.jsonl"
    monkeypatch.setattr(srv, "_FLIP_DRIFT_LOG_PATH", p)
    srv._log_flip_drift("SPY", {"gamma_flip": 745.25, "spot": 746.1,
                                "confidence": "TRUSTED",
                                "computed_ts_utc": RTH_TS})
    srv._log_flip_drift("QQQ", {"gamma_flip": None, "spot": 500.0})
    # Market-closed computes must NOT be logged — they manufacture a false "flip is stable".
    srv._log_flip_drift("IWM", {"gamma_flip": 222.0, "spot": 223.0,
                                "confidence": "TRUSTED",
                                "computed_ts_utc": NON_TRADING_TS})
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1, "None flip and market-closed rows must not be logged"
    row = _json.loads(lines[0])
    assert row["ticker"] == "SPY" and row["flip"] == 745.25
    assert row["spot"] == 746.1 and row["confidence"] == "TRUSTED"
    assert row["ts_utc"] == RTH_TS


def test_pricing_a_chain_wires_flip_drift_logger(monkeypatch, tmp_path):
    """Seam: pricing a chain the daemon delivered (_price_chain) must call the logger AFTER a
    successful cache write; a TypeError inside the logger must not fail the pricing."""
    import server as srv
    # its own cache: the SPY levels it publishes (a non-numeric flip below) must not reach
    # another test's /api/levels (they did, 2026-09-28, under CI's file-to-worker split)
    monkeypatch.setattr(srv, "_terrain_cache", {})
    monkeypatch.setattr(srv, "_terrain_refresh_last_error", {})

    calls: list = []
    real = srv._log_flip_drift

    def _spy(tk, payload):
        calls.append((tk, payload.get("gamma_flip")))
        real(tk, payload)

    # This test proves the logger is WIRED into the refresh seam; the session POLICY is covered
    # separately by test_flip_drift_logger_appends_real_jsonl. _log_flip_drift stamps time.time()
    # when the payload carries no computed_ts_utc, so without pinning the calendar authority this
    # assertion would pass or fail depending on the day the suite happens to run (RC-58).
    import time_et as _te
    monkeypatch.setattr(_te, "is_tradable_session_ts_utc", lambda _ts: True)
    monkeypatch.setattr(srv, "_FLIP_DRIFT_LOG_PATH", tmp_path / "flip.jsonl")
    monkeypatch.setattr(srv, "_log_flip_drift", _spy)
    monkeypatch.setattr(srv, "resolve_spot", lambda _tk, **_kw: (100.0, "test", 1.0))

    from terrain_engine import TerrainSnapshot

    monkeypatch.setattr(srv, "compute_terrain", lambda *_a, **_k: TerrainSnapshot(
        ticker="SPY", spot=100.0, gamma_flip=99.5, confidence="TRUSTED"))
    from terrain_atr import AtrPair
    monkeypatch.setattr(srv, "_atr_pair", lambda _tk: AtrPair(1.0, 0.2))

    rth_ts = 1784296800.0                  # a regular-session instant, the chain's fetch time
    srv._price_chain("SPY", srv.DELIVERED, [], rth_ts)
    assert srv.terrain_cache_get("SPY")["confidence"] == "TRUSTED"
    assert calls == [("SPY", 99.5)], "logger must run on the pricing seam"
    assert (tmp_path / "flip.jsonl").is_file()
    assert "SPY" not in srv._terrain_refresh_last_error

    # Fail-soft: non-numeric flip would raise inside float() — the pricing must stand
    monkeypatch.setattr(srv, "_log_flip_drift", real)

    monkeypatch.setattr(srv, "compute_terrain", lambda *_a, **_k: TerrainSnapshot(
        ticker="SPY", spot=100.0, gamma_flip="not-a-number", confidence="TRUSTED"))
    srv._price_chain("SPY", srv.DELIVERED, [], rth_ts)
    assert "SPY" not in srv._terrain_refresh_last_error, "flip-drift failure must stay fail-soft"


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
