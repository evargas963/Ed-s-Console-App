"""Log-only v2 post-trade attribution scaffold.

This module defines the structured close-out record required by v2.0 §20.5
without binding replay/live parity, learning, or trade authority.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

POST_TRADE_ATTRIBUTION_SCHEMA_VERSION = "1"
POST_TRADE_ATTRIBUTION_RECORD_TYPE = "v2_post_trade_attribution_close_out"

POST_TRADE_ATTRIBUTION_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "record_type",
        "created_at_utc",
        "module_id",
        "expression_profile_id",
        "close_out_record",
        "signal_contribution",
        "execution_shortfall",
        "portfolio_allocation",
        "lifecycle_action",
        "tax_impact",
        "regime_context",
        "reason_code_outcome",
        "feedback",
        "source",
    }
)


def post_trade_attribution_log_path(model_dir: Path) -> Path:
    """Return the dedicated append-only attribution log path."""
    return model_dir / "v2_decision" / "post_trade_attribution.jsonl"


def build_post_trade_attribution_record(
    *,
    ticker: str,
    trade_row: dict[str, Any] | None = None,
    module_id: str = "A",
    expression_profile_id: str = "A2",
    close_out_record: dict[str, Any] | None = None,
    signal_contribution: dict[str, Any] | None = None,
    execution_shortfall: dict[str, Any] | None = None,
    portfolio_allocation: dict[str, Any] | None = None,
    lifecycle_action: dict[str, Any] | None = None,
    tax_impact: dict[str, Any] | None = None,
    regime_context: dict[str, Any] | None = None,
    reason_code_outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a v2.0 §20.5 close-out attribution record.

    ``trade_row`` may be a row from ``realized_contract_eval.TRADE_LOG_FIELDS``.
    Runtime live-close hooks can replace this later without changing the record
    contract.
    """
    row = trade_row or {}
    close_out = _close_out_from_trade_row(ticker=ticker, module_id=module_id, expression_profile_id=expression_profile_id, row=row)
    close_out.update(close_out_record or {})

    reason_code = _reason_code_from_trade_row(row)
    reason_code.update(reason_code_outcome or {})

    record = {
        "schema_version": POST_TRADE_ATTRIBUTION_SCHEMA_VERSION,
        "record_type": POST_TRADE_ATTRIBUTION_RECORD_TYPE,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "module_id": module_id,
        "expression_profile_id": expression_profile_id,
        "close_out_record": close_out,
        "signal_contribution": signal_contribution or _placeholder_block("signal_attribution_not_implemented"),
        "execution_shortfall": execution_shortfall or _placeholder_block("execution_shortfall_not_implemented"),
        "portfolio_allocation": portfolio_allocation or _placeholder_block("portfolio_allocation_not_implemented"),
        "lifecycle_action": lifecycle_action or _lifecycle_from_trade_row(row),
        "tax_impact": tax_impact or {"status": "not_applicable", "detail": "Tax overlay is not implemented for advisory scaffold."},
        "regime_context": regime_context or _placeholder_block("regime_context_not_attached"),
        "reason_code_outcome": reason_code,
        "feedback": {
            "status": "log_only_no_learning",
            "feeds_calibration": False,
            "feeds_execution_model": False,
            "feeds_lifecycle_policy": False,
            "feeds_refit": False,
        },
        "source": {
            "classification": "presentation_only",
            "detail": "Advisory scaffold; no replay binding, learning, or trade authority.",
        },
    }
    _validate_post_trade_attribution_record(record)
    return record


def append_post_trade_attribution_record(model_dir: Path, record: dict[str, Any]) -> Path:
    """Append one validated attribution record as JSONL."""
    _validate_post_trade_attribution_record(record)
    path = post_trade_attribution_log_path(model_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
    return path


def load_recent_post_trade_attribution_records(model_dir: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    """Load recent valid-looking attribution records, newest last."""
    path = post_trade_attribution_log_path(model_dir)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            _validate_post_trade_attribution_record(record)
        except ValueError:
            continue
        out.append(record)
    return out


def _validate_post_trade_attribution_record(record: dict[str, Any]) -> None:
    missing = POST_TRADE_ATTRIBUTION_REQUIRED_KEYS - record.keys()
    if missing:
        raise ValueError(f"post-trade attribution record missing keys: {sorted(missing)}")
    if record.get("schema_version") != POST_TRADE_ATTRIBUTION_SCHEMA_VERSION:
        raise ValueError("unexpected post-trade attribution schema_version")
    if record.get("record_type") != POST_TRADE_ATTRIBUTION_RECORD_TYPE:
        raise ValueError("unexpected post-trade attribution record_type")
    for key in (
        "close_out_record",
        "signal_contribution",
        "execution_shortfall",
        "portfolio_allocation",
        "lifecycle_action",
        "tax_impact",
        "regime_context",
        "reason_code_outcome",
        "feedback",
        "source",
    ):
        if not isinstance(record.get(key), dict):
            raise ValueError(f"post-trade attribution {key} must be a dict")


def _close_out_from_trade_row(
    *,
    ticker: str,
    module_id: str,
    expression_profile_id: str,
    row: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ticker": str(row.get("ticker") or ticker).upper(),
        "module_id": module_id,
        "expression_profile_id": expression_profile_id,
        "architecture_type": row.get("architecture_type"),
        "signal_time": row.get("signal_time"),
        "entry_time": row.get("entry_time"),
        "exit_time": row.get("exit_time"),
        "option_right": row.get("right"),
        "strike": row.get("strike"),
        "expiry": row.get("expiry"),
        "contract_symbol": row.get("contract_symbol"),
        "entry_price": row.get("entry_price"),
        "exit_price": row.get("exit_price"),
        "contracts": row.get("contracts"),
        "multiplier": row.get("multiplier"),
        "pnl_dollars": row.get("pnl_dollars"),
        "pnl_percent": row.get("pnl_percent"),
        "snapshot_id_entry": row.get("snapshot_id_entry"),
        "snapshot_id_exit": row.get("snapshot_id_exit"),
    }


def _lifecycle_from_trade_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_taken": row.get("exit_reason"),
        "policy_id": None,
        "hold_bars": row.get("hold_bars"),
        "forced_exit": row.get("exit_reason") == "time_expiry",
        "pricing_entry_rule": row.get("pricing_entry_rule"),
        "pricing_exit_rule": row.get("pricing_exit_rule"),
        "path_model_used": row.get("path_model_used"),
        "same_bar_stop_target_conflict_flag": row.get("same_bar_stop_target_conflict_flag"),
        "same_bar_resolution_rule": row.get("same_bar_resolution_rule"),
    }


def _reason_code_from_trade_row(row: dict[str, Any]) -> dict[str, Any]:
    exit_reason = row.get("exit_reason")
    skipped_reason = row.get("skipped_reason")
    skipped_flag = row.get("skipped_flag")
    return {
        "exit_reason": exit_reason,
        "skipped_reason": skipped_reason,
        "skipped_flag": skipped_flag,
        "primary_outcome_code": skipped_reason or exit_reason,
    }


def _placeholder_block(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "value": None,
        "detail": "Reserved for v2.0 §20.5 attribution; log-only scaffold.",
    }
