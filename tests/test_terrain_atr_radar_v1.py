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


def test_terrain_refresh_one_wires_flip_drift_logger(monkeypatch, tmp_path):
    """Seam: _terrain_refresh_one must call the logger AFTER a successful cache
    write; a TypeError inside the logger must not turn ok: into error:."""
    import server as srv
    monkeypatch.setattr(srv, "_is_loggable_session", lambda: True)   # an open-market test
    # its own cache: the SPY levels it publishes (a non-numeric flip below) must not reach
    # another test's /api/levels (they did, 2026-09-28, under CI's file-to-worker split)
    monkeypatch.setattr(srv, "_terrain_cache", {})

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
    monkeypatch.setattr(srv, "get_client", lambda: object())

    class _Resp:
        status_code = 200

        def json(self):
            return {}

    monkeypatch.setattr(srv, "_gated_safe_get_chain", lambda *_a, **_k: (_Resp(), 0, 0))
    monkeypatch.setattr(srv, "flatten_chain_contracts", lambda _j: [])
    monkeypatch.setattr(srv, "resolve_spot", lambda _tk, **_kw: (100.0, "test", 1.0))

    from terrain_engine import TerrainSnapshot

    monkeypatch.setattr(srv, "compute_terrain", lambda *_a, **_k: TerrainSnapshot(
        ticker="SPY", spot=100.0, gamma_flip=99.5, confidence="TRUSTED"))
    from terrain_atr import AtrPair
    monkeypatch.setattr(srv, "_atr_pair", lambda _tk: AtrPair(1.0, 0.2))

    out = srv._terrain_refresh_one("SPY")
    assert out == "ok:TRUSTED"
    assert calls == [("SPY", 99.5)], "logger must run on the terrain refresh seam"
    assert (tmp_path / "flip.jsonl").is_file()

    # Fail-soft: non-numeric flip would raise inside float() — terrain must stay ok:
    monkeypatch.setattr(srv, "_log_flip_drift", real)

    monkeypatch.setattr(srv, "compute_terrain", lambda *_a, **_k: TerrainSnapshot(
        ticker="SPY", spot=100.0, gamma_flip="not-a-number", confidence="TRUSTED"))
    out2 = srv._terrain_refresh_one("SPY")
    assert out2 == "ok:TRUSTED", "flip-drift failure must stay fail-soft"


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
