from __future__ import annotations

from v2_decision.a2_replay_labels import (
    A2_REPLAY_RAW_CHAIN_GAP_ID,
    build_a2_replay_label,
    build_a2_replay_label_artifact,
)


def _trade_row(**overrides) -> dict:
    base = {
        "architecture_type": "parallel",
        "ticker": "SPY",
        "signal_time": "2026-05-05T14:30:00Z",
        "entry_time": "2026-05-05T14:31:00Z",
        "exit_time": "2026-05-05T14:46:00Z",
        "right": "CALL",
        "strike": 500.0,
        "expiry": "2026-05-05",
        "contract_symbol": "SPY260505C00500000",
        "entry_price": 1.25,
        "exit_price": 1.55,
        "contracts": 1,
        "multiplier": 100,
        "pnl_dollars": 30.0,
        "pnl_percent": 24.0,
        "exit_reason": "target_hit",
        "hold_bars": 15,
        "skipped_flag": False,
        "skipped_reason": None,
        "snapshot_id_entry": 101,
        "snapshot_id_exit": 116,
        "pricing_entry_rule": "entry_price = ask",
        "pricing_exit_rule": "exit_price = bid",
        "path_model_used": "underlying_1m_ohlc",
        "same_bar_stop_target_conflict_flag": False,
        "same_bar_resolution_rule": None,
    }
    return {**base, **overrides}


def test_contract_clause_31_builds_contract_payoff_label_from_replay_row():
    """Contract: v2.0 §31 requires contract-level payoff labels before A2 training."""
    label = build_a2_replay_label(_trade_row())

    assert label["module_id"] == "A"
    assert label["expression_profile_id"] == "A2"
    assert label["contract_symbol"] == "SPY260505C00500000"
    assert label["entry_price"] == 1.25
    assert label["exit_price"] == 1.55
    assert label["pnl_percent"] == 24.0
    assert label["contract_profit_label"] == 1
    assert label["exit_reason"] == "target_hit"
    assert label["hold_bars"] == 15


def test_contract_clause_192_wraps_realized_eval_outputs_without_raw_chain_reads():
    """Contract: A2 contract §192 uses realized_contract_eval as source, not raw chain reads."""
    label = build_a2_replay_label(_trade_row())
    provenance = label["provenance"]

    assert provenance["source_replay"] == "realized_contract_eval"
    assert provenance["input_boundary"] == "realized_contract_eval_trade_log_row"
    assert provenance["raw_chain_consumed_by_label_scaffold"] is False
    assert provenance["input_source_classification"] == "schwab_native_normalized"
    assert provenance["upstream_raw_chain_gap"] == A2_REPLAY_RAW_CHAIN_GAP_ID


def test_contract_clause_219_label_is_registered_derived_analytic_shape():
    """Contract: A2 contract §219 names contract-profit labels as missing gap."""
    label = build_a2_replay_label(_trade_row(pnl_percent=-12.5, pnl_dollars=-15.63, exit_reason="stop_hit"))

    assert label["contract_profit_label"] == 0
    assert label["provenance"]["label_source_classification"] == "derived_because_schwab_does_not_provide"
    assert label["provenance"]["label_detail"] == "Schwab provides quote primitives but not contract-profit replay labels."


def test_contract_clause_265_artifact_is_sidecar_not_trained_model_claim():
    """Contract: A2 contract §265 requires replay labels before any trained A2 model claim."""
    artifact = build_a2_replay_label_artifact(
        [_trade_row(), _trade_row(pnl_percent=-1.0, pnl_dollars=-1.25, exit_reason="stop_hit")],
        run_id="a2-replay-label-test",
    )

    assert artifact["runtime_adapter_unchanged"] is True
    assert artifact["trained_model_claim_enabled"] is False
    assert artifact["summary"] == {
        "n_rows": 2,
        "n_labeled": 2,
        "n_skipped": 0,
        "win_rate": 0.5,
    }


def test_skipped_replay_rows_do_not_fabricate_profit_labels():
    """Contract: skipped replay rows preserve skip reason and emit no synthetic payoff label."""
    label = build_a2_replay_label(
        _trade_row(
            entry_price="",
            exit_price="",
            pnl_percent="",
            pnl_dollars="",
            exit_reason="",
            skipped_flag=True,
            skipped_reason="replay_selection_mismatch",
        )
    )

    assert label["contract_profit_label"] is None
    assert label["skip_reason"] == "replay_selection_mismatch"
    assert label["skipped_flag"] is True


def test_artifact_records_upstream_raw_chain_cleanup_gap():
    """Contract: rider 5/6 flag realized_contract_eval raw-chain reads as upstream cleanup."""
    artifact = build_a2_replay_label_artifact([_trade_row()], run_id="a2-replay-label-test")

    assert artifact["raw_chain_normalization_gap"]["id"] == A2_REPLAY_RAW_CHAIN_GAP_ID
    assert artifact["raw_chain_normalization_gap"]["status"] == "flagged_upstream_cleanup_queue"
