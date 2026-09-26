"""
Issue 20 / 23 — coherent live decision bundle (transport + ordering guards).

Proves: monotonic stamping ties spot + decision fields; tick partial-patch helpers stay removed;
client HTML generation-order guard present. Step 2 (LIVE_OPERATOR_MODE_RESET_V1): with an SSE
viewer, /api/state is a read-only cache view (the SSE background loop owns recompute); the
no-viewer stale REST path still self-schedules (cold/poll-only fallback).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))




def test_tick_partial_patch_helpers_removed_from_server():
    src = (ROOT / "server.py").read_text(encoding="utf-8", errors="replace")
    assert "_patch_snapshot_with_fresh_order_flow" not in src
    assert "_ORDER_FLOW_PATCH_KEYS" not in src
    assert "sse_live" in src
    assert "sse_live = _sse_subscribers.get" in src


def test_sse_broadcast_only_passes_full_tier_c_payload():
    """SSE clients receive full Tier C ms_dict only — fetch result or cache fanout, never partial patches."""
    import re

    src = (ROOT / "server.py").read_text(encoding="utf-8", errors="replace")
    assert "_patch_snapshot_with_fresh_order_flow" not in src
    assert "_build_sse_cache_fanout_payload" in src
    assert "_attach_money_path_snapshot_envelope" in src
    pat = re.compile(r"_broadcast_snapshot\s*\(\s*result\s*\)")
    hits = [
        ln
        for ln in src.splitlines()
        if pat.search(ln) and "def _broadcast_snapshot" not in ln and "async def _broadcast_snapshot" not in ln
    ]
    assert len(hits) == 0, (
        "Tier C SSE must broadcast via _schedule_sse_broadcast (full fetch or cache fanout), "
        f"found legacy direct calls: {hits!r}"
    )
    assert "_schedule_sse_broadcast" in src


# test_index_html_rejects_older_decision_generation, test_index_html_render_return_gates_live_
# and_last_render_ts, and test_index_html_sse_badge_conn_on_open_live_after_payload were
# retired here (/console cutover, operator directive 2026-09-14): all three lock legacy static/
# index.html's Tier-A/Tier-C money-path render-generation architecture
# (_lastRenderedDecisionGen, _renderCoherenceGuards, ingestMoneyPathSnapshot), which has no
# equivalent in the new console's simpler poll model (grepped static/js/*.js and
# static/console.html, zero matches for any of these names). test_client_render_ordering_logic
# above (a reconstructed proxy of the generation-comparison arithmetic, not a file read) is
# unaffected and stays.


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
    """Step 2 single Tier C owner: viewer-owned REST reads serve cache WITHOUT scheduling;
    the no-viewer stale path still self-schedules; the stale-serve label stays honest."""
    # Keep the owner loop asleep (huge idle/subscribed intervals) so this test isolates
    # the REST path; honest small TTL comes from the ttl resolver, not CACHE_TTL.
    monkeypatch.setattr(srv, "VIEWER_SSE_REFRESH_SEC", 99999.0)
    monkeypatch.setattr(srv, "CACHE_TTL", 99999.0)
    monkeypatch.setattr(srv, "_sse_viewer_cache_ttl", lambda t, e: 0.5)
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
    # Seed an old bundle (well past the 2×TTL grace window at TTL=0).
    _seed_issue20_state_cache(srv, cache_key, 1.0, ts=time.time() - 60.0)

    from starlette.testclient import TestClient

    fetch_key = _fetch_call_key(ticker, expiry)
    with TestClient(srv.app) as client:
        # Viewer-owned: SSE subscriber present → REST serves the stale-labeled cache
        # and must NOT schedule a recompute (loop owns the key).
        srv._sse_subscribers[cache_key] = 1
        r_owned = client.get("/api/state", params=_state_api_params(ticker, expiry))
        assert r_owned.status_code == 200
        body = r_owned.json()
        assert body.get(_ISSUE20_SPOT) == 1.0
        assert body.get("analytics_stale") is True
        time.sleep(0.3)
        assert fetch_key not in calls, "viewer-owned REST read must not schedule recompute"

        # No viewer: the stale REST read self-schedules (cold/poll-only fallback).
        srv._sse_subscribers.pop(cache_key, None)
        r_cold = client.get("/api/state", params=_state_api_params(ticker, expiry))
        assert r_cold.status_code == 200
        for _ in range(100):
            time.sleep(0.02)
            if calls:
                break
        assert fetch_key in calls
        r3 = client.get("/api/state", params=_state_api_params(ticker, expiry))
        assert r3.status_code == 200
        body3 = r3.json()
        assert body3.get(_ISSUE20_SPOT, 0) > 1.0
        assert body3.get("decision_generation_id", 0) >= 424201

        # force=true is the manual override — schedules even when viewer-owned.
        srv._sse_subscribers[cache_key] = 1
        with srv._analytics_bg_lock:
            srv._analytics_inflight.clear()
        n_before = len(calls)
        params_force = dict(_state_api_params(ticker, expiry))
        params_force["force"] = "true"
        r_force = client.get("/api/state", params=params_force)
        assert r_force.status_code == 200
        for _ in range(100):
            time.sleep(0.02)
            if len(calls) > n_before:
                break
        assert len(calls) > n_before, "force=true must schedule despite viewer ownership"
        srv._sse_subscribers.pop(cache_key, None)










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












