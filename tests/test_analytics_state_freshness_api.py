"""S2A/S2B — Tier C /api/analytics/state card_freshness_v1 + operator mirror contract tests."""

from __future__ import annotations

import json
import time

import pytest

_CARD_FRESHNESS_V1_REQUIRED_KEYS = frozenset(
    {
        "card_trust_state",
        "card_actionable",
        "analytics_age_sec",
        "quote_age_sec",
        "bundle_age_sec",
        "analytics_ttl_sec",
        "quote_stale_sec",
        "bundle_trust_sec",
        "source_freshness",
        "stale_reason_codes",
        "quote_ts",
        "bundle_ts",
        "mhap_bundle_ts",
        "tier_c_cache_revalidated",
        "tier_c_cache_gate_ok",
        "analytics_stale",
        "analytics_generated_at",
        "analytics_refresh_in_progress",
    }
)

_OPERATOR_MIRROR_KEYS = frozenset(
    {
        "operator_card_actionable",
        "operator_card_trust_state",
        "operator_stale_reason_codes",
        "operator_actionability_reason",
    }
)

_RAW_TRADE_FIELDS = (
    "final_tradeable",
    "call_signal",
    "call_state",
    "validation_passed",
    "analytics_stale",
)


def _mhap_four() -> list[dict]:
    return [{"horizon": h, "call": {"dir": "flat"}} for h in ("1c", "5c", "15c", "60c")]


def _trusted_ms_dict(*, ticker: str = "ZZZ_CF1", bundle_ts: float | None = None) -> dict:
    now = time.time()
    ts = bundle_ts if bundle_ts is not None else now - 1.0
    return {
        "ticker": ticker,
        "selected_exp": "2099-12-01",
        "final_tradeable": True,
        "call_signal": "wait",
        "call_state": "WATCH",
        "validation_passed": True,
        "fusion_available": True,
        "mhap_rows": _mhap_four(),
        "_server_build_ts": ts,
        "spot": 500.0,
        "prior_close": 500.0,
    }


@pytest.fixture()
def tier_c_cache_spy(monkeypatch):
    import server as srv

    monkeypatch.setattr(srv, "_schedule_analytics_recompute", lambda *a, **k: None)
    monkeypatch.setattr(srv, "_attach_db_contention_operator_surface", lambda md: None)
    monkeypatch.setattr(srv, "_touch_tracked_ticker_view", lambda *a, **k: None)
    try:
        import market_state as ms

        monkeypatch.setattr(ms, "attach_operator_visible_field_lineage", lambda md: None)
    except ImportError:
        pass
    keys_before = set(srv._state_cache.keys())
    yield srv
    for key in list(srv._state_cache.keys()):
        if key not in keys_before:
            srv._state_cache.pop(key, None)


def _seed_cache(srv, ticker: str, expiry: str, ms_dict: dict, *, age_sec: float = 1.0) -> tuple:
    now = time.time()
    gen = now - age_sec
    key = (ticker, expiry)
    ms = dict(ms_dict)
    ms.setdefault("_server_build_ts", gen)
    srv._state_cache[key] = {
        "ms_dict": ms,
        "ts": gen,
        "generated_at": gen,
        "analytics_version": 2,
    }
    return key


def _response_body(resp) -> dict:
    return json.loads(resp.body)


def _operator_mirrors(body: dict) -> dict:
    return {k: body.get(k) for k in _OPERATOR_MIRROR_KEYS}


def _assert_operator_mirrors_nested(body: dict) -> None:
    block = body["card_freshness_v1"]
    assert body["operator_card_actionable"] is block["card_actionable"]
    assert body["operator_card_trust_state"] == block["card_trust_state"]
    assert body["operator_stale_reason_codes"] == block["stale_reason_codes"]
    if block["card_actionable"]:
        assert body["operator_actionability_reason"] is None
    else:
        assert body["operator_actionability_reason"] is not None





























