"""AUDIT-CAND-SERVER-PY-FULL-READ — FIND-SERVERPY-1..19 regression guards."""

from __future__ import annotations

import ast
import builtins
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER_PY = ROOT / "server.py"


def _server_src() -> str:
    return SERVER_PY.read_text(encoding="utf-8", errors="replace")


def _fn_src(name: str) -> str:
    import server

    return inspect.getsource(getattr(server, name))


def _unresolved_free_names_in_module(source: str) -> list[tuple[str, int]]:
    """Load names with no binding in module globals or enclosing function scopes."""
    tree = ast.parse(source)
    builtin_names = {n for n in dir(builtins) if not n.startswith("_")} | {
        "Exception",
        "BaseException",
        "StopIteration",
        "GeneratorExit",
        "__file__",
        "__name__",
        "__doc__",
    }
    typing_names = {
        "Any",
        "Callable",
        "Dict",
        "Iterable",
        "List",
        "Literal",
        "Mapping",
        "Optional",
        "Sequence",
        "Set",
        "Tuple",
        "Union",
    }
    globals_defined: set[str] = set(builtin_names) | typing_names

    def _add_target_names(node: ast.AST, into: set[str]) -> None:
        if isinstance(node, ast.Name):
            into.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for elt in node.elts:
                _add_target_names(elt, into)

    def _register_module_stmt(stmt: ast.stmt) -> None:
        if isinstance(stmt, ast.Try):
            for child in (*stmt.body, *stmt.orelse, *stmt.finalbody):
                _register_module_stmt(child)
            for handler in stmt.handlers:
                for child in handler.body:
                    _register_module_stmt(child)
            return
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for alias in stmt.names:
                globals_defined.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                _add_target_names(tgt, globals_defined)
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            globals_defined.add(stmt.target.id)
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            globals_defined.add(stmt.name)

    for node in tree.body:
        _register_module_stmt(node)

    class _Scope:
        __slots__ = ("names", "parent", "global_decls")

        def __init__(self, parent: _Scope | None = None) -> None:
            self.parent = parent
            self.names: set[str] = set()
            self.global_decls: set[str] = set()

        def resolve(self, name: str) -> bool:
            if name in self.names or name in self.global_decls:
                return True
            if self.parent is not None:
                return self.parent.resolve(name)
            return name in globals_defined

    def _collect_local_defs(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        local: set[str] = set()
        for arg in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs:
            local.add(arg.arg)
        if fn.args.vararg:
            local.add(fn.args.vararg.arg)
        if fn.args.kwarg:
            local.add(fn.args.kwarg.arg)
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                local.add(node.id)
            elif isinstance(node, ast.arg):
                local.add(node.arg)
            elif isinstance(node, ast.Global):
                local.update(node.names)
            elif isinstance(node, ast.Nonlocal):
                local.update(node.names)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                local.add(node.name)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                local.add(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    local.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    _add_target_names(tgt, local)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                local.add(node.target.id)
        return local

    unresolved: list[tuple[str, int]] = []

    def _check_function(fn: ast.FunctionDef | ast.AsyncFunctionDef, parent: _Scope) -> None:
        scope = _Scope(parent)
        scope.names.update(_collect_local_defs(fn))
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if not scope.resolve(node.id):
                    unresolved.append((node.id, node.lineno))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _check_function(node, _Scope())
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_scope = _Scope()
                    method_scope.names.add("self")
                    method_scope.names.update(_collect_local_defs(child))
                    for sub in ast.walk(child):
                        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                            if not method_scope.resolve(sub.id):
                                unresolved.append((sub.id, sub.lineno))

    for node in tree.body:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in globals_defined:
                unresolved.append((node.id, node.lineno))

    return unresolved


# FIND-SERVERPY-1
def test_candle_accumulator_max_bars_required():
    import server

    with pytest.raises(TypeError):
        server._CandleAccumulator(bar_seconds=60)


def test_candle_grid_stale_triggers_pricehistory_reseed():
    """Daily-scoreboard root cause (2026-06-11): background-logged tickers got one
    quote tick per ~15min visit, so the 1m grid was ~94% empty and fill_outcomes
    could never label forward bars. The grid must report stale on a gap so the
    fetch path re-seeds from the canonical Schwab pricehistory leaf — not only on
    the first visit of the server lifetime."""
    import server

    acc = server._CandleAccumulator(bar_seconds=60, max_bars=500)
    # No bars yet → stale (first-visit seed preserved).
    assert acc.grid_stale("QQQ", 10_000.0, server.CANDLE_RESEED_GAP_SECONDS)

    # Contiguous ticks → fresh grid, no re-seed churn for the active UI ticker.
    for i in range(5):
        acc.tick("QQQ", 100.0 + i, 9_600.0 + i * 60.0)
    last_end = acc.get_bars("QQQ")[-1].ts + 60.0
    assert not acc.grid_stale("QQQ", last_end + 60.0, server.CANDLE_RESEED_GAP_SECONDS)

    # 15-minute polling gap (background logger cadence) → stale → re-seed.
    assert acc.grid_stale("QQQ", last_end + 900.0, server.CANDLE_RESEED_GAP_SECONDS)

    # Fetch path wires the staleness check (not has_bars-once-per-lifetime).
    src = _server_src()
    assert "_candles_1m.grid_stale(ticker, _seed_ref_ts, CANDLE_RESEED_GAP_SECONDS)" in src
    assert "if not _candles_1m.has_bars(ticker):" not in src
    # Re-seed replaces the sparse tick grid with the canonical leaf, end to end.
    seed_bars = [
        {"datetime": (9_600.0 + i * 60.0) * 1000.0, "open": 1.0, "high": 2.0,
         "low": 0.5, "close": 1.5, "volume": 10.0}
        for i in range(20)
    ]
    acc.seed("QQQ", seed_bars)
    assert len(acc.get_bars("QQQ")) == 20
    assert acc.get_bars_source("QQQ") == "schwab_pricehistory"
    assert not acc.grid_stale("QQQ", 9_600.0 + 20 * 60.0, server.CANDLE_RESEED_GAP_SECONDS)


# FIND-SERVERPY-2
def test_filter_horizon_prob_bars_derived_from_primary_decision_horizons():
    import server
    from ml_horizon import PRIMARY_DECISION_HORIZONS

    ms = {"horizon_prob_bars": {"1m": {}, "5m": {}, "15m": {}, "60m": {}, "3c": {}}}
    server._filter_horizon_prob_bars_primary_only(ms)
    assert set(ms["horizon_prob_bars"].keys()) == server._PRIMARY_UI_HORIZON_MINUTES
    expected = frozenset(f"{int(s[:-1])}m" for s in PRIMARY_DECISION_HORIZONS)
    assert server._PRIMARY_UI_HORIZON_MINUTES == expected


# FIND-SERVERPY-3
def test_market_close_uses_market_close_hour_constant():
    src = _fn_src("_snapshot_expiry_hours_from_schwab_dte")
    assert "hour=16" not in src
    assert "MARKET_CLOSE_HOUR" in src


# FIND-SERVERPY-4
def test_rth_open_mins_constant_exists_and_used():
    import server

    assert server.RTH_OPEN_MINS == 570
    src = _fn_src("_update_rest_cum_delta")
    assert "9 * 60 + 30" not in src
    assert "RTH_OPEN_MINS" in src


# FIND-SERVERPY-5
def test_spread_semantic_stamped_on_fast_quote_and_tier_a():
    import server

    # Both quote paths now fetch via get_client() + _safe_get_quote_with_retry()
    # (production refactor). Patch both, in one shared context covering both asserts, so
    # no real Schwab/OAuth call occurs offline. The fraction-vs-dollar distinction comes
    # from the two functions (_build_rest_fast_quote_payload stamps "fraction";
    # _tier_a_live_state_dict hardcodes "dollar"), not from two quote shapes.
    _quote = MagicMock(
        status_code=200,
        json=lambda: {
            "SPY": {
                "quote": {
                    "lastPrice": 100.0,
                    "bidPrice": 99.9,
                    "askPrice": 100.1,
                    "mark": 100.0,
                    "totalVolume": 1000,
                }
            }
        },
    )
    with patch.object(server, "get_client") as gc, \
         patch.object(server, "_safe_get_quote_with_retry") as sgq:
        gc.return_value = MagicMock()
        sgq.return_value = _quote

        payload = server._build_rest_fast_quote_payload("SPY", "test")
        assert payload.get("spread_semantic") == "fraction"

        tier = server._tier_a_live_state_dict("SPY", None)
        assert tier.get("spread_semantic") == "dollar"


# FIND-SERVERPY-6
def test_price_levels_cache_sec_at_module_level():
    import server

    assert server.PRICE_LEVELS_CACHE_SEC == 15
    src = _fn_src("_fetch_state")
    assert "_PL_CACHE_SEC" not in src
    assert "PRICE_LEVELS_CACHE_SEC" in src


# FIND-SERVERPY-7
def test_l1_next_generation_regression_raises_runtime_error_not_assert():
    import server

    key = ("test-scope", "SPY")
    with server._l1_generation_lock:
        server._l1_generation[key] = 5
        server._l1_last_generation_seen[key] = 10
    with pytest.raises(RuntimeError, match="regression"):
        server._l1_next_generation(key)
    src = _fn_src("_l1_next_generation")
    assert "assert " not in src


# FIND-SERVERPY-8
def test_ed_db_bound_before_iv_rank_references():
    src = _fn_src("_fetch_state")
    ed_assign = src.index("_ed_db = get_db()")
    iv_use = src.index("if _atm_iv and _ed_db")
    assert ed_assign < iv_use


def test_iv_rank_non_none_when_atm_iv_and_db_history(monkeypatch):
    """Flow: hoisted _ed_db must be bound before IV rank block (FIND-8)."""
    import server
    from server import CANONICAL_TIMEFRAME, IV_HISTORY_LOOKBACK, compute_iv_rank

    mock_db = MagicMock()
    mock_db.get_recent_snapshots.return_value = [
        {"iv_level": 0.15 + 0.01 * i} for i in range(25)
    ]
    monkeypatch.setattr(server, "_HAS_SIGNALS", True)
    monkeypatch.setattr(server, "get_db", lambda: mock_db)

    _atm_iv = 0.25
    _ed_db = server.get_db() if server._HAS_SIGNALS else None
    _tick_ts = 1_700_000_000.0
    _iv_rank = None
    assert _ed_db is not None
    _iv_hist_rows = _ed_db.get_recent_snapshots(
        "SPY",
        CANONICAL_TIMEFRAME,
        n=IV_HISTORY_LOOKBACK,
        filled_only=False,
        as_of_ts_utc=_tick_ts,
    )
    _iv_history = [
        float(r.get("iv_level"))
        for r in _iv_hist_rows
        if r.get("iv_level") is not None and float(r.get("iv_level", 0)) > 0
    ]
    if _atm_iv and _ed_db and _tick_ts is not None and _iv_history:
        _iv_rank = compute_iv_rank(_atm_iv, _iv_history)
    assert _iv_rank is not None


# FIND-SERVERPY-9
def test_pressure_label_unavailable_when_no_dpi_or_hedging_flow():
    src = _fn_src("_fetch_state")
    assert '_pressure_label_live = "neutral"' not in src
    assert "unavailable_no_dpi_or_hedging_flow_direction" in src


# FIND-SERVERPY-11
def test_r_units_none_default_not_zero_float():
    src = _server_src()
    assert 'getattr(ms, "r_units", 0.0)' not in src
    assert 'getattr(ms, \'r_units\', 0.0)' not in src


# FIND-SERVERPY-12
def test_no_mc_em_pre_bms_warning_log():
    assert "MC_EM_PRE_BMS" not in _server_src()


# FIND-SERVERPY-13
def test_recent_crosses_uses_named_constant():
    import server

    assert server.RECENT_CROSSES_DISPLAY_LIMIT == 5
    assert "RECENT_CROSSES_DISPLAY_LIMIT" in _fn_src("_fetch_state")


# FIND-SERVERPY-14
def test_no_underscore_json_references():
    src = _server_src()
    assert "_json.loads" not in src
    assert "_json.dumps" not in src


# FIND-SERVERPY-15
def test_stack_mode_value_is_authority_only():
    src = _server_src()
    assert 'sr["stack_mode"] = "signals_engine_error"' not in src
    assert 'sr["signals_engine_failed"] = True' in src
    attach = _fn_src("_attach_stack_runtime_and_governance")
    assert "classify_stack_health" in attach


# FIND-SERVERPY-17
def test_prediction_override_rejects_empty_direction():
    from fastapi.testclient import TestClient

    import server

    client = TestClient(server.app)
    r = client.post("/api/prediction/override?ticker=SPY&direction=")
    assert r.status_code == 400


# FIND-SERVERPY-18
def test_tradeable_score_calls_liquidity_engine_authority():
    src = _fn_src("_liquidity_zone_tradeable_fields")
    assert "liquidity_zone_tradeable_score" in src
    assert "3.0 * len(tags)" not in src


# FIND-SERVERPY-19
def test_debug_prediction_returns_populated_distribution(monkeypatch):
    from fastapi.testclient import TestClient

    import server

    # /api/debug/prediction is fail-closed gated (R-011): it 404s unless
    # ED_ALLOW_DEBUG_ENDPOINTS is enabled. Enable it for this test only
    # (monkeypatch auto-reverts) — the production gate is unchanged.
    monkeypatch.setenv("ED_ALLOW_DEBUG_ENDPOINTS", "1")

    client = TestClient(server.app)
    with patch.object(server, "_fetch_state") as fs:
        fs.return_value = {
            "zone": "pin_bull",
            "vwap_side": "above",
            "bias_signal": "neutral",
            "pin_strength": 0.5,
            "net_delta": 0,
            "net_gamma": 0,
            "gex_magnitude": 0,
            "dex_magnitude": 0,
            "samples_used": 1,
            "model_note": "test",
            "session_bucket": "RTH",
            "vix_bucket": "low",
        }
        with patch.object(server, "get_db") as gdb:
            gdb.return_value = MagicMock(
                get_zone_distribution=MagicMock(return_value={"pin_bull": 3})
            )
            r = client.get("/api/debug/prediction?ticker=SPY")
    assert r.status_code == 200
    body = r.json()
    assert "error" not in body
    assert body.get("db_zone_distribution") == {"pin_bull": 3}


# FIND-SERVERPY-20 / cross-cutting
def test_server_module_imports_with_strict_name_resolution():
    src = _server_src()
    tree = ast.parse(src)
    assert isinstance(tree, ast.Module)
    compile(src, str(SERVER_PY), "exec")
    import server  # noqa: F401

    unresolved = _unresolved_free_names_in_module(src)
    assert unresolved == [], f"unresolved free names: {unresolved[:20]}"


def test_liquidity_zone_tradeable_score_authority_roundtrip():
    from liquidity_value_engine import liquidity_zone_tradeable_score

    assert liquidity_zone_tradeable_score(n_tags=1, n_opt=1, inside=False, dist_pen=0.0, spot=None) == 5.5


def test_vwap_failed_log_demoted_to_debug_for_index_symbols():
    """Operator scan flagged: 'WARNING: VWAP failed for $SPX: price_levels=None bars=390 — writing NULL'.

    Schwab index symbols ($SPX, $VIX, $NDX) don't carry intraday volume data;
    VWAP can't compute by definition → steady-state DEBUG, not WARNING. Real
    ticker (SPY etc.) with bars-present + VWAP-failed remains WARNING (data
    quality issue).
    """
    from pathlib import Path

    # RC-371 re-anchor: Phase 2A deleted the second VWAP implementation ALONG WITH its
    # 'VWAP failed for' log site — the WARN-spam this test suppressed cannot recur
    # because the block no longer exists. The lock now holds two things: the deleted
    # log site stays deleted, and the one-VWAP deletion record remains in place.
    src = Path(__file__).resolve().parents[1].joinpath("server.py").read_text(encoding="utf-8")
    assert "VWAP failed for" not in src, (
        "the deleted VWAP-failed log block is back in server.py — a second VWAP "
        "path (and its index-symbol WARN spam) is reopening"
    )
    assert "It was a second, independent VWAP implementation" in src, (
        "the Phase 2A one-VWAP deletion record left server.py — re-derive where the "
        "VWAP authority lives before trusting this lock"
    )
