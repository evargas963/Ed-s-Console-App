#!/usr/bin/env python3
"""Staged-file test-ownership selector (GOV-GATE-PERF-V1 Phases 2-3).

Maps staged repository paths to the owner test suites that must run before a
commit. Fail-safe by construction: any path that is unknown, ambiguous, or
touches the selector/map/hooks/test-infrastructure selects the FULL bundle —
the selector can only ever ADD precision, never subtract coverage. The remote
required CI (Pytest Full Suite) is untouched and remains the final authority.

Classes (mission contract):
  KNOWN_NARROW_PATH        → union of direct + transitive owner suites
  SHARED_CORE_PATH         → full bundle (fan-out too broad to enumerate safely)
  GOVERNANCE_CRITICAL_PATH → full governance bundle (= full bundle here)
  UNKNOWN_OR_AMBIGUOUS     → full bundle
  SELECTOR_OR_MAP_CHANGED  → full bundle (self-protection)
  HOOK_OR_TEST_INFRA       → full bundle (self-protection)
  EMPTY_STAGED_SCOPE       → full bundle (an empty scope must never mean zero tests)

Usage:
  python tools/gate_test_ownership.py --staged        # print suites for staged files
  python tools/gate_test_ownership.py --coverage      # ownership coverage audit
  python tools/gate_test_ownership.py --classify P... # classify explicit paths
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

FULL_BUNDLE = "FULL_BUNDLE"

# Self-protection surfaces: any change here runs everything.
SELF_PROTECTED_PATHS: tuple[str, ...] = (
    "tools/gate_test_ownership.py",
    "tools/governance_gate_cache.py",
    # (check_fix_everything_we_touch.py and enforce_all_rules.py were retired with
    # their stacks — removed from this set 2026-08-25, audit round 2.)
    "tools/check_institutional_closure_gate.py",
    # RC-505: the rehabilitation ratchet and its negative controls. Tests are not CHECKS, so
    # nothing noticed the suite being deleted or gutted — after which the ratchet's predicates
    # could be weakened freely while pytest-full still passed a suite that tested nothing.
    "tools/repo_rehab_status.py",
    "tests/test_repo_rehab_ratchet_v1.py",
    ".pre-commit-config.yaml",
    "tests/conftest.py",
    "pyproject.toml",
    "pytest.ini",
)
SELF_PROTECTED_PREFIXES: tuple[str, ...] = (
    ".github/",
)

# Governance-critical prefixes: full governance bundle (= full bundle).
GOVERNANCE_CRITICAL_PREFIXES: tuple[str, ...] = (
    "governance/",
    "docs/governance/",
)
GOVERNANCE_CRITICAL_EXACT: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    "OPEN_ITEMS.md",
    "ACTIVE_PROGRAM.md",
)

# Shared-core modules: imported so widely that narrow selection is unsafe.
SHARED_CORE_EXACT: tuple[str, ...] = (
    "server.py",
    "db.py",
    "market_state.py",
    "ml_scheduler.py",
    "ml_predict.py",
    "ml_train.py",
    "training_cache.py",
    "signal_types.py",
    "governed_stack_contract.py",
    "timeframe_config.py",
    "ml_horizon.py",
)

# Known-narrow ownership: path (exact or prefix ending in '/') → owner suites.
# Transitive owners are listed explicitly — the map is data, not inference.
OWNERSHIP_MAP: dict[str, tuple[str, ...]] = {
    "realized_contract_eval.py": (
        "tests/test_realized_contract_eval_layer5.py",
        "tests/test_arch_competition_eval_runner.py",
        "tests/test_stack_wire_6b_v1.py",
        "tests/test_stack_wire_6c_v1.py",
    ),
    "replay_hold_bars.py": (
        "tests/test_replay_hold_bars.py",
        "tests/test_realized_contract_eval_layer5.py",
    ),
    "replay_bundle_coverage.py": (
        "tests/test_realized_contract_eval_layer5.py",
    ),
    "lifecycle_rule_core.py": (
        "tests/test_realized_contract_eval_layer5.py",
    ),
    "base_money_path_capture.py": (
        "tests/test_base_ticker_observability.py",
    ),
    "model_serve_policy.py": (
        "tests/test_model_serve_policy.py",
    ),
    "vol_observability.py": (
        "tests/test_volatility_regime_fail_closed.py",
    ),
    "features/": (
        "tests/test_ml_feature_provenance.py",
        "tests/test_replay_signal_input_v1.py",
    ),
    "calibration/": (
        "tests/test_v2_a1_calibration.py",
        "tests/test_a1_conformal_artifact_loader.py",
        "tests/test_fusion_temperature_calibration.py",
        "tests/test_v2_advisory_backfill.py",
    ),
    "arch_competition/": (
        "tests/test_arch_competition_eval_runner.py",
        "tests/test_arch_competition_auto_promote.py",
    ),
    "static/": (
        "tests/test_card_wiring_transport_locks.py",
    ),
    "templates/": (
        "tests/test_card_wiring_transport_locks.py",
    ),
}


def _norm(path: str) -> str:
    """Normalize separators + strip; keep case as-is but compare deterministically.

    Only a literal leading "./" is removed — charset lstrip would mangle
    dotfiles (".pre-commit-config.yaml" must stay a dotfile).
    """
    p = path.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p


def classify_path(path: str) -> tuple[str, tuple[str, ...]]:
    """Return (classification, owner_suites). FULL_BUNDLE surfaces empty suites."""
    p = _norm(path)
    if not p:
        return "UNKNOWN_OR_AMBIGUOUS", ()
    if p in SELF_PROTECTED_PATHS or any(p.startswith(x) for x in SELF_PROTECTED_PREFIXES):
        return "HOOK_OR_TEST_INFRA", ()
    if p.startswith("tests/"):
        # A test file is its own owner AND may guard shared behavior — run full.
        return "HOOK_OR_TEST_INFRA", ()
    if p in GOVERNANCE_CRITICAL_EXACT or any(p.startswith(x) for x in GOVERNANCE_CRITICAL_PREFIXES):
        return "GOVERNANCE_CRITICAL_PATH", ()
    if p in SHARED_CORE_EXACT:
        return "SHARED_CORE_PATH", ()
    if p in OWNERSHIP_MAP:
        return "KNOWN_NARROW_PATH", OWNERSHIP_MAP[p]
    for prefix, suites in OWNERSHIP_MAP.items():
        if prefix.endswith("/") and p.startswith(prefix):
            return "KNOWN_NARROW_PATH", suites
    return "UNKNOWN_OR_AMBIGUOUS", ()


def select_owner_suites(staged: list[str]) -> dict:
    """Selection for a staged set. Any full-bundle class anywhere → FULL_BUNDLE."""
    normalized = [_norm(s) for s in staged if _norm(s)]
    if not normalized:
        return {
            "selection": FULL_BUNDLE,
            "reason": "EMPTY_STAGED_SCOPE",
            "classifications": {},
        }
    classifications: dict[str, str] = {}
    suites: set[str] = set()
    full_reason: str | None = None
    for p in normalized:
        cls, owners = classify_path(p)
        classifications[p] = cls
        if cls == "KNOWN_NARROW_PATH":
            suites.update(owners)
        else:
            full_reason = full_reason or cls
    if full_reason is not None:
        return {
            "selection": FULL_BUNDLE,
            "reason": full_reason,
            "classifications": classifications,
        }
    if not suites:
        return {
            "selection": FULL_BUNDLE,
            "reason": "NO_MATCH",
            "classifications": classifications,
        }
    return {
        "selection": sorted(suites),
        "reason": "KNOWN_NARROW_PATH",
        "classifications": classifications,
    }


def ownership_coverage_audit() -> list[str]:
    """Every tracked production/governance .py must classify into a named class
    (KNOWN_NARROW via map, SHARED_CORE, GOVERNANCE_CRITICAL, self-protected) or
    deliberately fall to UNKNOWN→FULL_BUNDLE. UNKNOWN is fail-safe, so the audit
    reports counts rather than failing on breadth; it FAILS only if a mapped
    owner suite file does not exist (map rot)."""
    errors: list[str] = []
    for suites in OWNERSHIP_MAP.values():
        for s in suites:
            if not (REPO_ROOT / s).is_file():
                errors.append(f"ownership map rot: owner suite missing on disk: {s}")
    return errors


def _git_staged() -> list[str]:
    r = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRD"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
    )
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def main(argv: list[str]) -> int:
    if "--coverage" in argv:
        errs = ownership_coverage_audit()
        if errs:
            print("\n".join(errs))
            return 1
        print(f"ownership coverage: {len(OWNERSHIP_MAP)} mapped roots, all owner suites exist")
        return 0
    if "--classify" in argv:
        paths = argv[argv.index("--classify") + 1:]
        print(json.dumps(select_owner_suites(paths), indent=2))
        return 0
    out = select_owner_suites(_git_staged())
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
