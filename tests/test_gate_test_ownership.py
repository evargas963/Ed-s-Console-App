"""GOV-GATE-PERF-V1 Phase 3 — adversarial proofs for the staged-file ownership
selector. Every mission-required behavior: narrow selection with transitive
owners, shared-core/governance/unknown/empty → FULL_BUNDLE, selector/map/hook
self-protection, separator + deletion handling, and map-rot detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.gate_test_ownership import (
    FULL_BUNDLE,
    OWNERSHIP_MAP,
    classify_path,
    ownership_coverage_audit,
    select_owner_suites,
)


def test_known_narrow_path_selects_direct_and_transitive_owners():
    out = select_owner_suites(["realized_contract_eval.py"])
    assert out["reason"] == "KNOWN_NARROW_PATH"
    assert "tests/test_realized_contract_eval_layer5.py" in out["selection"]
    # transitive consumers (arch competition + stack-wire suites) included
    assert "tests/test_arch_competition_eval_runner.py" in out["selection"]
    assert "tests/test_stack_wire_6b_v1.py" in out["selection"]


def test_multiple_staged_files_produce_union_of_suites():
    out = select_owner_suites(["replay_hold_bars.py", "base_money_path_capture.py"])
    assert out["selection"] != FULL_BUNDLE
    assert set(out["selection"]) >= {
        "tests/test_replay_hold_bars.py",
        "tests/test_realized_contract_eval_layer5.py",
        "tests/test_base_ticker_observability.py",
    }


def test_shared_core_path_runs_full_bundle():
    for core in ("server.py", "ml_scheduler.py", "db.py"):
        out = select_owner_suites([core])
        assert out["selection"] == FULL_BUNDLE
        assert out["reason"] == "SHARED_CORE_PATH"


def test_governance_critical_path_runs_full_bundle():
    for p in ("governance/INSTITUTIONAL_CLOSURE_SCHEMA.json", "AGENTS.md", "OPEN_ITEMS.md"):
        out = select_owner_suites([p])
        assert out["selection"] == FULL_BUNDLE
        assert out["reason"] == "GOVERNANCE_CRITICAL_PATH"


def test_unknown_path_runs_full_bundle():
    out = select_owner_suites(["some_new_module_nobody_mapped.py"])
    assert out["selection"] == FULL_BUNDLE
    assert out["reason"] == "UNKNOWN_OR_AMBIGUOUS"


def test_selector_and_map_changes_run_full_bundle():
    out = select_owner_suites(["tools/gate_test_ownership.py"])
    assert out["selection"] == FULL_BUNDLE
    assert out["reason"] == "HOOK_OR_TEST_INFRA"


def test_hook_and_ci_and_test_infra_changes_run_full_bundle():
    for p in (
        ".pre-commit-config.yaml",
        ".github/workflows/hardening.yml",
        "tests/conftest.py",
        "tools/check_fix_everything_we_touch.py",
        "tools/governance_gate_cache.py",
        "tests/test_anything_at_all.py",
    ):
        out = select_owner_suites([p])
        assert out["selection"] == FULL_BUNDLE, p
        assert out["reason"] == "HOOK_OR_TEST_INFRA", p


def test_mixed_scope_narrow_plus_unknown_runs_full_bundle():
    out = select_owner_suites(["replay_hold_bars.py", "totally_unmapped.py"])
    assert out["selection"] == FULL_BUNDLE
    assert out["reason"] == "UNKNOWN_OR_AMBIGUOUS"


def test_empty_staged_scope_never_zero_tests():
    out = select_owner_suites([])
    assert out["selection"] == FULL_BUNDLE
    assert out["reason"] == "EMPTY_STAGED_SCOPE"
    out2 = select_owner_suites(["", "   "])
    assert out2["selection"] == FULL_BUNDLE


def test_deleted_and_renamed_paths_still_classify():
    # deletion of a mapped file: still narrow (its owners verify the removal)
    cls, owners = classify_path("replay_bundle_coverage.py")
    assert cls == "KNOWN_NARROW_PATH" and owners
    # deletion of an unmapped file: full bundle
    out = select_owner_suites(["deleted_legacy_module.py"])
    assert out["selection"] == FULL_BUNDLE


def test_windows_and_posix_separators_normalize_identically():
    a = select_owner_suites(["features\\replay_signal_input_v1.py"])
    b = select_owner_suites(["features/replay_signal_input_v1.py"])
    assert a["selection"] == b["selection"] != FULL_BUNDLE


def test_case_behavior_deterministic():
    # case-mismatched path does not silently match a mapped root → full bundle
    out = select_owner_suites(["Realized_Contract_Eval.py"])
    assert out["selection"] == FULL_BUNDLE
    assert out["reason"] == "UNKNOWN_OR_AMBIGUOUS"


def test_prefix_ownership_fans_out_to_shared_suites():
    out = select_owner_suites(["calibration/v2_a1_calibration.py"])
    assert out["selection"] != FULL_BUNDLE
    assert "tests/test_v2_a1_calibration.py" in out["selection"]
    assert "tests/test_a1_conformal_artifact_loader.py" in out["selection"]


def test_intentionally_omitted_owner_mapping_is_caught():
    """Map rot lock: every mapped owner suite must exist on disk."""
    assert ownership_coverage_audit() == []
    # adversarial: a fabricated map with a missing suite must be caught
    import tools.gate_test_ownership as g

    orig = dict(OWNERSHIP_MAP)
    try:
        OWNERSHIP_MAP["fabricated.py"] = ("tests/test_does_not_exist_anywhere.py",)
        errs = g.ownership_coverage_audit()
        assert errs and "test_does_not_exist_anywhere" in errs[0]
    finally:
        OWNERSHIP_MAP.clear()
        OWNERSHIP_MAP.update(orig)


def test_dependency_outside_immediate_directory_selects_affected_suites():
    """A staged features/ file selects the provenance suite that lives under
    tests/, not merely files in its own directory."""
    out = select_owner_suites(["features/db_feature_adapter.py"])
    assert out["selection"] != FULL_BUNDLE
    assert "tests/test_ml_feature_provenance.py" in out["selection"]


def test_full_bundle_classes_never_produce_partial_selection():
    for p, expected in (
        ("server.py", "SHARED_CORE_PATH"),
        ("governance/x.md", "GOVERNANCE_CRITICAL_PATH"),
        ("unknown.py", "UNKNOWN_OR_AMBIGUOUS"),
    ):
        out = select_owner_suites([p, "replay_hold_bars.py"])
        assert out["selection"] == FULL_BUNDLE, (
            f"{p}: a full-bundle class must dominate any narrow co-staged file"
        )
