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

from terrain_atr import (
    RING_CLOSING,
    RING_CONTACT,
    RING_REGIME,
    RING_SECTOR,
    AtrPair,
    atr_distance,
    ring_for,
)


def test_rings_are_ordered_and_distinct() -> None:
    assert 0 < RING_CONTACT < RING_CLOSING < RING_SECTOR
    assert 0 < RING_REGIME < RING_CLOSING


def test_ring_classification_uses_atr_not_percent() -> None:
    """The same POINT gap lands in different rings on instruments with different ATR."""
    gap = 1.0
    assert ring_for(gap, 5.99) == "CLOSING"      # SPY-like: 1pt is 0.17 daily ATR
    assert ring_for(gap, 12.33) == "CONTACT"     # QQQ-like: 1pt is 0.08 daily ATR
    assert ring_for(gap, 0.60) is None           # tiny-ATR name: 1pt is 1.7 ATR, off-scope


def test_ring_boundaries() -> None:
    atr = 10.0
    assert ring_for(RING_CONTACT * atr, atr) == "CONTACT"
    assert ring_for(RING_CONTACT * atr + 0.01, atr) == "CLOSING"
    assert ring_for(RING_CLOSING * atr, atr) == "CLOSING"
    assert ring_for(RING_CLOSING * atr + 0.01, atr) == "SECTOR"
    assert ring_for(RING_SECTOR * atr, atr) == "SECTOR"
    assert ring_for(RING_SECTOR * atr + 0.01, atr) is None


def test_direction_does_not_change_the_ring() -> None:
    """Above or below, only the magnitude of the gap decides reachability."""
    assert ring_for(2.0, 10.0) == ring_for(-2.0, 10.0)
    assert atr_distance(2.0, 10.0) == atr_distance(-2.0, 10.0) == 0.2


def test_no_atr_means_no_ring_never_a_guess() -> None:
    """Without a scale, a distance in points is meaningless — the contact must not appear."""
    for bad in (None, 0, 0.0, -1.0):
        assert ring_for(5.0, bad) is None
        assert atr_distance(5.0, bad) is None
    assert ring_for(None, 10.0) is None
    assert atr_distance(None, 10.0) is None


def test_atr_pair_tolerates_missing_legs() -> None:
    p = AtrPair(daily=None, m15=1.5)
    assert p.daily is None and p.m15 == 1.5
    assert ring_for(1.0, p.daily) is None


def test_regime_ring_is_tighter_than_the_wall_contact_ring() -> None:
    """A flip is only a contact when it is genuinely imminent.

    RING_REGIME sits between CONTACT and CLOSING: tight enough that a flip does not
    permanently occupy the top of the scope, loose enough to warn before the crossing.
    """
    assert RING_CONTACT < RING_REGIME < RING_CLOSING


