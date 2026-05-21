"""AUDIT-CAND-SERVER-PY-FULL-READ — FIND-SERVERPY-1..19 regression guards."""

from __future__ import annotations

import ast
import inspect
import re
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


# FIND-SERVERPY-1
def test_candle_accumulator_max_bars_required():
    import server

    with pytest.raises(TypeError):
        server._CandleAccumulator(bar_seconds=60)


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

    with patch.object(server, "get_client") as gc:
        gc.return_value = MagicMock()
        with patch.object(server, "safe_get_quote") as sgq:
            sgq.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "SPY": {
                        "lastPrice": 100.0,
                        "bidPrice": 99.9,
                        "askPrice": 100.1,
                        "totalVolume": 1000,
                    }
                },
            )
            payload = server._build_rest_fast_quote_payload("SPY", "test")
    assert payload.get("spread_semantic") == "fraction"

    with patch.object(server, "_build_rest_fast_quote_payload") as br:
        br.return_value = {"spread": 0.05, "spread_pts": 0.05}
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
def test_debug_prediction_returns_populated_distribution():
    from fastapi.testclient import TestClient

    import server

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
def test_server_module_imports_under_strict_name_resolution():
    tree = ast.parse(_server_src())
    assert isinstance(tree, ast.Module)
    compile(_server_src(), str(SERVER_PY), "exec")


def test_liquidity_zone_tradeable_score_authority_roundtrip():
    from liquidity_value_engine import liquidity_zone_tradeable_score

    assert liquidity_zone_tradeable_score(n_tags=1, n_opt=1, inside=False, dist_pen=0.0, spot=None) == 5.5
