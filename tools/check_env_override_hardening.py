#!/usr/bin/env python3
"""Inventory and gate high-impact ED_* environment overrides — Phase 3E."""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ART = REPO_ROOT / "governance" / "artifacts"
INVENTORY_PATH = ART / "ENV_OVERRIDE_INVENTORY.json"

# classification: safe_runtime_config | test_only | debug_only | production_dangerous | governance_sensitive
ENV_OVERRIDE_INVENTORY: dict[str, dict[str, str]] = {
    "ED_ALLOW_DEBUG_ENDPOINTS": {
        "classification": "production_dangerous",
        "description": "Enables debug HTTP endpoints including R-011 path",
    },
    "ED_CONSOLE_ALLOW_PRED_OVERRIDE": {
        "classification": "production_dangerous",
        "description": "Allows prediction override without registry discipline",
    },
    "ED_CONSOLE_ALLOW_NONCANONICAL_DB": {
        "classification": "test_only",
        "description": "CI/test non-canonical DB path",
    },
    "ED_DISABLE_STARTUP_ANALYTICS_WARM": {
        "classification": "debug_only",
        "description": "Skips startup analytics warm — test/dev only",
    },
    "ED_NON_PRODUCTION_MODE": {
        "classification": "safe_runtime_config",
        "description": "Explicit opt-in to allow dangerous flags in non-prod",
    },
    "ED_SERVING_PROCESS": {
        "classification": "safe_runtime_config",
        "description": "Marks live serving process for production checks",
    },
    "ED_ABLATION_SCORING_PASS": {
        "classification": "test_only",
        "description": "Offline ablation scoring path",
    },
    "ED_DISABLE_AUTO_PROMOTE": {
        "classification": "governance_sensitive",
        "description": "Disables scheduler auto-promote",
    },
    "ED_SCHEDULER_AUTO_PROMOTE": {
        "classification": "governance_sensitive",
        "description": "Scheduler promotion toggle",
    },
    "ED_LIVE_SNAPSHOT_MATERIALIZE": {
        "classification": "debug_only",
        "description": "Live snapshot normalized materialize on fetch path",
    },
    "ED_MH_EMPIRICAL_SUPPORT": {
        "classification": "governance_sensitive",
        "description": "Empirical blend on cards — must stay 0.0 in production",
    },
    "ED_SIGNAL_LAYER_FUSION_BLEND": {
        "classification": "governance_sensitive",
        "description": "Signal-layer fusion blend — must stay 0.0 default",
    },
    "ED_LIVE_ABLATION_EXPERIMENT": {
        "classification": "test_only",
        "description": "Pre-train card observe from parallel models",
    },
    "ED_BUILD_GENERATION": {
        "classification": "test_only",
        "description": "Release/build generation pin for tests",
    },
    "ED_GATE_MAX_SPREAD_AGE_MS": {
        "classification": "safe_runtime_config",
        "description": "Trade-impacting gate spread age threshold",
    },
    "ED_VIEWER_STATE_CACHE_TTL_SEC": {
        "classification": "safe_runtime_config",
        "description": "Tier C cache TTL",
    },
    "ED_TICK_REFRESH_SPOT_PCT": {
        "classification": "safe_runtime_config",
        "description": "Tick coherent refresh spot percent threshold",
    },
    "ED_TICK_REFRESH_SPOT_ABS": {
        "classification": "safe_runtime_config",
        "description": "Tick coherent refresh spot absolute threshold",
    },
}

PRODUCTION_DANGEROUS = frozenset(
    k for k, v in ENV_OVERRIDE_INVENTORY.items() if v["classification"] == "production_dangerous"
)
GOVERNANCE_SENSITIVE = frozenset(
    k for k, v in ENV_OVERRIDE_INVENTORY.items() if v["classification"] == "governance_sensitive"
)


def is_production_serving_context() -> bool:
    if os.environ.get("CI", "").strip().lower() in ("1", "true", "yes"):
        return False
    if os.environ.get("ED_NON_PRODUCTION_MODE", "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return os.environ.get("ED_SERVING_PROCESS", "").strip().lower() in ("1", "true", "yes", "on")


def active_env_overrides() -> dict[str, str]:
    return {k: os.environ[k] for k in ENV_OVERRIDE_INVENTORY if k in os.environ and os.environ[k] != ""}


def build_env_override_inventory_artifact() -> dict:
    active = active_env_overrides()
    high_risk_active = [
        k
        for k in active
        if ENV_OVERRIDE_INVENTORY[k]["classification"] in ("production_dangerous", "governance_sensitive")
    ]
    return {
        "schema_version": 1,
        "artifact": str(INVENTORY_PATH.relative_to(REPO_ROOT)).replace("\\", "/"),
        "inventory_count": len(ENV_OVERRIDE_INVENTORY),
        "high_risk_count": len(PRODUCTION_DANGEROUS | GOVERNANCE_SENSITIVE),
        "active_overrides": active,
        "high_risk_active": high_risk_active,
        "production_serving_context": is_production_serving_context(),
        "entries": [
            {"name": k, **v} for k, v in sorted(ENV_OVERRIDE_INVENTORY.items())
        ],
    }


def run_env_override_hardening_check() -> list[str]:
    errors: list[str] = []
    if not is_production_serving_context():
        return errors
    for name in PRODUCTION_DANGEROUS:
        val = os.environ.get(name, "").strip().lower()
        if val in ("1", "true", "yes", "on"):
            errors.append(
                f"{name}=1 in production serving context without ED_NON_PRODUCTION_MODE — blocked"
            )
    for name in GOVERNANCE_SENSITIVE:
        val = os.environ.get(name, "").strip().lower()
        if name == "ED_MH_EMPIRICAL_SUPPORT" and val not in ("", "0", "0.0"):
            errors.append(f"{name} must be 0.0 in production serving context (got {os.environ.get(name)!r})")
        if name == "ED_SIGNAL_LAYER_FUSION_BLEND" and val not in ("", "0", "0.0"):
            errors.append(f"{name} must be 0.0 in production serving context (got {os.environ.get(name)!r})")
        if name in ("ED_DISABLE_AUTO_PROMOTE", "ED_SCHEDULER_AUTO_PROMOTE") and val in ("0", "false", "no", "off"):
            errors.append(f"{name} disables auto-promote in production serving context")
    artifact = ART / "ENV_OVERRIDE_INVENTORY.json"
    if not artifact.is_file():
        errors.append(f"{artifact.relative_to(REPO_ROOT)}: missing — run tools/_build_institutional_audit_phase3e.py")
    return errors


def main() -> int:
    errors = run_env_override_hardening_check()
    if errors:
        for e in errors:
            print(f"check_env_override_hardening: FAIL — {e}", file=sys.stderr)
        return 1
    print("check_env_override_hardening: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
