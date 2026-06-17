"""Performance / scope tests for check_fix_everything_we_touch pre-commit path."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import check_fix_everything_we_touch as mod  # noqa: E402
from fix_everything_we_touch_scope import (  # noqa: E402
    compute_cache_invalidation_sha256,
    is_governance_critical_commit,
    load_disk_cache,
    resolve_precommit_check_funcs,
    save_disk_cache,
)


def test_normal_staged_change_does_not_require_full_repo_wide():
    staged = {"market_state.py"}
    funcs = resolve_precommit_check_funcs(mod._REPO_WIDE_STATIC_CHECK_FUNCS, staged=staged)
    assert len(funcs) < len(mod._REPO_WIDE_STATIC_CHECK_FUNCS)
    assert "check_precommit_performance_contract" in funcs


def test_governance_critical_staged_runs_all_repo_wide():
    staged = {"tools/check_fix_everything_we_touch.py", "governance/README.md"}
    assert is_governance_critical_commit(staged)
    funcs = resolve_precommit_check_funcs(mod._REPO_WIDE_STATIC_CHECK_FUNCS, staged=staged, full_static=False)
    assert funcs == mod._REPO_WIDE_STATIC_CHECK_FUNCS


def test_agents_change_expands_agent_preload_checks():
    staged = {"AGENTS.md"}
    funcs = resolve_precommit_check_funcs(mod._REPO_WIDE_STATIC_CHECK_FUNCS, staged=staged)
    assert "check_agent_preload_contract" in funcs


def test_money_path_staged_includes_fusion_contract():
    staged = {"static/index.html"}
    funcs = resolve_precommit_check_funcs(mod._REPO_WIDE_STATIC_CHECK_FUNCS, staged=staged)
    assert "check_fusion_only_card_contract" in funcs


def test_cache_invalidation_changes_when_lock_set_changes():
    inv_a = compute_cache_invalidation_sha256(mod._REPO_WIDE_STATIC_CHECK_FUNCS)
    extended = mod._REPO_WIDE_STATIC_CHECK_FUNCS + ("check_precommit_performance_contract",)
    inv_b = compute_cache_invalidation_sha256(extended)
    assert inv_a != inv_b


def test_cache_roundtrip(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr("tools.fix_everything_we_touch_scope.CACHE_PATH", cache_path)
    payload = {
        "schema_version": 1,
        "invalidation_sha256": "abc",
        "checkers": {"check_external_rule_tools_wired": {"ok": True, "errors": []}},
    }
    save_disk_cache(payload)
    loaded = load_disk_cache()
    assert loaded is not None
    assert loaded["invalidation_sha256"] == "abc"


def test_security_by_design_still_allowed_in_staged_scan():
    line = '        ("T1-09", "Security by design"),'
    hits = mod._line_rule_drift_hits(REPO / "tools/_build_governance_coverage_matrix.py", 55, line)
    assert hits == []


def test_full_static_flag_runs_all_checks(monkeypatch):
    staged = {"market_state.py"}
    seen: list[str] = []

    def fake_run(*, staged=None, full_static=False, profile=None, use_cache=True):
        seen.append(str(full_static))
        return []

    monkeypatch.setattr(mod, "_run_repo_wide_static_check_funcs", fake_run)
    mod.check_paths([], staged=staged, full_static=True)
    assert seen == ["True"]


def test_objective_audit_uses_full_static_not_cache(monkeypatch):
    calls: list[dict] = []

    def capture(*, staged=None, full_static=False, profile=None, use_cache=True):
        calls.append({"full_static": full_static, "use_cache": use_cache})
        return []

    monkeypatch.delenv("ED_PYTEST_REUSE_STATIC_AUDIT", raising=False)
    mod.reset_session_static_audit_cache_for_tests()
    monkeypatch.setattr(mod, "_run_repo_wide_static_check_funcs", capture)
    mod.run_repo_wide_static_audit(staged=set())
    assert calls == [{"full_static": True, "use_cache": False}]


def test_pytest_session_static_audit_cache_reuses_result(monkeypatch):
    """Phase 3K — read-only pytest tests must not rebuild repo-wide static audit."""
    monkeypatch.setenv("ED_PYTEST_REUSE_STATIC_AUDIT", "1")
    mod.reset_session_static_audit_cache_for_tests()
    invocations: list[int] = []

    def capture(*, staged=None, full_static=False, profile=None, use_cache=True):
        invocations.append(1)
        return []

    monkeypatch.setattr(mod, "_run_repo_wide_static_check_funcs", capture)
    mod.run_repo_wide_static_audit(staged=set())
    mod.run_repo_wide_static_audit(staged=set())
    assert invocations == [1]
    cache = mod.session_static_audit_cache_for_tests()
    assert cache is not None
    assert tuple() in cache


def test_force_fresh_static_audit_bypasses_session_cache(monkeypatch):
    monkeypatch.setenv("ED_PYTEST_REUSE_STATIC_AUDIT", "1")
    mod.reset_session_static_audit_cache_for_tests()
    invocations: list[int] = []

    def capture(*, staged=None, full_static=False, profile=None, use_cache=True):
        invocations.append(1)
        return []

    monkeypatch.setattr(mod, "_run_repo_wide_static_check_funcs", capture)
    mod.run_repo_wide_static_audit(staged=set())
    mod.run_repo_wide_static_audit(staged=set(), force_fresh=True)
    assert invocations == [1, 1]


def test_ablation_static_index_reused_across_read_only_checks():
    from tools.ablation_static_lock_index import (
        get_ablation_static_lock_index,
        get_ablation_static_lock_index_build_count,
    )

    before = get_ablation_static_lock_index_build_count()
    idx = get_ablation_static_lock_index()
    mod.check_ablation_seven_model_four_horizon_grid()
    mod.check_ablation_equal_layer_consumers()
    after = get_ablation_static_lock_index_build_count()
    assert after == before
    assert get_ablation_static_lock_index() is idx


def test_profile_mode_writes_artifact(monkeypatch, tmp_path):
    out = tmp_path / "FIX_EVERYTHING_WE_TOUCH_PROFILE.json"
    import fix_everything_we_touch_scope as scope_mod

    monkeypatch.setattr(scope_mod, "PROFILE_ARTIFACT", out)
    monkeypatch.setattr(mod, "_run_repo_wide_static_check_funcs", lambda **kw: [])
    monkeypatch.setattr(mod, "check_upfront_mechanical_gate_stamp", lambda staged: [])
    monkeypatch.setattr(mod, "check_staged_rule_drift", lambda staged: [])
    monkeypatch.setattr(mod, "check_action_not_documentation", lambda staged: [])
    monkeypatch.setattr(mod, "check_storage_writer_has_consumer", lambda staged: [])
    monkeypatch.setattr(mod, "check_persistence_map_fresh", lambda staged: [])
    monkeypatch.setattr(mod, "check_persistence_writer_has_reader", lambda staged: [])
    import check_encoder_cone_tests as enc

    monkeypatch.setattr(enc, "check_encoder_cone_tests", lambda staged: [])
    rc = mod.main(["--profile"])
    assert rc == 0
    art = json.loads(out.read_text(encoding="utf-8"))
    assert art.get("schema_version") == 1
    assert isinstance(art.get("subchecks"), list)


def test_precommit_config_has_full_static_pre_push_hook():
    cfg = (REPO / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "fix-everything-we-touch-full-static" in cfg
    assert "--full-static" in cfg
