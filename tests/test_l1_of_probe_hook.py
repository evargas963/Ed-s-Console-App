"""RC-404 (Cursor F10): the L1 quote hook carries the SINGLE published order-flow signature and
runs NO second OrderFlowEngine computation.

The prior hybrid input-probe + thin `compute_order_flow_compact` recompute WAS the second producer
this fix removed: it published `order_flow_score` / `book_imbalance_5` on `/api/analytics/light`
from a chain-less input set that diverged from `/api/state`'s full computation at the same tick.
Order flow is now one L2 computation, carried by L1.
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


def test_l1_path_runs_no_second_orderflow_computation(srv_clean_of, monkeypatch):
    """Neither the authoritative L1 build nor the quote hook may invoke a second OF compute."""
    import planes.context_light as cl

    srv = srv_clean_of

    def boom(*a, **k):
        raise AssertionError("RC-404: the L1 path must not run a second OrderFlowEngine compute")

    monkeypatch.setattr(cl, "compute_order_flow_compact", boom)
    srv._project_l1("SPY", None, reason="seed")           # carrier build — must not compute OF
    sig = srv._l1_quote_hook_order_flow_signature("SPY")  # quote hook — must not compute OF
    assert sig is not None


def test_quote_hook_returns_the_published_of_signature(srv_clean_of):
    """The quote-hook signature IS the published snapshot's signature (single source), so an
    unchanged scope matches and the materiality gate skips."""
    srv = srv_clean_of
    srv._project_l1("SPY", None, reason="seed")
    snap = srv._l1_snapshot_cache.get(("SPY", "__auto__"))
    assert snap is not None
    assert srv._l1_quote_hook_order_flow_signature("SPY") == snap["_l1_of_signature"]


def test_diagnostics_includes_of_hook_counters(monkeypatch):
    """TEST_SYSTEM_REHAB_V2 final remediation: get_l1_diagnostics is a plain sync
    handler with no auth/middleware/lifespan dependency -- the HTTP round trip added
    nothing a direct call doesn't already prove."""
    import json

    import server as srv

    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {"spot": 400.0, "bid": 399.0, "ask": 401.0},
    )
    j = json.loads(srv.get_l1_diagnostics().body)["ed_l1"]
    assert "l1_of_quote_hook_engine_total" in j
    assert "l1_of_quote_hook_reuse_total" in j
