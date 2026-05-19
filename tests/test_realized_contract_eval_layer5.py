"""Layer 5 realized_contract_eval.py fail-closed guards."""

from __future__ import annotations

from realized_contract_eval import (
    _chain_selection_quality_row,
    replay_max_hold_bars_from_context,
)


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
