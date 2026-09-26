"""STACK-WIRE-1 — backend producer/payload cone (FIND-WIRE1-1..6)."""

from __future__ import annotations

import inspect


from live_decision_bundle import stamp_decision_bundle


def test_decision_generation_id_always_present():
    failed = {"signals_engine_failed": True}
    stamp_decision_bundle(failed)
    assert "decision_generation_id" in failed
    assert failed["decision_generation_id"] is None
    assert failed["decision_timestamp_utc"] is None
    assert failed["decision_generation_skipped"] is True
    assert failed["decision_tick_kind"] == "signals_engine_error"

    # Fail-closed contract: a bare dict missing ticker/price/release is blocked by the
    # trade-impacting gate (added after this test was written) — no decision_generation_id is
    # minted. Positive path (valid bundle + passing gates -> int decision_generation_id, tick
    # kind "live") is covered by
    # tests/test_batch2_signals_engine_error.py::test_stamp_decision_bundle_increments_on_success.
    blocked = {"signals_engine_failed": False}
    stamp_decision_bundle(blocked)
    assert blocked["decision_generation_id"] is None
    assert blocked["decision_generation_skipped"] is True
    assert blocked["decision_gate_blocked"] is True
    reasons = blocked.get("decision_gate_reasons") or []
    assert "missing_ticker" in reasons
    assert "missing_price" in reasons
    assert blocked["decision_tick_kind"] == "market_quarantine"


def test_server_build_ts_always_set():
    import server

    # Current invariant (stamp call moved upstream of _fetch_state): _fetch_state stamps the
    # build timestamp on the bundle it returns, and the ms_dict decision bundle is stamped
    # through the canonical stamper with an explicit route in the server path. We assert the
    # stable current shape, not the old single-function source ordering.
    fetch_src = inspect.getsource(server._fetch_state)
    assert 'ms_dict["_server_build_ts"] = time.time()' in fetch_src

    server_src = inspect.getsource(server)
    assert "stamp_decision_bundle(ms_dict, route=route)" in server_src


def test_stack_runtime_fields_propagate():
    import server

    ms_dict = {
        "fusion_available": True,
        "canonical_provenance": "bayesian_fusion",  # STACK-WIRE-4-CAND: tradable provenance required
        "stack_directional_authorized": True,
        "mc_available": True,
        "xgb_available": True,
        "lstm_available": False,
        "transformer_available": True,
        "fusion_contributing_models": ["xgb", "transformer"],
    }
    server._attach_stack_runtime_and_governance(ms_dict, ticker="SPY")
    rt = ms_dict["stack_runtime"]
    assert rt["fusion_active"] is True
    assert rt["mc_participated"] is True
    assert rt["n_ml_layers_live"] == 2
    assert rt["stack_mode"] in {"FULL", "INVALID"}
    assert rt["contributing_models"] == ["xgb", "transformer"]


def test_stack_runtime_fusion_active_uses_tradability_gate_not_bare_flag():
    """STACK-WIRE-4-CAND-MS-DICT-ADOPTION regression: ``fusion_available=True`` with a
    non-tradable ``canonical_provenance`` must resolve to ``fusion_active=False`` and
    ``stack_mode=INVALID`` — otherwise the Decision Command stack chip lies to the
    operator while v2 tradability is blocked.
    """
    import server

    # Split-brain case 1: canonical_forecast missing → fusion_available stays True but
    # canonical is unsafe to read as tradable.
    ms_missing = {
        "fusion_available": True,
        "canonical_provenance": "canonical_forecast_missing",
        "mc_available": True,
        "xgb_available": True,
        "lstm_available": True,
        "transformer_available": True,
    }
    server._attach_stack_runtime_and_governance(ms_missing, ticker="SPY")
    rt = ms_missing["stack_runtime"]
    assert rt["fusion_active"] is False, "tradability gate must veto fusion_active when provenance non-tradable"
    assert rt["stack_mode"] == "INVALID"

    # Split-brain case 2: empty provenance string (legacy / pre-stamp).
    ms_empty = {
        "fusion_available": True,
        "canonical_provenance": "",
        "mc_available": True,
        "xgb_available": True,
    }
    server._attach_stack_runtime_and_governance(ms_empty, ticker="SPY")
    assert ms_empty["stack_runtime"]["fusion_active"] is False
    assert ms_empty["stack_runtime"]["stack_mode"] == "INVALID"

    # Authoritative case: bayesian_fusion stays active when unified stack team scored together.
    ms_ok = {
        "fusion_available": True,
        "canonical_provenance": "bayesian_fusion",
        "mc_available": True,
        "xgb_available": True,
        "lstm_available": True,
        "transformer_available": True,
        "ml_layer_probs": {
            "xgb": {"up": 0.4, "down": 0.3, "flat": 0.3},
            "lstm": {"up": 0.4, "down": 0.3, "flat": 0.3},
            "transformer": {"up": 0.4, "down": 0.3, "flat": 0.3},
        },
        # The server no longer RE-DERIVES directional authorization from layer probs — it consumes
        # the verdict computed where composition was known. A payload without it is unauthorized,
        # so the authoritative case must now carry it.
        "stack_directional_authorized": True,
        "stack_directional_authorization_reason": "composition_complete:xgb+lstm+transformer",
    }
    server._attach_stack_runtime_and_governance(ms_ok, ticker="SPY")
    assert ms_ok["stack_runtime"]["fusion_active"] is True
    assert ms_ok["stack_runtime"]["stack_mode"] == "FULL"

    # Source-level guarantee: server keys off the contract gate, not the bare flag.
    attach_src = inspect.getsource(server._attach_stack_runtime_and_governance)
    assert "is_ms_dict_fusion_authoritative(ms_dict)" in attach_src
    assert 'bool(ms_dict.get("fusion_available"))' not in attach_src


def test_state_error_truncation_constant():
    import market_state
    import server

    assert server.STATE_ERROR_DETAIL_MAX_CHARS == 120
    ms_src = inspect.getsource(market_state.build_market_state)
    srv_src = inspect.getsource(server._logger_fetch_and_log)
    # TEST_SYSTEM_REHAB_V2: was `"[:120]" not in ms_src or "STATE_ERROR_DETAIL_MAX_CHARS"
    # in ms_src` -- the constant appearing ANYWHERE in build_market_state's source
    # (not necessarily at the truncation site) satisfied the OR, so a reintroduced
    # hardcoded `[:120]` slice sitting alongside an unrelated mention of the constant
    # would still pass. Made consistent with the strict server.py check below.
    assert "[:120]" not in ms_src, "market_state truncation reintroduced a hardcoded magic number"
    assert "[:120]" not in srv_src








def test_classify_stack_health_called_once_per_tick():
    import signals

    src = inspect.getsource(signals._compute_signals_impl)
    assert "classify_stack_health(" not in src
