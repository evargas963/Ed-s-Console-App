"""
L1 quote-hook OF probe: hybrid input probe + cadence + periodic refresh — no duplicate _project_l1.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def srv_clean_of(monkeypatch):
    import server as srv

    monkeypatch.setattr(srv._lmp, "apply_l1_live_quote_overlay", lambda *a, **k: None)
    for d in (srv._l1_of_sig_cache_by_ticker, srv._l1_of_probe_by_ticker, srv._l1_of_last_engine_mono_by_ticker):
        d.clear()
    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {"spot": 100.0, "bid": 99.0, "ask": 101.0, "fast_generation_id": 1.0},
    )
    yield srv


def test_quote_hook_engine_runs_when_probe_cache_cold(srv_clean_of, monkeypatch):
    import planes.context_light as cl

    srv = srv_clean_of
    calls: list[int] = []
    _real = cl.compute_order_flow_compact

    def track(t, row):
        calls.append(1)
        return _real(t, row)

    monkeypatch.setattr(cl, "compute_order_flow_compact", track)
    srv._l1_quote_hook_order_flow_signature("SPY")
    assert len(calls) == 1
    assert srv._l1_instrumentation["l1_of_quote_hook_engine_total"] >= 1


def test_quote_hook_reuses_when_probe_unchanged(srv_clean_of, monkeypatch):
    import planes.context_light as cl

    srv = srv_clean_of
    calls: list[int] = []
    _real = cl.compute_order_flow_compact

    def track(t, row):
        calls.append(1)
        return _real(t, row)

    monkeypatch.setattr(cl, "compute_order_flow_compact", track)
    srv._l1_quote_hook_order_flow_signature("SPY")
    assert len(calls) == 1
    srv._l1_quote_hook_order_flow_signature("SPY")
    assert len(calls) == 1
    assert int(srv._l1_instrumentation["l1_of_quote_hook_reuse_total"]) >= 1


def test_project_l1_syncs_probe_cache_so_hook_reuses(srv_clean_of, monkeypatch):
    import planes.context_light as cl

    srv = srv_clean_of
    calls: list[int] = []
    _real = cl.compute_order_flow_compact

    def track(t, row):
        calls.append(1)
        return _real(t, row)

    monkeypatch.setattr(cl, "compute_order_flow_compact", track)
    srv._project_l1("SPY", None, reason="seed")
    n_after_project = len(calls)
    assert n_after_project >= 1
    srv._l1_quote_hook_order_flow_signature("SPY")
    assert len(calls) == n_after_project


def test_diagnostics_includes_of_hook_counters(monkeypatch):
    from starlette.testclient import TestClient

    import server as srv

    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {"spot": 400.0, "bid": 399.0, "ask": 401.0},
    )
    with TestClient(srv.app) as client:
        r = client.get("/api/diagnostics/l1")
        j = r.json()["ed_l1"]
        assert "l1_of_quote_hook_engine_total" in j
        assert "l1_of_quote_hook_reuse_total" in j
        assert "L1_OF_MIN_COMPUTE_INTERVAL_SEC" in j["policy"]
        assert "L1_OF_PROBE_FORCE_REFRESH_SEC" in j["policy"]
