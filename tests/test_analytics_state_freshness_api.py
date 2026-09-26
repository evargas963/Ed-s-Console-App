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




def test_stage_timer_surfaces_present_in_fetch_state_source():
    """Source lock: stage marks + additive timing fields exist in the Tier C recompute path."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    for needle in (
        '_stage_marks.append(("stack_runtime_governance_attach"',
        '_stage_marks.append(("db_snapshot_write_accuracy"',
        '_stage_marks.append(("signals_engine_build_market_state"',
        'ms_dict["_compute_breakdown"]',
        'ms_dict["_finalize_tail_ms"]',
        'result["analytics_executor_queue_wait_sec"]',
        'ms_dict["analytics_cache_observability_v1"]',
    ):
        assert needle in src, f"missing stage-timer surface: {needle}"


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


def test_chain_fetch_call_shape_and_gated_site_source_lock():
    """Fidelity lock: helper preserves the exact Schwab call shape; _fetch_state routes through it.

    UI_05_OPERATOR_PRIORITY_ADMISSION_V1 threads a priority flag into the gated call — the Schwab
    call shape inside the helper is unchanged.

    2026-09-25: the width is gone -- the state chain is the selected expiry's FULL chain.
    Historical note, RC-59: the WIDTH source changed deliberately. _fetch_state used to pass the hardcoded
    CHAIN_STRIKE_COUNT (20), which analysed the console on a ~±6.6%-of-spot chain while terrain
    used geometry-sized widths — the same ticker measured two ways. Width now comes from the ONE
    faucet, resolve_chain_strike_count(). This lock therefore asserts the INTENT (gated helper +
    priority flag + faucet-sourced width) rather than a frozen literal, so a genuine improvement
    does not read as a regression while a real drift still fails.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    # RC-239: the call shape gained `to_date=` (expiry scoping); Cursor-audit F2 added `from_date=`
    # (single-expiry near-edge bound). The lock asserts the SHAPE — gated helper, faucet-sourced
    # width, and every kwarg named — rather than a frozen literal that goes stale the moment a
    # legitimate argument is added.
    assert "resp = safe_get_chain(client, ticker, strike_count=strike_count, strike_range=strike_range,\n                              to_date=to_date, from_date=from_date)" in src
    # both _fetch_state branches take the selected expiry's FULL chain (2026-09-25; no strike
    # window anywhere -- enforced repo-wide by check_chain_width_single_faucet)
    assert src.count("_fetch_state_chain, client, ticker, expiry, _chain_priority") == 1
    assert src.count("_fetch_state_chain(client, ticker, expiry, _chain_priority)") == 1
    assert 'ms_dict["chain_gate_wait_sec"]' in src
    assert '_stage_ms["chain_gate_wait_ms"]' in src


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














def test_log_only_branch_routes_through_guard_source_lock():
    """Source lock: the log_only branch calls _log_only_cache_touch; no inline clobber remains."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    assert "_log_only_cache_touch(" in src
    # The old inline clobber wrote ms_dict {} directly at the log_only branch;
    # the only remaining empty-ms_dict cache write lives inside the guarded helper.
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_fetch_state")
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Assign):
            for tgt in sub.targets:
                if (isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "_state_cache" and isinstance(sub.value, ast.Dict)):
                    dict_keys = {k.value for k in sub.value.keys if isinstance(k, ast.Constant)}
                    assert "generated_at" in dict_keys, (
                        "_fetch_state writes a _state_cache dict without generated_at "
                        "(log_only clobber shape) — must route through _log_only_cache_touch"
                    )


def test_log_only_guard_ticker_agnostic_no_literals():
    """AST lock: no uppercase ticker literals in the guard functions."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    targets = {"_analytics_cache_entry_is_full_bundle", "_log_only_cache_touch"}
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in targets:
            found.add(node.name)
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    assert not (sub.value.isalpha() and sub.value.isupper()), (
                        f"ticker-literal-shaped constant {sub.value!r} in {node.name}"
                    )
    assert found == targets


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


