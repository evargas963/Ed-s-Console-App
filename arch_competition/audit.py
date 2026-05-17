"""Append-only audit log for manual architecture governance actions."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)

AUDIT_RECORD_SCHEMA_VERSION = "1"

AUDIT_ACTION = Literal[
    "manual_promote_attempt",
    "manual_promote_success",
    "manual_promote_failure",
    "rollback_attempt",
    "rollback_success",
    "rollback_failure",
]

# Stable field set for consumers (additive fields require schema bump).
AUDIT_RECORD_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "action",
        "outcome",
        "timestamp_utc",
        "operator_id",
        "ticker",
        "ml_horizon_suffix",
        "prior_active_architecture",
        "target_architecture",
        "new_active_architecture",
        "evaluation_manifest_path",
        "promotion_decision_path",
        "checkpoint_id",
        "detail",
    }
)


def governance_audit_log_path(model_dir: Path) -> Path:
    return model_dir / "arch_competition" / "governance_audit.jsonl"


def append_audit_record(model_dir: Path, record: dict[str, Any]) -> Path:
    """Append one JSON line; creates parent dirs."""
    missing = AUDIT_RECORD_REQUIRED_KEYS - record.keys()
    if missing:
        raise ValueError(f"audit record missing keys: {sorted(missing)}")
    path = governance_audit_log_path(model_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
    return path


def load_recent_audit_records(model_dir: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    path = governance_audit_log_path(model_dir)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            log.warning("governance audit log line corrupted (skipped): %s", exc)
            continue
    return out


def build_audit_record(
    *,
    action: str,
    outcome: str,
    operator_id: str,
    ticker: str,
    ml_horizon_suffix: str,
    prior_active_architecture: str | None,
    target_architecture: str | None,
    new_active_architecture: str | None,
    evaluation_manifest_path: str | None,
    promotion_decision_path: str | None,
    checkpoint_id: str | None,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": AUDIT_RECORD_SCHEMA_VERSION,
        "action": action,
        "outcome": outcome,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "operator_id": operator_id,
        "ticker": ticker.upper(),
        "ml_horizon_suffix": str(ml_horizon_suffix).lower(),
        "prior_active_architecture": prior_active_architecture,
        "target_architecture": target_architecture,
        "new_active_architecture": new_active_architecture,
        "evaluation_manifest_path": evaluation_manifest_path,
        "promotion_decision_path": promotion_decision_path,
        "checkpoint_id": checkpoint_id,
        "detail": detail,
    }
