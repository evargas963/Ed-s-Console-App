"""Layer 5 realized_contract_eval.py fail-closed guards."""

from __future__ import annotations

import inspect

import realized_contract_eval as rce
from realized_contract_eval import _chain_selection_quality_row
from replay_hold_bars import replay_max_hold_bars_from_context


def test_replay_max_hold_bars_from_context_requires_explicit_value():
    assert replay_max_hold_bars_from_context({}) is None
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": None}) is None
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": 0}) is None
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": "bad"}) is None


def test_replay_max_hold_bars_from_context_accepts_valid_and_caps():
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": 15}) == 15
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": 500}) == 390


def test_chain_selection_quality_ignores_ranked_rows_without_strike():
    row = _chain_selection_quality_row(
        ticker="SPY",
        architecture_type="parallel",
        signal_time="2026-05-05T10:00:00",
        selected_strike=500.0,
        put_call="CALL",
        ranked_top5=[
            {"strike": None, "composite_score": 99.0},
            {"strike": 501.0, "composite_score": 8.0},
        ],
        selected_pnl=10.0,
        symbol_hint=None,
        entry_chain=[],
        exit_chain=[],
    )
    assert row["alt_1"] is None or row["alt_1"]["strike"] != 0.0


def test_chain_selection_quality_best_score_ignores_none_scores():
    row = _chain_selection_quality_row(
        ticker="SPY",
        architecture_type="parallel",
        signal_time="2026-05-05T10:00:00",
        selected_strike=500.0,
        put_call="CALL",
        ranked_top5=[
            {"strike": 500.0, "composite_score": None},
            {"strike": 501.0, "composite_score": 7.5},
        ],
        selected_pnl=5.0,
        symbol_hint=None,
        entry_chain=[],
        exit_chain=[],
    )
    assert row["score_gap_vs_best"] is None


def test_forward_path_bars_converted_to_dict_before_simulate_exit():
    """Big-audit regression: _forward_path_rows returns sqlite3.Row objects, but
    _simulate_exit → lifecycle_rule_core.fire_exit → _bar_value uses .get() which
    sqlite3.Row does not support. The integration path requires dict-conversion
    at the boundary. Without this conversion the entire historical evaluation
    crashes with AttributeError on the very first bar.
    """
    src = inspect.getsource(rce.evaluate_realized_contract_trades_for_rows)
    assert "[dict(r) for r in _forward_path_rows" in src, (
        "bars must be converted to dict before passing to _simulate_exit; "
        "see lifecycle_rule_core._bar_value which uses .get()"
    )


def test_chain_selection_quality_best_score_with_all_negative_real_scores():
    """None scores must not sort as 0 and beat negative composite scores."""
    row = _chain_selection_quality_row(
        ticker="SPY",
        architecture_type="parallel",
        signal_time="2026-05-05T10:00:00",
        selected_strike=502.0,
        put_call="CALL",
        ranked_top5=[
            {"strike": 500.0, "composite_score": None},
            {"strike": 501.0, "composite_score": -2.0},
            {"strike": 502.0, "composite_score": -10.0},
        ],
        selected_pnl=5.0,
        symbol_hint=None,
        entry_chain=[],
        exit_chain=[],
    )
    # best real score is -2.0 at 501, not None-as-0; gap vs selected -10.0 at 502
    assert row["score_gap_vs_best"] == round(-2.0 - (-10.0), 4)