def test_bars1m_endpoint_serves_canonical_bars_shape():
    """CR-03 pre-work: /api/bars1m returns newest-last {t,o,h,l,c,v} rows from
    price_bars_1m (read-only; index-served: ticker named in the WHERE)."""
    import server as srv
    from fastapi.testclient import TestClient

    client = TestClient(srv.app)
    r = client.get("/api/bars1m?ticker=SPY&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "SPY" and isinstance(body["bars"], list)
    if body["bars"]:
        row = body["bars"][-1]
        assert set(row) == {"t", "o", "h", "l", "c", "v"}
        ts = [b["t"] for b in body["bars"]]
        assert ts == sorted(ts), "bars must be newest-last (ascending time)"


def test_chart_page_route_serves_static_chart_html():
    import server as srv
    from fastapi.testclient import TestClient

    client = TestClient(srv.app)
    r = client.get("/chart")
    assert r.status_code == 200
    assert "terrain on price" in r.text
    assert "no-store" in r.headers.get("cache-control", ""), (
        "chart shell must never be browser-cached (stale-JS class, RC on 2026-07-22)")


def test_flip_drift_logger_appends_real_jsonl(tmp_path, monkeypatch):
    """Flip-drift row (register, due 2026-07-31): each terrain compute appends one
    JSONL row; flip=None is absence and appends nothing. Drives the REAL logger."""
    import json as _json

    import server as srv

    p = tmp_path / "flip_drift_log.jsonl"
    monkeypatch.setattr(srv, "_FLIP_DRIFT_LOG_PATH", p)
    srv._log_flip_drift("SPY", {"gamma_flip": 745.25, "spot": 746.1,
                                "confidence": "TRUSTED",
                                "computed_ts_utc": 1700000000.0})
    srv._log_flip_drift("QQQ", {"gamma_flip": None, "spot": 500.0})
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1, "None flip must not produce a row"
    row = _json.loads(lines[0])
    assert row["ticker"] == "SPY" and row["flip"] == 745.25
    assert row["spot"] == 746.1 and row["confidence"] == "TRUSTED"
    assert row["ts_utc"] == 1700000000.0


def test_terrain_refresh_one_wires_flip_drift_logger(monkeypatch, tmp_path):
    """Seam: _terrain_refresh_one must call the logger AFTER a successful cache
    write; a TypeError inside the logger must not turn ok: into error:."""
    from types import SimpleNamespace

    import server as srv

    calls: list = []
    real = srv._log_flip_drift

    def _spy(tk, payload):
        calls.append((tk, payload.get("gamma_flip")))
        real(tk, payload)

    monkeypatch.setattr(srv, "_FLIP_DRIFT_LOG_PATH", tmp_path / "flip.jsonl")
    monkeypatch.setattr(srv, "_log_flip_drift", _spy)
    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_universal_capture_wanted", lambda _tk: (False, None))
    monkeypatch.setattr(srv, "_terrain_strike_count", lambda _tk: 20)

    class _Resp:
        status_code = 200

        def json(self):
            return {}

    monkeypatch.setattr(srv, "_gated_safe_get_chain", lambda *_a, **_k: (_Resp(), 0, 0))
    monkeypatch.setattr(srv, "flatten_chain_contracts", lambda _j: [])
    monkeypatch.setattr(srv, "resolve_spot", lambda _tk, **_kw: (100.0, "test", 1.0))
    monkeypatch.setattr(srv, "_learn_strike_geometry", lambda *_a, **_k: None)

    class _Snap:
        confidence = "TRUSTED"
        profile = object()

        def to_dict(self):
            return {"gamma_flip": 99.5, "spot": 100.0, "confidence": "TRUSTED"}

    monkeypatch.setattr(srv, "compute_terrain", lambda *_a, **_k: _Snap())
    monkeypatch.setattr(srv, "_radar_atr", lambda _tk: SimpleNamespace(daily=1.0, m15=0.2))

    out = srv._terrain_refresh_one("SPY")
    assert out == "ok:TRUSTED"
    assert calls == [("SPY", 99.5)], "logger must run on the terrain refresh seam"
    assert (tmp_path / "flip.jsonl").is_file()

    # Fail-soft: non-numeric flip would raise inside float() — terrain must stay ok:
    monkeypatch.setattr(srv, "_log_flip_drift", real)

    class _BadSnap:
        confidence = "TRUSTED"
        profile = object()

        def to_dict(self):
            return {"gamma_flip": object(), "spot": 100.0, "confidence": "TRUSTED"}

    monkeypatch.setattr(srv, "compute_terrain", lambda *_a, **_k: _BadSnap())
    out2 = srv._terrain_refresh_one("SPY")
    assert out2 == "ok:TRUSTED", "flip-drift failure must stay fail-soft"


def test_radar_fallback_never_blocks_serves_stale_and_single_flights(monkeypatch):
    """Open-stampede class (measured 21.7s inline at the 2026-07-23 open): the
    radar snapshot merge must return the LAST memo immediately while exactly ONE
    background recompute runs; recompute -> None keeps the previous memo."""
    import threading as th
    import time as _t

    import server as srv

    started = th.Event()
    release = th.Event()
    runs = {"n": 0}

    def _slow_recompute():
        runs["n"] += 1
        started.set()
        release.wait(10)
        return [{"ticker": "ZZZ", "spot": 10.0}]

    monkeypatch.setattr(srv, "_radar_fallback_recompute", _slow_recompute)
    monkeypatch.setattr(srv, "_radar_fallback_cache", (0.0, [{"ticker": "OLD", "spot": 1.0}]))
    monkeypatch.setattr(srv, "_radar_fallback_inflight", False)

    out1 = srv._terrain_snapshots_for_radar()
    out2 = srv._terrain_snapshots_for_radar()
    # returned while the recompute is still parked on `release` -> proven non-blocking:
    # an inline path could only return ZZZ (or wait); OLD in hand proves the memo served
    assert any(m.get("ticker") == "OLD" for m in out1)
    assert any(m.get("ticker") == "OLD" for m in out2)
    assert started.wait(30), "background recompute never started"
    assert runs["n"] == 1, "second caller must join the flight, not start another"
    release.set()
    deadline = _t.time() + 30
    while _t.time() < deadline:
        if srv._radar_fallback_cache[1] and \
           srv._radar_fallback_cache[1][0].get("ticker") == "ZZZ":
            break
        _t.sleep(0.02)
    assert srv._radar_fallback_cache[1][0].get("ticker") == "ZZZ", \
        "background result must land in the memo"

    # None keeps the previous memo (DB hiccup must not wipe the scope)
    monkeypatch.setattr(srv, "_radar_fallback_recompute", lambda: None)
    monkeypatch.setattr(srv, "_radar_fallback_inflight", False)
    srv._radar_fallback_refresh_worker()
    assert srv._radar_fallback_cache[1][0].get("ticker") == "ZZZ"

    # Fresh empty memo is a legitimate result — must NOT re-kick the sweep
    kicks = {"n": 0}

    def _count_recompute():
        kicks["n"] += 1
        return []

    monkeypatch.setattr(srv, "_radar_fallback_recompute", _count_recompute)
    monkeypatch.setattr(srv, "_radar_fallback_cache", (_t.time(), []))
    monkeypatch.setattr(srv, "_radar_fallback_inflight", False)
    srv._terrain_snapshots_for_radar()
    assert kicks["n"] == 0, "fresh empty memo must not re-stampede the fallback"


def test_spot_endpoint_caches_upstream_within_ttl(monkeypatch):
    """Budget guard: TTL hit + concurrent misses single-flight to ONE resolve_spot
    (every upstream call is a real Schwab request against the shared budget)."""
    import json as _json
    import threading as th
    import time as _t

    import server as srv

    calls = {"n": 0}
    entered = th.Event()
    release = th.Event()
    lk = th.Lock()

    def _fake(_tk, **_kw):
        with lk:
            calls["n"] += 1
        entered.set()
        release.wait(10)
        return (123.45, "test_quote", 1.0)

    monkeypatch.setattr(srv, "resolve_spot", _fake)
    srv._spot_poll_cache.clear()
    srv._spot_poll_inflight.clear()

    results: list = []
    slock = th.Lock()

    def _call():
        resp = srv.get_spot(ticker="SPY")
        body = _json.loads(resp.body.decode("utf-8"))
        with slock:
            results.append(body.get("spot"))

    threads = [th.Thread(target=_call) for _ in range(4)]
    for t in threads:
        t.start()
    assert entered.wait(30), "leader never entered resolve_spot"
    _t.sleep(0.05)
    release.set()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads)
    assert results == [123.45] * 4
    assert calls["n"] == 1, f"concurrent misses must single-flight, got {calls['n']}"

    resp2 = srv.get_spot(ticker="SPY")
    assert _json.loads(resp2.body.decode("utf-8"))["spot"] == 123.45
    assert calls["n"] == 1, "TTL hit must not resolve again"
    srv._spot_poll_cache.clear()
    srv._spot_poll_inflight.clear()


def test_spot_endpoint_shape_single_authority():
    """Fast-poll spot feed for /chart (2.5s): exact shape, one price authority."""
    import server as srv
    from fastapi.testclient import TestClient

    client = TestClient(srv.app)
    r = client.get("/api/spot?ticker=SPY")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "SPY"
    assert set(body) == {"ticker", "spot", "spot_source", "spot_as_of_ts_utc"}


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