def test_fix_b_publish_precedes_persistence_tail_source_lock():
    """Stage-order lock: the generated_at-stamping publish precedes the full-path
    tail call; the persistence stage marks live inside the tail def, which is
    defined before but executed after the publish."""
    src = _fetch_state_source()
    i_pub = src.index('"generated_at": _gen_ts')
    i_full_call = src.index("_post_publish_persistence_tail(_next_ver")
    i_tail_def = src.index("def _post_publish_persistence_tail(")
    i_snap_mark = src.index('_stage_marks.append(("db_snapshot_write_accuracy"')
    i_cal_mark = src.index('_stage_marks.append(("v2_calibration_logging"')
    assert i_pub < i_full_call, "full-path tail call must come AFTER the publish"
    assert i_tail_def < i_snap_mark < i_cal_mark < i_pub, (
        "persistence stage marks must live inside the tail def, "
        "which is defined before (but executed after) the publish"
    )


def test_fix_b_payload_shape_keys_still_served():
    """Payload-shape regression: counters/accuracy keys still assembled pre-publish
    (documented one-cycle lag; values come from the pre-read count + module cache)."""
    src = _fetch_state_source()
    assert 'ms_dict["total_snapshots"]  = db_counts.get("total", 0)' in src
    assert 'ms_dict["filled_snapshots"] = db_counts.get("filled", 0)' in src
    assert 'ms_dict["accuracy_scope"] = "rth_0930_1600_et"' in src
    # The pre-read count SELECT (read-only) still precedes the block.
    assert "db_counts = _ed_db.count_snapshots(ticker, CANONICAL_TIMEFRAME)" in src


def test_fix_b_once_per_cycle_call_sites():
    """Once-per-cycle: exactly one tail def; exactly two mutually-exclusive call
    sites (log_only pre-return, full-path post-publish); exactly one calibration
    append inside the tail."""
    import ast

    fetch, tail = _fetch_state_ast()
    defs = [
        n for n in ast.walk(fetch)
        if isinstance(n, ast.FunctionDef) and n.name == "_post_publish_persistence_tail"
    ]
    assert len(defs) == 1
    calls = [
        n for n in ast.walk(fetch)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "_post_publish_persistence_tail"
    ]
    assert len(calls) == 2, "exactly log_only pre-return + full-path post-publish"
    appends = [
        n for n in ast.walk(tail)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "append_live_v2_calibration_decision"
    ]
    assert len(appends) == 1
    # The log_only branch returns before the full path can reach the second call.
    src = _fetch_state_source()
    i_log_only_call = src.index("_post_publish_persistence_tail(None, _v2_decision_for_response)")
    i_log_only_return = src.index("return {}", i_log_only_call)
    i_full_call = src.index("_post_publish_persistence_tail(_next_ver")
    assert i_log_only_call < i_log_only_return < i_full_call




def test_fix_b_v2_decision_parity_served_equals_logged():
    """v2_decision parity: the full-path tail call passes the SERVED object
    (ms_dict['v2_decision']); the log_only path passes the built decision."""
    src = _fetch_state_source()
    assert '_post_publish_persistence_tail(_next_ver, ms_dict["v2_decision"])' in src
    assert "_post_publish_persistence_tail(None, _v2_decision_for_response)" in src
    assert "v2_decision=v2_decision_for_log," in src


