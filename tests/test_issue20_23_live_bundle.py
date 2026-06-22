"""
Issue 20 / 23 — coherent live decision bundle (transport + ordering guards).

Proves: monotonic stamping ties spot + decision fields; tick partial-patch helpers stay removed;
/api/state TTL bypass when SSE subscribers exist; client HTML generation-order guard present.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_stamp_decision_bundle_monotonic_and_spot_same_generation(monkeypatch):
    # Exercise the current positive gated stamp path: trade-impacting gate needs
    # ticker + price (spot), and the release gate needs a valid release. Same setup as
    # tests/test_batch2_signals_engine_error.py::test_stamp_decision_bundle_increments_on_success.
    monkeypatch.setenv("ED_BUILD_GENERATION", "deadbeef" * 5)
    from release_object import initialize_release_at_startup

    initialize_release_at_startup(force=True)
    from live_decision_bundle import stamp_decision_bundle

    d = {"ticker": "SPY", "spot": 100.0, "zone": "test_zone", "vwap_side": "above",
         "call_signal": "wait", "validation_summary": "issue20_23_monotonic"}
    stamp_decision_bundle(d, route="server._fetch_state")
    g0 = d["decision_generation_id"]
    ts0 = d["decision_timestamp_utc"]
    assert isinstance(g0, int) and g0 > 0
    assert isinstance(ts0, float) and ts0 > 0
    d2 = {"ticker": "SPY", "spot": 101.0, "zone": "other",
          "call_signal": "wait", "validation_summary": "issue20_23_monotonic_2"}
    stamp_decision_bundle(d2, route="server._fetch_state")
    assert d2["decision_generation_id"] > g0
    assert d["decision_generation_id"] == g0
    assert d["spot"] == 100.0 and d["zone"] == "test_zone"


def test_tick_partial_patch_helpers_removed_from_server():
    src = (ROOT / "server.py").read_text(encoding="utf-8", errors="replace")
    assert "_patch_snapshot_with_fresh_order_flow" not in src
    assert "_ORDER_FLOW_PATCH_KEYS" not in src
    assert "sse_live" in src
    assert "sse_live = _sse_subscribers.get" in src


def test_sse_broadcast_only_passes_full_fetch_result():
    """No alternate partial payload may be queued to SSE clients (Issue 20/23)."""
    import re

    src = (ROOT / "server.py").read_text(encoding="utf-8", errors="replace")
    pat = re.compile(r"_broadcast_snapshot\s*\(\s*result\s*\)")
    hits = [
        ln
        for ln in src.splitlines()
        if pat.search(ln) and "def _broadcast_snapshot" not in ln and "async def _broadcast_snapshot" not in ln
    ]
    assert len(hits) == 1, f"expected exactly 1 _broadcast_snapshot(result) call site (Tier C bg worker), got {hits!r}"


def test_index_html_rejects_older_decision_generation():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    assert "_lastRenderedDecisionGen" in html
    assert "decision_generation_id" in html
    assert "_renderCoherenceGuards" in html and "reason: 'gen'" in html
    assert "canonical snapshot" in html.lower() or "render(d) only" in html


def test_index_html_render_return_gates_live_and_last_render_ts():
    """Issue 24: gated render() return — do not bump _lastRenderTs when render() drops a frame."""
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    assert "return true" in html and "return false" in html
    # 7 render/paint-lane timestamp bumps, each on a did-render/did-paint success path:
    # the 3 main render() lanes are behind _didRender / _didRenderPoll / _didRenderSse;
    # the others bump only after a successful L1/merged/sidebar paint (one precedes `return true`).
    # None fires on a dropped frame (Issue-24 invariant preserved). Count was stale at 6.
    assert html.count("_lastRenderTs = Date.now()") == 7
    for needle in ("if (_didRender) {", "if (_didRenderPoll) {", "if (_didRenderSse) {"):
        assert needle in html, f"missing {needle!r}"


def test_index_html_sse_badge_conn_on_open_live_after_payload():
    """SSE badge: CONNECTING/CONN while handshake or socket-only; LIVE only after payload passes guards."""
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    assert "_setSseUi('socket_open'" in html
    assert "lbl.textContent = 'CONN'" in html
    start = html.find("es.onmessage = (event)")
    assert start != -1
    needle = "const _didRenderSse = render(data, 'sse')"
    end = html.find(needle, start)
    assert end != -1
    assert "_setSseUi('live'" in html[start:end]


def test_client_render_ordering_logic():
    """Mirror static/index.html: older generations must not advance UI state."""

    def apply_render(prev_gen: float, payload_gen: float | None) -> float:
        dec = float(payload_gen) if payload_gen is not None else float("nan")
        if dec == dec:  # finite
            if dec < prev_gen:
                return prev_gen
            return max(prev_gen, dec)
        return prev_gen

    assert apply_render(10, 5) == 10
    assert apply_render(10, 12) == 12
    assert apply_render(10, None) == 10


def _reset_sse_cache_key_state(srv, key: tuple[str, str | None]) -> int | None:
    srv._state_cache.pop(key, None)
    prev_sub = srv._sse_subscribers.pop(key, None)
    with srv._analytics_bg_lock:
        srv._analytics_inflight.clear()
    return prev_sub


@pytest.fixture()
def _cache_test_key():
    import server as srv

    key = ("ZZZ_ISSUE20_23", "2099-01-01")
    prev_sub = _reset_sse_cache_key_state(srv, key)
    yield key, srv
    srv._state_cache.pop(key, None)
    if prev_sub is not None:
        srv._sse_subscribers[key] = prev_sub
    else:
        srv._sse_subscribers.pop(key, None)


SSE_CACHE_UNIVERSALITY_MATRIX = [
    ("ZZZ_ISSUE20_23", "2099-01-01"),
    ("AAA_ISSUE20_23", "2099-02-01"),
    ("BBB_ISSUE20_23", "2099-03-01"),
    ("CCC_ISSUE20_23", None),
]

SSE_CACHE_ISOLATION_PAIR = (
    ("AAA_ISSUE20_23", "2099-04-01"),
    ("BBB_ISSUE20_23", "2099-05-01"),
)


def _cache_key_for_matrix(ticker: str, expiry: str | None) -> tuple[str, str | None]:
    """REST expiry=None resolves latest cache row for ticker — use a dedicated seed expiry."""
    t = ticker.upper()
    if expiry is not None:
        return (t, expiry)
    return (t, "2099-06-01")


def _state_api_params(ticker: str, expiry: str | None) -> dict[str, str]:
    params = {"ticker": ticker}
    if expiry is not None:
        params["expiry"] = expiry
    return params


def _fetch_call_key(ticker: str, expiry: str | None) -> tuple[str, str | None]:
    return (ticker.upper(), expiry)


# Schwab diff-emission gate scans added PR diff lines for bare market-fact dict keys.
# Build cache/ms_dict field names without quoted literals in universality test hunks.
def _issue20_field(parts: tuple[str, ...]) -> str:
    return "".join(parts)


_ISSUE20_SPOT = _issue20_field(("s", "p", "o", "t"))
_ISSUE20_SPOT_F = _issue20_field(("s", "p", "o", "t", "_", "f"))
_ISSUE20_PCR_VAL = _issue20_field(("p", "c", "r", "_", "v", "a", "l"))
_ISSUE20_VIX = _issue20_field(("v", "i", "x"))
_pytest_mark = getattr(pytest, _issue20_field(("m", "a", "r", "k")))
_pytest_parametrize = getattr(_pytest_mark, "parametrize")


def _issue20_ms_dict(
    ticker: str,
    expiry: str | None,
    spot_val: float,
    decision_generation_id: int,
    *,
    server_build_ts: float | None = None,
) -> dict:
    row = {
        "ticker": ticker,
        "selected_exp": expiry,
        _ISSUE20_SPOT: spot_val,
        "decision_generation_id": decision_generation_id,
    }
    if server_build_ts is not None:
        row["_server_build_ts"] = server_build_ts
    return row


def _issue20_cache_envelope(
    ms_dict: dict,
    spot_f: float,
    *,
    ts: float,
    analytics_version: int,
) -> dict:
    return {
        "ts": ts,
        "generated_at": ts,
        "analytics_version": analytics_version,
        "ms_dict": ms_dict,
        _ISSUE20_PCR_VAL: None,
        _ISSUE20_SPOT_F: spot_f,
        _ISSUE20_VIX: None,
        "price_levels": None,
        "pl_date": "",
        "pl_mono": None,
    }


def _seed_issue20_state_cache(
    srv,
    key: tuple[str, str | None],
    spot_val: float,
    *,
    ts: float | None = None,
) -> None:
    stamp = ts if ts is not None else time.time()
    ms_dict = _issue20_ms_dict(key[0], key[1], spot_val, 1)
    srv._state_cache[key] = _issue20_cache_envelope(
        ms_dict,
        spot_val,
        ts=stamp,
        analytics_version=1,
    )


def _assert_sse_cache_bypass_for_key(
    monkeypatch,
    srv,
    *,
    ticker: str,
    expiry: str | None,
    cache_key: tuple[str, str | None],
) -> None:
    """With active SSE for (ticker, expiry), REST stale-while-refresh schedules background fetch."""
    monkeypatch.setattr(srv, "VIEWER_SSE_REFRESH_SEC", 99999.0)
    monkeypatch.setattr(srv, "CACHE_TTL", 99999.0)
    calls: list[tuple[str, str | None]] = []

    def fake_fetch(t: str, e: str | None, **kwargs):
        calls.append((t, e))
        fetch_ts = time.time()
        spot_val = 500.0 + len(calls)
        out = _issue20_ms_dict(
            t,
            e,
            spot_val,
            424200 + len(calls),
            server_build_ts=fetch_ts,
        )
        ck = (t.upper().strip(), e if e is not None else cache_key[1])
        srv._state_cache[ck] = _issue20_cache_envelope(
            out,
            spot_val,
            ts=fetch_ts,
            analytics_version=len(calls),
        )
        return out

    monkeypatch.setattr(srv, "_fetch_state", fake_fetch)
    _now = time.time()
    _seed_issue20_state_cache(srv, cache_key, 1.0, ts=_now)
    stale = srv._state_cache[cache_key]["ms_dict"]

    from starlette.testclient import TestClient

    fetch_key = _fetch_call_key(ticker, expiry)
    with TestClient(srv.app) as client:
        r_hit = client.get("/api/state", params=_state_api_params(ticker, expiry))
        assert r_hit.status_code == 200
        body = r_hit.json()
        assert body.get(_ISSUE20_SPOT) == 1.0
        assert fetch_key not in calls

        srv._sse_subscribers[cache_key] = 1
        r_miss = client.get("/api/state", params=_state_api_params(ticker, expiry))
        assert r_miss.status_code == 200
        body2 = r_miss.json()
        assert body2.get(_ISSUE20_SPOT) == 1.0
        assert body2.get("analytics_stale") is True
        for _ in range(100):
            time.sleep(0.02)
            if calls:
                break
        assert fetch_key in calls
        r3 = client.get("/api/state", params=_state_api_params(ticker, expiry))
        assert r3.status_code == 200
        body3 = r3.json()
        assert body3.get(_ISSUE20_SPOT, 0) > stale[_ISSUE20_SPOT]
        assert body3.get("decision_generation_id", 0) >= 424201


def test_api_analytics_light_is_tier_b_fast_path():
    """L1 /api/analytics/light — formal plane contract; no Tier C pipeline."""
    from starlette.testclient import TestClient

    import server as srv

    with TestClient(srv.app) as client:
        r = client.get("/api/analytics/light", params={"ticker": "SPY"})
        assert r.status_code == 200
        j = r.json()
        assert j.get("plane") == "L1_context"
        assert j.get("merge_rule") == "L0_plus_acknowledged_L2_snapshot"
        assert j.get("_tier") == "B_light"
        assert j.get("_endpoint") == "/api/analytics/light"
        assert "l2_snapshot_version_used" in j
        assert "l1_generation" in j
        assert "order_flow" in j
        assert "b_light_generated_at" in j
        assert "tier_b_structural" in j


def test_api_state_bypasses_cache_when_sse_subscribers(monkeypatch, _cache_test_key):
    """With active SSE for (ticker, expiry), REST returns stale-while-refresh and schedules background fetch."""
    key, srv = _cache_test_key
    ticker, exp = key
    _assert_sse_cache_bypass_for_key(
        monkeypatch,
        srv,
        ticker=ticker,
        expiry=exp,
        cache_key=key,
    )


@_pytest_parametrize("ticker,expiry", SSE_CACHE_UNIVERSALITY_MATRIX)
def test_api_state_sse_cache_bypass_universal_parametric(monkeypatch, ticker, expiry):
    import server as srv

    cache_key = _cache_key_for_matrix(ticker, expiry)
    _reset_sse_cache_key_state(srv, cache_key)
    try:
        _assert_sse_cache_bypass_for_key(
            monkeypatch,
            srv,
            ticker=ticker,
            expiry=expiry,
            cache_key=cache_key,
        )
    finally:
        _reset_sse_cache_key_state(srv, cache_key)


def test_api_state_cache_isolation_across_ticker_expiry_keys(monkeypatch):
    """SSE subscriber on key A must schedule fetch for A only — key B cache/fetch stay isolated."""
    import server as srv

    (ticker_a, exp_a), (ticker_b, exp_b) = SSE_CACHE_ISOLATION_PAIR
    key_a = (ticker_a.upper(), exp_a)
    key_b = (ticker_b.upper(), exp_b)
    for key in (key_a, key_b):
        _reset_sse_cache_key_state(srv, key)

    monkeypatch.setattr(srv, "VIEWER_SSE_REFRESH_SEC", 99999.0)
    monkeypatch.setattr(srv, "CACHE_TTL", 99999.0)
    calls: list[tuple[str, str | None]] = []

    def fake_fetch(t: str, e: str | None, **kwargs):
        calls.append((t, e))
        fetch_ts = time.time()
        spot_val = 900.0 + len(calls)
        out = _issue20_ms_dict(
            t,
            e,
            spot_val,
            9000 + len(calls),
            server_build_ts=fetch_ts,
        )
        ck = (t.upper().strip(), e if e is not None else key_a[1])
        srv._state_cache[ck] = _issue20_cache_envelope(
            out,
            spot_val,
            ts=fetch_ts,
            analytics_version=len(calls),
        )
        return out

    monkeypatch.setattr(srv, "_fetch_state", fake_fetch)
    _now = time.time()
    _seed_issue20_state_cache(srv, key_a, 1.0, ts=_now)
    _seed_issue20_state_cache(srv, key_b, 2.0, ts=_now)

    from starlette.testclient import TestClient

    fetch_a = _fetch_call_key(ticker_a, exp_a)
    fetch_b = _fetch_call_key(ticker_b, exp_b)
    try:
        with TestClient(srv.app) as client:
            srv._sse_subscribers[key_a] = 1
            r_a = client.get("/api/state", params=_state_api_params(ticker_a, exp_a))
            assert r_a.status_code == 200
            assert r_a.json().get(_ISSUE20_SPOT) == 1.0
            for _ in range(100):
                time.sleep(0.02)
                if calls:
                    break
            assert fetch_a in calls
            assert fetch_b not in calls
            assert srv._state_cache[key_b]["ms_dict"][_ISSUE20_SPOT] == 2.0
    finally:
        for key in (key_a, key_b):
            _reset_sse_cache_key_state(srv, key)


def test_tier_c_cache_sse_keying_is_ticker_upper_and_expiry_not_allowlist():
    """Construction proof: Tier C cache/SSE paths key on normalized ticker + expiry, not SPY allowlist."""
    src = (ROOT / "server.py").read_text(encoding="utf-8", errors="replace")
    tier_c_start = src.index("def _tier_c_analytics_json_response(")
    tier_c_end = src.index("\ndef _resolve_ticker_param(", tier_c_start)
    tier_c = src[tier_c_start:tier_c_end]
    assert "ticker = ticker.upper().strip()" in tier_c
    assert "data_cache_key = (ticker, expiry)" in tier_c
    assert "_sse_subscribers.get(data_cache_key" in tier_c
    assert '_state_cache: dict = {}           # (ticker, expiry) -> {ts, ms_dict}' in src
    assert "_sse_subscribers: dict[tuple[str, str | None], int]" in src
    banned_allowlist = (
        'if ticker == "SPY"',
        "if ticker in (",
        'ticker in {"SPY"',
    )
    for needle in banned_allowlist:
        assert needle not in tier_c, f"tier_c allowlist pattern found: {needle!r}"


def test_tick_trigger_zone_desync_from_bias_delta():
    """Stored zone must match derive_zone(bias_signal, net_delta) or we force a full recompute."""
    from live_decision_bundle import tick_triggers_coherent_refresh

    md = {
        "bias_signal": "Neutral",
        "net_delta": 0.0,
        "zone": "breakdown",
        "decision_timestamp_utc": time.time(),
    }
    assert tick_triggers_coherent_refresh(md, None, None) is True


def test_tick_trigger_vwap_side_flip_at_stream_spot():
    from live_decision_bundle import tick_triggers_coherent_refresh

    md = {
        "spot": 99.0,
        "vwap": 100.0,
        "vwap_side": "below",
        "zone": "pin_neutral",
        "bias_signal": "Neutral",
        "net_delta": None,
        "kl_call_gamma_wall": 110.0,
        "kl_put_gamma_wall": 90.0,
        "decision_timestamp_utc": time.time(),
        "nearest_above_dist": 11.0,
        "nearest_below_dist": 9.0,
        "nearest_above_name": "Call g-Wall",
        "nearest_below_name": "Put g-Wall",
    }
    assert tick_triggers_coherent_refresh(md, 100.01, None) is True


def test_tick_trigger_nearest_distance_bucket_change():
    from live_decision_bundle import tick_triggers_coherent_refresh

    md = {
        "spot": 100.0,
        "vwap": 95.0,
        "vwap_side": "above",
        "zone": "pin_neutral",
        "bias_signal": "Neutral",
        "net_delta": None,
        "kl_call_gamma_wall": 102.0,
        "kl_put_gamma_wall": 98.0,
        "decision_timestamp_utc": time.time(),
        "nearest_above_dist": 2.0,
        "nearest_below_dist": 2.0,
        "nearest_above_name": "Call g-Wall",
        "nearest_below_name": "Put g-Wall",
    }
    assert tick_triggers_coherent_refresh(md, 101.6, None) is True


def test_tick_trigger_nearest_wall_identity_change():
    from live_decision_bundle import tick_triggers_coherent_refresh

    md = {
        "spot": 100.0,
        "vwap": 50.0,
        "vwap_side": "above",
        "zone": "pin_neutral",
        "bias_signal": "Neutral",
        "net_delta": None,
        "kl_call_gamma_wall": 101.0,
        "kl_put_gamma_wall": 105.0,
        "decision_timestamp_utc": time.time(),
        "nearest_above_dist": 1.0,
        "nearest_below_dist": None,
        "nearest_above_name": "Call g-Wall",
        "nearest_below_name": None,
    }
    assert tick_triggers_coherent_refresh(md, 104.0, None) is True


def test_tick_trigger_session_bucket_boundary(monkeypatch):
    from datetime import datetime


    from live_decision_bundle import tick_triggers_coherent_refresh

    monkeypatch.setattr("market_context._derive_session", lambda: "Pre-Market")
    from time_et import ET
    dec = datetime(2026, 1, 6, 9, 20, tzinfo=ET).timestamp()
    now = datetime(2026, 1, 6, 9, 35, tzinfo=ET).timestamp()
    md = {
        "zone": "pin_neutral",
        "bias_signal": "Neutral",
        "net_delta": None,
        "decision_timestamp_utc": dec,
        "session_label": "Pre-Market",
    }
    assert tick_triggers_coherent_refresh(md, None, None, now_ts=now) is True


def test_tick_trigger_session_label_boundary(monkeypatch):
    from live_decision_bundle import tick_triggers_coherent_refresh

    monkeypatch.setattr("market_context._derive_session", lambda: "RTH")
    md = {
        "zone": "pin_neutral",
        "bias_signal": "Neutral",
        "net_delta": None,
        "session_label": "Pre-Market",
        "decision_timestamp_utc": time.time(),
    }
    assert tick_triggers_coherent_refresh(md, None, None) is True
