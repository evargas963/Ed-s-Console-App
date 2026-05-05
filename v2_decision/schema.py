"""Schema guardrails for the draft v2 decision object.

The contract is "complete in structure, honest in substance": every leaf
decision field carries a source indicator so the UI can show the target v2 shape
without implying unbuilt components are live.
"""

from __future__ import annotations

from typing import Any


SCHEMA_VERSION = "v2.0-draft"
V2_STATUS = "target_architecture_pending_governance_binding"
ALLOWED_SOURCE_INDICATORS = frozenset(
    {
        "v2_compliant",
        "v1_approximation",
        "not_implemented",
        "policy_object_pending",
    }
)

REQUIRED_TOP_LEVEL_KEYS = (
    "schema_version",
    "v2_status",
    "authority",
    "strategy_module",
    "expression_profile",
    "decision",
    "edge_domains",
    "trace",
    "conformance_gaps",
)

LEAF_FIELD_REQUIRED_KEYS = ("value", "source")


class V2DecisionSchemaError(ValueError):
    """Raised when a v2 decision payload violates the draft schema."""


def leaf(value: Any, source: str, *, detail: str | None = None) -> dict[str, Any]:
    """Build a source-indicated leaf field."""
    if source not in ALLOWED_SOURCE_INDICATORS:
        raise V2DecisionSchemaError(f"invalid source indicator: {source!r}")
    out: dict[str, Any] = {"value": value, "source": source}
    if detail:
        out["detail"] = detail
    return out


def validate_v2_decision(decision: dict[str, Any]) -> None:
    """Validate the structural Pilot 1A v2 decision contract."""
    if not isinstance(decision, dict):
        raise V2DecisionSchemaError("v2_decision must be a dict")

    missing = [k for k in REQUIRED_TOP_LEVEL_KEYS if k not in decision]
    if missing:
        raise V2DecisionSchemaError(f"missing top-level keys: {missing}")

    if decision.get("schema_version") != SCHEMA_VERSION:
        raise V2DecisionSchemaError("unexpected schema_version")
    if decision.get("v2_status") != V2_STATUS:
        raise V2DecisionSchemaError("unexpected v2_status")

    _validate_authority(decision.get("authority"))
    _walk_leaf_fields(decision)


def _validate_authority(authority: Any) -> None:
    if not isinstance(authority, dict):
        raise V2DecisionSchemaError("authority must be a dict")
    if authority.get("mode") != "advisory_non_authoritative":
        raise V2DecisionSchemaError("authority.mode must be advisory_non_authoritative")
    if authority.get("tier") != "C_analytics_only":
        raise V2DecisionSchemaError("authority.tier must be C_analytics_only")
    if authority.get("changes_trade_behavior") is not False:
        raise V2DecisionSchemaError("authority.changes_trade_behavior must be false")


def _walk_leaf_fields(obj: Any, path: str = "v2_decision") -> None:
    if isinstance(obj, dict):
        if set(LEAF_FIELD_REQUIRED_KEYS).issubset(obj.keys()):
            _validate_leaf(obj, path)
            return
        for key, value in obj.items():
            _walk_leaf_fields(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            _walk_leaf_fields(value, f"{path}[{idx}]")


def _validate_leaf(obj: dict[str, Any], path: str) -> None:
    source = obj.get("source")
    if source not in ALLOWED_SOURCE_INDICATORS:
        raise V2DecisionSchemaError(f"{path}.source invalid: {source!r}")