def test_fix_b_tail_never_touches_state_cache():
    """Isolation lock: the tail never references _state_cache, and the prev-vix
    capture holds structurally (VOL_INPUT_CONTRACT 1.0.0 renamed it to
    _vol_prev_published_vix; the old exact-string anchor was brittle):
    (a) exactly one capture binding exists in _fetch_state;
    (b) it reads _state_cache.get(_cache_key, ...).get("vix") — the prior
        published cache entry under the exact cycle key, no other source;
    (c) it precedes every dict-literal _state_cache[_cache_key] publish that
        carries a "vix" key, so this cycle's publish can never contaminate
        the previous-value calculation."""
    import ast

    fetch, tail = _fetch_state_ast()
    names = {s.id for s in ast.walk(tail) if isinstance(s, ast.Name)}
    assert "_state_cache" not in names

    captures = [
        node for node in ast.walk(fetch)
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_vol_prev_published_vix"
            for t in node.targets
        )
    ]
    assert len(captures) == 1, "exactly one pre-publish prev-vix capture"
    cap = captures[0]
    outer = cap.value
    assert isinstance(outer, ast.Call) and isinstance(outer.func, ast.Attribute)
    assert outer.func.attr == "get"
    assert [a.value for a in outer.args if isinstance(a, ast.Constant)] == ["vix"]
    inner = outer.func.value
    assert isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
    assert inner.func.attr == "get"
    assert isinstance(inner.func.value, ast.Name)
    assert inner.func.value.id == "_state_cache", "prev vix must come from the state cache"
    assert any(
        isinstance(a, ast.Name) and a.id == "_cache_key" for a in inner.args
    ), "prev vix must read the exact per-cycle cache key"

    publishes = [
        node for node in ast.walk(fetch)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Dict)
        and any(
            isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
            and t.value.id == "_state_cache"
            for t in node.targets
        )
        and "vix" in {
            k.value for k in node.value.keys if isinstance(k, ast.Constant)
        }
    ]
    assert publishes, "expected a vix-carrying _state_cache publish in _fetch_state"
    assert all(cap.lineno < p.lineno for p in publishes), (
        "the prev-vix capture must precede every vix-carrying publish"
    )


# ── OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_1 ───────────────────────────────


def test_step1_log_only_inline_source_lock():
    """log_only joins the shutdown inline path for chain/quote; the operator-facing
    submit remains. Bars are no longer seeded per request (price_bars_1m is written
    only from the streamed bars), so the chain/quote leg is the only nested leaf."""
    src = _fetch_state_source()
    i_inline_cq = src.index("if _analytics_bg_shutdown or _log_only_inline_leaf_fetches(log_only):")
    # Step 2 rebinds the pooled arm to the dedicated leaf pool; the Step 1
    # invariant (inline arm precedes the pooled arm) is pool-independent.
    i_pool_cq = src.index("_cq_pool = (")
    assert i_inline_cq < i_pool_cq, "inline chain/quote arm must precede the pooled arm"
    # Operator-facing bounded parallelism intact (submit still present).
    assert "_chain_fut = _cq_pool.submit(" in src
    assert "_seed_candles" not in src and "_seed_pool" not in src






def test_step1_shutdown_inline_branch_preserved():
    """Shutdown keeps its pre-existing inline behavior via the call-site or."""
    src = _fetch_state_source()
    assert "_analytics_bg_shutdown or _log_only_inline_leaf_fetches(log_only)" in src


# ── OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_2 ───────────────────────────────


def test_step2_leaf_executor_referenced_only_in_fetch_state_leaf_blocks():
    """AST lock: _get_recompute_leaf_executor is called only inside _fetch_state
    (the chain/quote and seed submit blocks) — never by handlers or other code."""
    import ast

    tree = ast.parse(_fetch_state_source())
    callers = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                        and sub.func.id == "_get_recompute_leaf_executor"
                        and node.name != "_get_recompute_leaf_executor"):
                    callers.append(node.name)
    # Nested walk double-counts under enclosing defs; the set must be exactly
    # _fetch_state (call sites live directly in its body, not in nested defs).
    assert set(callers) == {"_fetch_state"}, f"unexpected callers: {sorted(set(callers))}"
    src = _fetch_state_source()
    # Call sites only (the bare substring also matches the def line).
    # UI_05 residual: both sites are now conditional expressions selecting the
    # priority lane vs the shared leaf pool.
    # the candle-seed leg was deleted with the per-request seeding: chain/quote only
    assert src.count("else _get_recompute_leaf_executor()") == 1  # chain/quote


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




