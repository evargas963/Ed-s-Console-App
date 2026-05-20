"""Sidecar A2 replay-label artifact builder.

This module wraps realized-contract replay trade-log rows into a v2 A2 label
shape. It does not read raw option-chain contracts, wire runtime payloads, or
promote any A2 trained-model claim.
"""

from __future__ import annotations

from typing import Any


A2_REPLAY_LABEL_SCHEMA_VERSION = "1"
A2_REPLAY_LABEL_METHOD = "a2_replay_label_sidecar"
A2_REPLAY_LABEL_SOURCE_CLASSIFICATION = "derived_because_schwab_does_not_provide"
A2_REPLAY_INPUT_SOURCE_CLASSIFICATION = "schwab_native_normalized"
A2_REPLAY_RAW_CHAIN_GAP_ID = "realized_contract_eval_raw_chain_reads_pending_normalization"


def build_a2_replay_label_artifact(
    trade_rows: list[dict[str, Any]],
    *,
    run_id: str,
    source_replay: str = "realized_contract_eval",
) -> dict[str, Any]:
    """Build a sidecar A2 label artifact from replay trade-log rows."""
    labels = [build_a2_replay_label(row, source_replay=source_replay) for row in trade_rows]
    return {
        "schema_version": A2_REPLAY_LABEL_SCHEMA_VERSION,
        "method": A2_REPLAY_LABEL_METHOD,
        "run_id": run_id,
        "module_id": "A",
        "expression_profile_id": "A2",
        "source_replay": source_replay,
        "runtime_adapter_unchanged": True,
        "trained_model_claim_enabled": False,
        "raw_chain_normalization_gap": {
            "id": A2_REPLAY_RAW_CHAIN_GAP_ID,
            "status": "flagged_upstream_cleanup_queue",
            "detail": "realized_contract_eval still has raw chain reads; this sidecar consumes trade-log rows only.",
        },
        "labels": labels,
        "summary": _summary(labels),
    }


def build_a2_replay_label(
    trade_row: dict[str, Any],
    *,
    source_replay: str = "realized_contract_eval",
) -> dict[str, Any]:
    """Build one A2 replay label from an already-snapshotted trade-log row."""
    skipped_reason = _string_or_none(trade_row.get("skipped_reason"))
    skipped_flag = _bool_value(trade_row.get("skipped_flag")) or bool(skipped_reason)
    pnl_percent = _float_or_none(trade_row.get("pnl_percent"))
    pnl_dollars = _float_or_none(trade_row.get("pnl_dollars"))
    contract_profit_label = _contract_profit_label(
        skipped_flag=skipped_flag,
        pnl_percent=pnl_percent,
        pnl_dollars=pnl_dollars,
    )

    return {
        "schema_version": A2_REPLAY_LABEL_SCHEMA_VERSION,
        "method": A2_REPLAY_LABEL_METHOD,
        "module_id": "A",
        "expression_profile_id": "A2",
        "ticker": _upper_or_none(trade_row.get("ticker")),
        "contract_symbol": _string_or_none(trade_row.get("contract_symbol")),
        "option_right": _string_or_none(trade_row.get("right")),
        "strike": _float_or_none(trade_row.get("strike")),
        "expiry": _string_or_none(trade_row.get("expiry")),
        "signal_time": _string_or_none(trade_row.get("signal_time")),
        "entry_time": _string_or_none(trade_row.get("entry_time")),
        "exit_time": _string_or_none(trade_row.get("exit_time")),
        "snapshot_id_entry": trade_row.get("snapshot_id_entry"),
        "snapshot_id_exit": trade_row.get("snapshot_id_exit"),
        "entry_price": _float_or_none(trade_row.get("entry_price")),
        "exit_price": _float_or_none(trade_row.get("exit_price")),
        "pnl_dollars": pnl_dollars,
        "pnl_percent": pnl_percent,
        "contract_profit_label": contract_profit_label,
        "exit_reason": _string_or_none(trade_row.get("exit_reason")),
        "hold_bars": _int_or_none(trade_row.get("hold_bars")),
        "skip_reason": skipped_reason,
        "skipped_flag": skipped_flag,
        "pricing_entry_rule": _string_or_none(trade_row.get("pricing_entry_rule")),
        "pricing_exit_rule": _string_or_none(trade_row.get("pricing_exit_rule")),
        "path_model_used": _string_or_none(trade_row.get("path_model_used")),
        "same_bar_stop_target_conflict_flag": _bool_value(trade_row.get("same_bar_stop_target_conflict_flag")),
        "same_bar_resolution_rule": _string_or_none(trade_row.get("same_bar_resolution_rule")),
        "provenance": _provenance(source_replay),
    }


def _contract_profit_label(
    *,
    skipped_flag: bool,
    pnl_percent: float | None,
    pnl_dollars: float | None,
) -> int | None:
    if skipped_flag:
        return None
    if pnl_percent is not None:
        return 1 if pnl_percent > 0.0 else 0
    if pnl_dollars is not None:
        return 1 if pnl_dollars > 0.0 else 0
    return None


def _provenance(source_replay: str) -> dict[str, Any]:
    return {
        "source_replay": source_replay,
        "input_boundary": "realized_contract_eval_trade_log_row",
        "raw_chain_consumed_by_label_scaffold": False,
        "input_source_classification": A2_REPLAY_INPUT_SOURCE_CLASSIFICATION,
        "input_detail": "entry_price/exit_price are consumed from replay trade-log snapshots, not raw chain dicts.",
        "label_source_classification": A2_REPLAY_LABEL_SOURCE_CLASSIFICATION,
        "label_detail": "Schwab provides quote primitives but not contract-profit replay labels.",
        "upstream_raw_chain_gap": A2_REPLAY_RAW_CHAIN_GAP_ID,
    }


def _summary(labels: list[dict[str, Any]]) -> dict[str, Any]:
    labeled = [row for row in labels if row.get("contract_profit_label") is not None]
    skipped = [row for row in labels if row.get("skipped_flag") is True]
    wins = [row for row in labeled if row.get("contract_profit_label") == 1]
    return {
        "n_rows": len(labels),
        "n_labeled": len(labeled),
        "n_skipped": len(skipped),
        "win_rate": None if not labeled else round(len(wins) / len(labeled), 6),
    }


def _float_or_none(value: Any) -> float | None:
    from numeric_contract import float_finite_or_none

    return float_finite_or_none(value)


def _int_or_none(value: Any) -> int | None:
    try:
        if value is not None and value != "":
            return int(value)
    except (TypeError, ValueError):
        return None
    return None


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _string_or_none(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _upper_or_none(value: Any) -> str | None:
    text = _string_or_none(value)
    return None if text is None else text.upper()