# ── SESSION_OPEN_ANCHOR_WARM_SLICE_V1 — RTH-open anchor warm locks ───────────
















# ── TIER_C_STAGE_TIMER_INSTRUMENTATION_V1 — stage timing + cache observability locks ──






def test_executor_sizing_unchanged_by_stage_timer_slice():
    """Hard constraint: analytics executor stays at 4 workers (no sizing change in this slice)."""
    import server as srv

    assert srv._get_analytics_executor()._max_workers == 4






# ── TIER_C_CHAIN_FETCH_GATE_IMPLEMENTATION_V1 — chain-fetch gate locks ────────


def test_chain_fetch_gate_serializes_concurrent_fetches(monkeypatch):
    """CHAIN_GATE_V2 (operator-approved 2026-07-10 EVE): concurrency is
    BOUNDED at two global slots — three distinct-ticker threads never exceed
    two inside safe_get_chain."""
    import threading as th

    import server as srv

    monkeypatch.setattr(srv, "_schwab_chain_fetch_gate", srv._ChainGateV2())
    monkeypatch.setattr(srv, "_chain_inflight", {})
    active = {"n": 0, "max": 0}
    lk = th.Lock()

    # RC-239: the production call site passes `to_date=` as well; a stub that omits it does
    # not stand in for the real callee, it just raises TypeError inside the gate. Cursor-audit F2
    # added `from_date=` (single-expiry near-edge bound) — the stub mirrors the real signature.
    # OPTIONS_ORDER_FLOW_V1 round 3 added `strike_range=` (see the source-shape lock test above).
    def _slow_chain(client, ticker, *, strike_count=None, strike_range=None, to_date=None, from_date=None):
        with lk:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        time.sleep(0.15)
        with lk:
            active["n"] -= 1
        return f"RESP_{ticker}"

    monkeypatch.setattr(srv, "safe_get_chain", _slow_chain)
    threads = [
        th.Thread(target=srv._gated_safe_get_chain, args=(None, f"ZZZ_G{i}"), kwargs={"strike_count": 5})
        for i in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert active["max"] <= srv.CHAIN_GATE_GLOBAL_SLOTS_MAX == 2


def test_chain_fetch_gate_fail_open_on_timeout(monkeypatch):
    """Gate held elsewhere + short timeout: fetch still executes; timeout counter increments."""
    import server as srv

    # Order-independence: use a FRESH gate, never the process-global one. This test
    # asserts the gate starts fully free; any earlier test that leaks a slot on the
    # shared instance would otherwise fail it (observed 2026-07-19 only inside the
    # full 301-file run, never standalone). Same construction as the sibling
    # concurrency test above.
    monkeypatch.setattr(srv, "_schwab_chain_fetch_gate", srv._ChainGateV2())
    monkeypatch.setattr(srv, "_chain_inflight", {})
    monkeypatch.setattr(srv, "CHAIN_FETCH_GATE_ACQUIRE_TIMEOUT_SEC", 0.05)
    calls: list[str] = []
    monkeypatch.setattr(
        srv,
        "safe_get_chain",
        lambda client, ticker, *, strike_count=None, strike_range=None, to_date=None, from_date=None: (calls.append(ticker), "RESP")[1],
    )
    # CHAIN_GATE_V2: two slots — saturate both to force the timeout path.
    assert srv._schwab_chain_fetch_gate.acquire(timeout=1)
    assert srv._schwab_chain_fetch_gate.acquire(timeout=1)
    try:
        before = srv._chain_fetch_gate_timeout_count
        resp, gate_wait_sec, fetch_sec = srv._gated_safe_get_chain(None, "ZZZ_TMO", strike_count=5)
        assert resp == "RESP"
        assert calls == ["ZZZ_TMO"]
        assert srv._chain_fetch_gate_timeout_count == before + 1
        assert gate_wait_sec >= 0.05
        assert fetch_sec >= 0.0
    finally:
        srv._schwab_chain_fetch_gate.release()
        srv._schwab_chain_fetch_gate.release()
    # Timeout path must not double-release: exactly two slots acquirable now.
    assert srv._schwab_chain_fetch_gate.acquire(timeout=1)
    assert srv._schwab_chain_fetch_gate.acquire(timeout=1)
    srv._schwab_chain_fetch_gate.release()
    srv._schwab_chain_fetch_gate.release()


def test_chain_fetch_gate_returns_timings_on_normal_path(monkeypatch):
    """Uncontended gate: response + non-negative gate wait + fetch duration."""
    import server as srv

    # Order-independence: fresh gate (see the timeout test above). The final
    # "immediately acquirable" assertion requires a gate no other test has touched.
    monkeypatch.setattr(srv, "_schwab_chain_fetch_gate", srv._ChainGateV2())
    monkeypatch.setattr(srv, "_chain_inflight", {})
    monkeypatch.setattr(
        srv, "safe_get_chain",
        lambda client, ticker, *, strike_count=None, strike_range=None, to_date=None, from_date=None: "OK")
    resp, gate_wait_sec, fetch_sec = srv._gated_safe_get_chain(None, "ZZZ_NORM", strike_count=5)
    assert resp == "OK"
    assert gate_wait_sec >= 0.0
    assert fetch_sec >= 0.0
    # Gate released: immediately acquirable.
    assert srv._schwab_chain_fetch_gate.acquire(timeout=1)
    srv._schwab_chain_fetch_gate.release()




# ── ANCHOR_QUOTE_LANE_REFRESHER_V1 ────────────────────────────────────────────


class _FakePlane:
    """Minimal live_market_plane stand-in: per-ticker rows, read-only for the refresher."""

    def __init__(self, rows: dict):
        self.rows = rows

    def get_quote(self, ticker: str):
        return self.rows.get(ticker)


def test_no_rest_quote_refresher_feeds_the_live_plane():
    """The ANCHOR_QUOTE_LANE_REFRESHER re-quoted SPY/QQQ/IWM over REST every 20s into the
    live plane whenever their streamed quote aged past 20s -- a REST fallback for three named
    tickers. Deleted (operator rules 2026-09-23: no fallbacks, universality): a stale streamed
    quote now reads stale."""
    import inspect

    import server as srv
    src = inspect.getsource(srv)
    assert "_anchor_quote_lane" not in src and "rest_anchor_lane_refresher" not in src


# ── ANALYTICS_LOG_ONLY_CACHE_CLOBBER_GUARD_V1 ────────────────────────────────


def _full_bundle_entry(version: int, gen_ts: float) -> dict:
    """Fixture: cache entry shaped like a full Tier C publish (server.py full-write site)."""
    return {
        "ts": gen_ts,
        "generated_at": gen_ts,
        "analytics_version": version,
        "ms_dict": {"mhap_rows": [{"h": "1c"}], "fusion_available": True, "spot": 100.0},
        "pcr_val": 0.9,
        "spot_f": 100.0,
        "vix": 15.0,
        "price_levels": {"lvl": 1},
        "pl_date": "2026-07-07",
        "pl_mono": 123.0,
    }


def _clear_fixture_cache_keys(srv, ticker: str) -> None:
    for k in [k for k in list(srv._state_cache) if k[0] == ticker]:
        del srv._state_cache[k]


















# ── FIX_B_PUBLISH_BEFORE_LOG_REORDER_V1 ──────────────────────────────────────


def _fetch_state_source() -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")


def _fetch_state_ast():
    import ast

    tree = ast.parse(_fetch_state_source())
    fetch = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_fetch_state"
    )
    tail = next(
        n for n in ast.walk(fetch)
        if isinstance(n, ast.FunctionDef) and n.name == "_post_publish_persistence_tail"
    )
    return fetch, tail














# ── OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_1 ───────────────────────────────










# ── OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_2 ───────────────────────────────




def test_step2_leaf_functions_have_no_nested_submit():
    """AST leaf lock: leaf functions, schwab_client, and the price_bars_1m readers
    contain no .submit() anywhere — the nested-submit deadlock class cannot form."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent

    def submit_sites(path, names=None):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if names and node.name not in names:
                    continue
                for sub in ast.walk(node):
                    if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                            and sub.func.attr == "submit"):
                        out.append((node.name, sub.lineno))
        return out

    assert submit_sites(root / "server.py",
                        {"_gated_safe_get_chain", "_safe_get_quote_with_retry",
                         "_read_bars_1m", "_bars_1m", "_bars_5m"}) == []
    assert submit_sites(root / "schwab_client.py") == []
















# ── EXEC-03 POST_PUBLISH_LAST_ERROR_OBSERVABILITY_V1 ─────────────────────────












# ── IDLE_SENTINEL_FRESHNESS_V1 — idle-refresh standing producer locks ─────────


def _idle_seed_cache(srv, monkeypatch, entries):
    """entries: {(ticker, expiry): age_sec | None-for-shell}."""
    import time as _t

    now = _t.time()
    cache = {}
    for key, age in entries.items():
        if age is None:
            cache[key] = {"ts": now, "ms_dict": {}}  # pending-shell-like: empty body
        else:
            cache[key] = {"ts": now - age, "ms_dict": {"ticker": key[0]}}
    monkeypatch.setattr(srv, "_state_cache", cache)
    monkeypatch.setattr(srv, "_analytics_inflight", set())
    # RC-483: the idle standing producer now keeps only ENROLLED cards warm (an un-enrolled
    # viewed-once card must not be resurrected — the CRM/DKS defect). These tests exercise the
    # selection MECHANICS (oldest-first, rate-bound, owner-exclusion), so their seeded tickers
    # are enrolled here; the enrollment-scoping itself is pinned in
    # tests/test_idle_producer_enrolled_only_v1.py.
    monkeypatch.setattr(srv, "_logger_tickers", [k[0] for k in entries], raising=False)




















# ── UI_05_OPERATOR_PRIORITY_ADMISSION_V1 — priority admission + gate locks ────










def test_ui05_priority_gate_priority_waiter_acquires_first():
    """With the slot held and one background + one priority waiter queued, the
    priority waiter gets the slot on release."""
    import threading as th

    import server as srv

    gate = srv._ChainGateV2()
    gate.record_result(False, throttled=True)  # degrade to capacity 1
    assert gate.acquire(timeout=1)  # hold the slot
    order = []
    bg_started = th.Event()
    prio_started = th.Event()

    def bg():
        bg_started.set()
        assert gate.acquire(timeout=10)
        order.append("background")
        gate.release()

    def prio():
        prio_started.set()
        assert gate.acquire(timeout=10, priority=True)
        order.append("priority")
        gate.release()

    t_bg = th.Thread(target=bg)
    t_bg.start()
    bg_started.wait(2)
    import time as _t

    _t.sleep(0.15)  # background waiter is queued first
    t_prio = th.Thread(target=prio)
    t_prio.start()
    prio_started.wait(2)
    _t.sleep(0.15)
    gate.release()
    t_prio.join(5)
    t_bg.join(5)
    assert order == ["priority", "background"]
    # slot fully restored
    assert gate.acquire(timeout=1)
    gate.release()




# ── UI_05 residual — priority leaf lane + startup model prewarm sweep ────────






def test_ui05r_priority_leaf_teardown_present():
    src = _fetch_state_source()
    assert src.count("_priority_leaf_executor.shutdown(wait=True, cancel_futures=True)") == 1








# ── UI_05 tail closure: market-context single-flight + stale-while-refresh ────


def _mkt_ctx_test_reset(srv, ctx=None, age_sec=0.0):
    with srv._cached_mkt_ctx_lock:
        srv._cached_mkt_ctx = ctx
        srv._cached_mkt_ctx_ts = (time.time() - age_sec) if ctx is not None else 0.0
        srv._mkt_ctx_refresh_inflight = False