def test_step2_nested_submit_sites_use_leaf_pool_not_route_pool():
    """Source lock: the nested-submit site binds the leaf pool; the route pool
    is not referenced by it."""
    src = _fetch_state_source()
    # UI_05 residual: the leaf site selects the bounded PRIORITY leaf lane for
    # operator-priority recomputes and the shared leaf pool otherwise — the route
    # pool stays banned. The candle-seed site was deleted with per-request seeding,
    # leaving the chain/quote site as the only one.
    assert src.count("if _chain_priority") >= 1
    assert src.count("else _get_recompute_leaf_executor()") == 1
    assert src.count("_get_priority_leaf_executor()") >= 1
    assert "_cq_pool = _get_route_offload_executor()" not in src
    assert "_seed_pool" not in src


def test_step2_log_only_uses_neither_pool_for_nested_work():
    """Step 1 preserved: the inline arm precedes the submit block, so log_only
    reaches neither the route pool nor the leaf pool for nested work."""
    src = _fetch_state_source()
    i_inline_cq = src.index("if _analytics_bg_shutdown or _log_only_inline_leaf_fetches(log_only):")
    i_pool_cq = src.index("_cq_pool = (")
    assert i_inline_cq < i_pool_cq
    assert "_seed_pool" not in src


def test_step2_shutdown_order_and_inline_branch():
    """Leaf-pool teardown comes after the analytics executor shutdown, and the
    _analytics_bg_shutdown condition still forces inline leaf fetches."""
    src = _fetch_state_source()
    i_analytics_shutdown = src.index("_shutdown_analytics_executor(wait=True)")
    i_leaf_teardown = src.index("_recompute_leaf_executor.shutdown(wait=True, cancel_futures=True)")
    assert i_analytics_shutdown < i_leaf_teardown
    assert "_analytics_bg_shutdown or _log_only_inline_leaf_fetches(log_only)" in src


def test_step2_no_ticker_session_horizon_literals():
    """AST lock on the new getter: no uppercase ticker/session literal constants."""
    import ast

    tree = ast.parse(_fetch_state_source())
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_get_recompute_leaf_executor"
    )
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            assert not (sub.value.isalpha() and sub.value.isupper()), (
                f"literal-shaped constant {sub.value!r} in leaf-pool getter"
            )






# ── EXEC-03 POST_PUBLISH_LAST_ERROR_OBSERVABILITY_V1 ─────────────────────────






def test_post_publish_last_error_wired_at_both_failure_branches():
    """Both tail except-handlers record cause detail right after their counter
    increment; the payload attaches a copy adjacent to the observability block."""
    src = _fetch_state_source()
    i_snap_inc = src.index('_analytics_cache_observability["post_publish_snapshot_failures"] += 1')
    i_snap_rec = src.index('_record_post_publish_failure("snapshot", ticker, published_version, e)')
    i_cal_inc = src.index('_analytics_cache_observability["post_publish_calibration_failures"] += 1')
    i_cal_rec = src.index(
        '_record_post_publish_failure("calibration", ticker, published_version, _v2_log_e)'
    )
    assert i_snap_inc < i_snap_rec < i_cal_inc < i_cal_rec
    i_obs_attach = src.index('ms_dict["analytics_cache_observability_v1"] = dict(')
    i_err_attach = src.index('ms_dict["post_publish_last_errors_v1"] = {')
    assert i_obs_attach < i_err_attach


