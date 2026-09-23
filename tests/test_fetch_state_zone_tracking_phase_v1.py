"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, twelfth extracted phase.

_zone_tracking_for_state (server.py) is the Zone Tracking phase, extracted
verbatim from _fetch_state's body: derives the current zone from
consensus_summary's bias_signal/net_delta (market_state.derive_zone), then
updates the module-level `_zone_tracker` singleton's per-ticker state machine
(zone, prev_zone, since_bars_1m, since_bars_5m, last_bar_ts_1m/5m).

zone_since_bars_1m = execution-layer recency (canonical 1m bars); primary
for models/features. zone_since_bars_5m = structure-layer recency (derived
5m bars); tracked independently so there is no mixed-clock dependency.
"""
from __future__ import annotations

from types import SimpleNamespace

import server as srv


def _clean(ticker: str):
    srv._zone_tracker.pop(ticker, None)


def test_first_call_seeds_zone_and_prev_zone_identically():
    ticker = "ZZZ_ZONE_SEED"
    _clean(ticker)
    cs = SimpleNamespace(bias_signal="bull", net_delta=100.0)
    zt = srv._zone_tracking_for_state(ticker, cs)
    assert zt["zone"] == "pin_bull"
    assert zt["prev_zone"] == "pin_bull"
    assert zt["since_bars_1m"] == 0
    assert zt["since_bars_5m"] == 0
    assert srv._zone_tracker[ticker] is zt


def test_zone_change_resets_since_bars_and_records_prev_zone():
    ticker = "ZZZ_ZONE_CHANGE"
    _clean(ticker)
    srv._zone_tracking_for_state(ticker, SimpleNamespace(bias_signal="bull", net_delta=100.0))
    zt2 = srv._zone_tracking_for_state(ticker, SimpleNamespace(bias_signal="bear", net_delta=-100.0))
    assert zt2["zone"] == "pin_bear"
    assert zt2["prev_zone"] == "pin_bull"
    assert zt2["since_bars_1m"] == 0
    assert zt2["since_bars_5m"] == 0


def test_same_zone_repeated_call_does_not_change_prev_zone():
    ticker = "ZZZ_ZONE_SAME"
    _clean(ticker)
    cs = SimpleNamespace(bias_signal="balanced", net_delta=0.0)
    srv._zone_tracking_for_state(ticker, cs)
    zt2 = srv._zone_tracking_for_state(ticker, cs)
    assert zt2["zone"] == "pin_neutral"
    assert zt2["prev_zone"] == "pin_neutral"


def test_missing_consensus_summary_falls_through_to_pin_neutral_default():
    ticker = "ZZZ_ZONE_NONE"
    _clean(ticker)
    zt = srv._zone_tracking_for_state(ticker, None)
    assert zt["zone"] == "pin_neutral"


def test_fetch_state_calls_the_extracted_function_exactly_once():
    """AST lock: _fetch_state must call _zone_tracking_for_state exactly once, and must
    not directly call market_state.derive_zone itself."""
    import ast
    from pathlib import Path

    src = Path(srv.__file__).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    fetch_state_fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_fetch_state"
    )
    calls_in_fetch_state = [
        n.func.id for n in ast.walk(fetch_state_fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert calls_in_fetch_state.count("_zone_tracking_for_state") == 1
    assert "derive_zone" not in calls_in_fetch_state, (
        "_fetch_state still calls derive_zone directly -- the zone-tracking phase was "
        "not fully extracted, a second inline computation site survived"
    )
