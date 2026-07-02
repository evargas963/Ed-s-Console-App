"""T5 RTH failure targeted repair — SSE default message + client freshness reconnect."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HTML = ROOT / "static" / "index.html"


def _html() -> str:
    return HTML.read_text(encoding="utf-8", errors="replace")


def _seed_spy_cache(srv, *, gen_id: int = 100) -> tuple:
    ticker, expiry = "SPY", "2099-01-01"
    ck = (ticker, expiry)
    now = time.time()
    srv._state_cache[ck] = {
        "ts": now,
        "generated_at": now,
        "analytics_version": 1,
        "ms_dict": {
            "ticker": ticker,
            "selected_exp": expiry,
            "mhap_rows": [{"horizon": "5c", "call": "WAIT", "confidence": 0.5}],
            "decision_generation_id": gen_id,
            "_server_build_ts": now,
        },
    }
    return ticker, expiry, ck


@pytest.fixture
def srv_module():
    import server as srv

    srv._startup_analytics_executor()
    srv._analytics_bg_shutdown = False
    srv._analytics_inflight.clear()
    srv._analytics_bg_fail_counts.clear()
    srv._analytics_bg_last_error.clear()
    srv._sse_clients.clear()
    srv._sse_subscribers.clear()
    yield srv
    srv._analytics_inflight.clear()
    srv._sse_clients.clear()
    srv._sse_subscribers.clear()


def test_t5_sse_default_message_emitted_for_money_path_snapshot(srv_module):
    srv = srv_module
    ticker, expiry, _ck = _seed_spy_cache(srv)
    q = asyncio.Queue(maxsize=10)
    srv._sse_clients.append(q)

    payload = srv._build_sse_cache_fanout_payload(
        ticker,
        expiry,
        inflight_key=srv._tier_c_inflight_key(ticker, expiry),
        fanout_reason="unit_test",
    )
    assert payload is not None
    enveloped = srv._attach_money_path_snapshot_envelope(payload)

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        srv._broadcast_snapshot(enveloped)
    )
    raw = q.get_nowait()
    assert isinstance(raw, dict)
    assert raw.get("money_path_snapshot_kind") == "tier_c"
    assert isinstance(raw.get("money_path_snapshot"), dict)
    wire = json.dumps(raw)
    assert "money_path_snapshot" in wire
    assert raw.get("ticker") == ticker


def test_t5_sse_broadcast_reachable_from_background_cadence(srv_module, monkeypatch):
    srv = srv_module
    ticker, expiry, ck = _seed_spy_cache(srv)
    with srv._sse_lock:
        srv._sse_subscribers[ck] = 1
    broadcasts: list[dict] = []

    async def _capture(data):
        broadcasts.append(data)

    monkeypatch.setattr(srv, "_broadcast_snapshot", _capture)
    recompute_calls: list[tuple] = []

    def _recompute(ik, t, e, update_source):
        recompute_calls.append((t, e, update_source))

    monkeypatch.setattr(srv, "_schedule_analytics_recompute", _recompute)

    async def _one_tick():
        with srv._sse_lock:
            subs = list(srv._sse_subscribers.keys())
        for (t, e) in subs:
            ik = srv._tier_c_inflight_key(t, e)
            fanout_payload = srv._build_sse_cache_fanout_payload(
                t, e, inflight_key=ik, fanout_reason="sse_loop_cadence"
            )
            if fanout_payload is not None:
                await srv._broadcast_snapshot(fanout_payload)
            srv._schedule_analytics_recompute(ik, t, e, update_source="sse_loop")

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_one_tick())
    assert len(broadcasts) == 1
    assert broadcasts[0].get("ticker") == ticker
    assert recompute_calls == [(ticker, expiry, "sse_loop")]


def test_t5_sse_stream_subscribe_connect_fanout_in_source():
    src = (ROOT / "server.py").read_text(encoding="utf-8", errors="replace")
    assert "fanout_reason=\"subscribe_connect\"" in src
    assert "await _broadcast_snapshot(fanout_payload)" in src
    assert "sse_subscribe_cache_fanout" in src


def test_t5_sse_force_reconnect_uses_active_ticker():
    h = _html()
    assert "force_preamble" in h
    idx = h.find("function connectSSE")
    chunk = h[idx : idx + 4200]
    assert "_tearDownL1LightEventSource" in chunk
    assert "force replace with main SSE" in chunk
    acq = h.find("function runTickerLiveAcquisition")
    acq_chunk = h[acq : acq + 2200]
    assert "force_preamble" in acq_chunk
    assert "connectSSE(force ? { force: true }" in acq_chunk


def test_t5_run_ticker_live_acquisition_no_bare_wanturl():
    """STREAM_ACTIVE must not reference connectSSE-local wantUrl (T5 wantUrl blocker)."""
    h = _html()
    assert "ssePendingUrl: wantUrl" not in h
    assert "_sseStreamUrl || wantUrl" not in h
    acq = h.find("function runTickerLiveAcquisition")
    assert acq != -1
    chunk = h[acq : acq + 2200]
    assert "const pendingSseUrl = _buildSseStreamUrl(activeTicker, activeExpiry)" in chunk
    assert "ssePendingUrl: pendingSseUrl" in chunk
    assert "sseUrl: _sseStreamUrl || pendingSseUrl" in chunk
    assert "wantUrl" not in chunk


def test_t5_fetch_state_force_variable_defined():
    h = _html()
    assert "if (!force && Date.now() < _tierCBackoffUntilMs)" not in h
    assert "if (!forceTierC && Date.now() < _tierCBackoffUntilMs)" in h
    idx = h.find("async function fetchState")
    chunk = h[idx : idx + 12000]
    assert "const forceTierC" in chunk


def test_t5_freshness_pill_does_not_show_fresh_when_bundle_stale():
    h = _html()
    idx = h.find("function _updateDecisionBundleAgeUI")
    assert idx != -1
    chunk = h[idx : idx + 2400]
    assert "bundle_freshness_state" in chunk
    assert "_edMplApplyFreshnessUiLabels" in chunk
    assert "bundleState === 'frozen'" in chunk or "bundleState === \"frozen\"" in chunk
    assert "bundleState === 'stale'" in chunk or "bundleState === \"stale\"" in chunk
    assert "QUOTE FRESH" in chunk


def test_t5_sse_stream_url_set_on_open_not_before():
    h = _html()
    idx = h.find("function connectSSE")
    chunk = h[idx : idx + 4500]
    assert "_sseStreamUrl = null" in chunk
    assert "_sseStreamUrl = es.url || wantUrl" in chunk


def test_t5_stale_actionability_fail_closed_preserved():
    h = _html()
    assert "function _edMplFreshnessActionabilityBlocked" in h
    assert "bundle === 'stale' || bundle === 'frozen'" in h
    assert "data-freshness-fail-closed" in h