def test_tail_no_unbound_shadow_of_fetch_state_locals():
    """Relocation-class lock: no name stored in the tail may shadow a
    _fetch_state-level binding AND be read at-or-before its first tail store
    without a nonlocal declaration (the mkt_ctx UnboundLocalError class).
    Comprehension targets are scope-isolated in py3 and excluded."""
    import ast

    fetch, tail = _fetch_state_ast()

    comp_targets: set[str] = set()
    for node in ast.walk(tail):
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for gen in node.generators:
                for t in ast.walk(gen.target):
                    if isinstance(t, ast.Name):
                        comp_targets.add(t.id)

    nonlocals: set[str] = set()
    for node in ast.walk(tail):
        if isinstance(node, ast.Nonlocal):
            nonlocals.update(node.names)

    def _stores_and_loads(fn):
        stores: dict[str, int] = {}
        loads: dict[str, list[int]] = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Store):
                    stores.setdefault(node.id, node.lineno)
                    stores[node.id] = min(stores[node.id], node.lineno)
                elif isinstance(node.ctx, ast.Load):
                    loads.setdefault(node.id, []).append(node.lineno)
        return stores, loads

    fetch_stores, _ = _stores_and_loads(fetch)
    fetch_params = {a.arg for a in fetch.args.args + fetch.args.kwonlyargs}
    tail_stores, tail_loads = _stores_and_loads(tail)

    offenders = []
    for name, first_store in tail_stores.items():
        if name in nonlocals or name in comp_targets:
            continue
        if name not in fetch_stores and name not in fetch_params:
            continue
        early = [ln for ln in tail_loads.get(name, []) if ln <= first_store]
        if early:
            offenders.append((name, first_store, early))
    assert not offenders, f"unbound tail shadows of _fetch_state locals: {offenders}"


def test_post_publish_last_error_no_ticker_literals():
    """Universality: the recorder body carries no ticker-literal-shaped constants
    (its dict keys are lowercase kinds; ticker arrives as runtime data)."""
    import ast

    tree = ast.parse(_fetch_state_source())
    rec = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_record_post_publish_failure"
    )
    for sub in ast.walk(rec):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            assert not (sub.value.isalpha() and sub.value.isupper()), (
                f"ticker-literal-shaped constant {sub.value!r} in recorder"
            )


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












def test_idle_refresh_no_ticker_literals_in_selection():
    """Required 6: no ticker-literal-shaped constants drive selection."""
    import ast

    tree = ast.parse(_fetch_state_source())
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_select_idle_stale_keys"
    )
    for node in ast.walk(fn):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not (node.value.isalpha() and node.value.isupper()), (
                f"ticker-literal-shaped constant {node.value!r} in idle selection"
            )








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




def test_ui05r_leaf_pool_selection_source_lock():
    """The chain/quote leg selects the priority lane exactly when the recompute is
    operator-priority (the _chain_priority classifier). (The seed leg was deleted
    with per-request bar seeding.)"""
    src = _fetch_state_source()
    i_cq = src.index("_cq_pool = (")
    assert "_get_priority_leaf_executor()" in src[i_cq:i_cq + 200]
    assert "if _chain_priority" in src[i_cq:i_cq + 200]
    assert "else _get_recompute_leaf_executor()" in src[i_cq:i_cq + 260]


def test_ui05r_priority_leaf_teardown_present():
    src = _fetch_state_source()
    assert src.count("_priority_leaf_executor.shutdown(wait=True, cancel_futures=True)") == 1






def test_ui05r_sweep_never_bypasses_serve_policy():
    """The sweep loads via the same prewarm worker → same strict load path →
    MODEL-04 withholding still applies (source lock)."""
    src = _fetch_state_source()
    i = src.index("def _startup_model_prewarm_sweep_worker")
    seg = src[i:i + 500]
    assert "_prewarm_inference_models_worker(t)" in seg
    assert "pickle" not in seg and "torch" not in seg  # no direct artifact loads


# ── UI_05 tail closure: market-context single-flight + stale-while-refresh ────


def _mkt_ctx_test_reset(srv, ctx=None, age_sec=0.0):
    with srv._cached_mkt_ctx_lock:
        srv._cached_mkt_ctx = ctx
        srv._cached_mkt_ctx_ts = (time.time() - age_sec) if ctx is not None else 0.0
        srv._mkt_ctx_refresh_inflight = False








