"""STACK-WIRE-6b — Schwab multiplier leaf + named-constant sweep (FIND-WIRE6-3..7)."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import live_decision_bundle as ldb
import realized_contract_eval as rce
from replay_bundle_coverage import REPLAY_BUNDLE_MIN_JSON_LENGTH


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_replay_bundle_min_json_length_authority_and_adoption():
    """FIND-WIRE6-5: REPLAY_BUNDLE_MIN_JSON_LENGTH authority + cross-file adoption."""
    assert REPLAY_BUNDLE_MIN_JSON_LENGTH == 10
    consumers = (
        "realized_contract_eval.py",
        "live_vs_replay_validation.py",
        "tools/measure_post_fix_theta_v1.py",
    )
    root = _repo_root()
    for rel in consumers:
        src = (root / rel).read_text(encoding="utf-8")
        assert "REPLAY_BUNDLE_MIN_JSON_LENGTH" in src, f"{rel} missing constant adoption"
        assert "length(replay_context_json) > 10" not in src, f"{rel} retains bare 10 literal (replay_context_json)"
        assert "length(option_chain_json) > 10" not in src, f"{rel} retains bare 10 literal (option_chain_json)"


def test_realized_contract_eval_named_constants_present():
    """FIND-WIRE6-3..6: module-level named constants for strike tolerances + ring buffers."""
    assert rce.STRIKE_MATCH_TOL_PENNY == 0.011
    assert rce.STRIKE_MATCH_TOL_NICKEL == 0.02
    assert rce.CHAIN_QUALITY_AUDIT_MAX_RECORDS == 5000
    assert rce.CHAIN_DEBUG_MAX_RECORDS == 200
    # FIND-WIRE6-3: OPTION_MULTIPLIER removed in favor of per-row Schwab leaf
    assert not hasattr(rce, "OPTION_MULTIPLIER"), "OPTION_MULTIPLIER constant must be removed"


def test_contract_multiplier_reads_schwab_leaf_fail_closed():
    """FIND-WIRE6-3: _contract_multiplier reads chains.*.multiplier; fail-closed on missing."""
    # Valid Schwab leaf — equity option (multiplier=100)
    assert rce._contract_multiplier({"multiplier": 100}) == 100
    # String coercion (Schwab can send as string)
    assert rce._contract_multiplier({"multiplier": "100"}) == 100
    # Mini contract (non-standard multiplier)
    assert rce._contract_multiplier({"multiplier": 10}) == 10
    # Fail-closed: missing leaf, no fabricated 100 default
    assert rce._contract_multiplier({}) is None
    assert rce._contract_multiplier({"multiplier": None}) is None
    # Fail-closed: invalid value
    assert rce._contract_multiplier({"multiplier": 0}) is None
    assert rce._contract_multiplier({"multiplier": -1}) is None
    assert rce._contract_multiplier({"multiplier": "bad"}) is None
    # Non-dict input is also fail-closed
    assert rce._contract_multiplier(None) is None  # type: ignore[arg-type]


def test_no_hardcoded_strike_tolerance_literals_in_realized_contract_eval():
    """FIND-WIRE6-4: 0.011 and 0.02 strike-match tolerance literals replaced by named constants."""
    src_find = inspect.getsource(rce._find_contract_row)
    assert "0.011" not in src_find
    assert "STRIKE_MATCH_TOL_PENNY" in src_find

    src_quality = inspect.getsource(rce._chain_selection_quality_row)
    assert re.search(r"(?<![\w.])0\.02(?![\w.])", src_quality) is None, "0.02 literal still in source"
    assert "STRIKE_MATCH_TOL_NICKEL" in src_quality

    src_expr = inspect.getsource(rce._expressions_match_live)
    assert re.search(r"(?<![\w.])0\.02(?![\w.])", src_expr) is None
    assert "STRIKE_MATCH_TOL_NICKEL" in src_expr


def test_strike_match_tol_nickel_adopted_in_live_vs_replay_validation():
    """FIND-WIRE6-4 extension: live_vs_replay_validation strike comparison uses authority constant.

    Caught by gap-closure self-audit after WIRE-6b: the L298 strike-match in
    live_vs_replay_validation.py was using bare 0.021 (inconsistent with L316/L468
    docs saying 0.02). Now uses STRIKE_MATCH_TOL_NICKEL imported from realized_contract_eval.
    """
    import live_vs_replay_validation as lvr
    src = inspect.getsource(lvr)
    assert re.search(r"(?<![\w.])0\.021(?![\w.])", src) is None, "bare 0.021 literal still present"
    assert "STRIKE_MATCH_TOL_NICKEL" in src


def test_live_decision_bundle_tick_refresh_default_constants():
    """FIND-WIRE6-7: tick-refresh spot drift thresholds named at module level."""
    assert ldb.TICK_REFRESH_SPOT_PCT_DEFAULT == 0.0003
    assert ldb.TICK_REFRESH_SPOT_ABS_DEFAULT == 0.05
    src = inspect.getsource(ldb.tick_triggers_coherent_refresh)
    # env-default strings now reference the constants, not bare numeric strings
    assert '"0.0003"' not in src
    assert '"0.05"' not in src
    assert "TICK_REFRESH_SPOT_PCT_DEFAULT" in src
    assert "TICK_REFRESH_SPOT_ABS_DEFAULT" in src
