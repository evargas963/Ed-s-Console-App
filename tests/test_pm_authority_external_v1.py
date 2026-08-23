# institutional-synthetic-ok: drive the external PM-authority reader and helper
# SOURCE contract against tmp paths. The installed privileged helper is the
# host security boundary; this file is not that boundary.
"""RC-456 — executable PM authority is external; repo JSON is not a fallback.

Tests A–Q are repository-level / helper-SOURCE proofs.
HOST ACCEPTANCE PROOF is required before merge; these tests do not claim it.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.operating_process_lock as OPL  # noqa: E402
import tools.pm_authority as PA  # noqa: E402
import tools.pm_authority_helper as PAH  # noqa: E402
import tools.process_lock_guard as PLG  # noqa: E402
import tools.writer_drift_lock as WDL  # noqa: E402


def _pin(monkeypatch, tmp_path, doc: dict | None = None, *, write: bool = True) -> Path:
    path = tmp_path / "pm_mission.json"
    if write and doc is not None:
        path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(PA, "CANONICAL_AUTHORITY_PATH", path)
    return path


def test_a_canonical_runtime_reader_uses_external_authority(monkeypatch, tmp_path):
    path = _pin(monkeypatch, tmp_path, {"pm": "operator", "status": "active", "mission_id": "ext"})
    loaded = PA.load_pm_authority()
    assert loaded.ok
    assert loaded.doc["mission_id"] == "ext"
    assert path.parent != ROOT / "governance"
    assert not PA.path_is_inside_repo(path)


def test_b_repo_json_cannot_become_executable_fallback(monkeypatch):
    monkeypatch.setattr(PA, "CANONICAL_AUTHORITY_PATH", PA.REPO_PM_MISSION_TEMPLATE)
    loaded = PA.load_pm_authority()
    assert not loaded.ok
    assert any("inside the Git repository" in m or "refuse repo JSON" in m for m in loaded.violations)
    assert OPL.pm_mission_record() == {}


def test_c_external_state_missing_fail_closed(monkeypatch, tmp_path):
    path = tmp_path / "absent.json"
    monkeypatch.setattr(PA, "CANONICAL_AUTHORITY_PATH", path)
    loaded = PA.load_pm_authority()
    assert not loaded.ok
    assert any("missing" in m for m in loaded.violations)
    assert OPL.pm_mission_record() == {}
    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    msg = OPL.pm_mission_edit_violation("server.py", agent="cursor")
    assert msg and "unavailable" in msg and "fallback" in msg


def test_d_malformed_external_state_fail_closed(monkeypatch, tmp_path):
    path = _pin(monkeypatch, tmp_path, None, write=False)
    path.write_text("<<<<<<<", encoding="utf-8")
    loaded = PA.load_pm_authority()
    assert not loaded.ok
    assert any("not valid JSON" in m for m in loaded.violations)


@pytest.mark.parametrize("body", ["{}", '{"status": "active"}'])
def test_e_pm_missing_fail_closed(monkeypatch, tmp_path, body):
    path = _pin(monkeypatch, tmp_path, None, write=False)
    path.write_text(body, encoding="utf-8")
    loaded = PA.load_pm_authority()
    assert not loaded.ok
    assert any("pm is missing" in m for m in loaded.violations)


@pytest.mark.parametrize("pm", ["cursor", "claude", "codex", "gpt", "other"])
def test_f_wrong_pm_fail_closed(monkeypatch, tmp_path, pm):
    _pin(monkeypatch, tmp_path, {"pm": pm, "status": "active"})
    loaded = PA.load_pm_authority()
    assert not loaded.ok
    assert any("required exactly 'operator'" in m for m in loaded.violations)


def test_g_pm_operator_valid(monkeypatch, tmp_path):
    _pin(monkeypatch, tmp_path, {"pm": "operator", "status": "idle"})
    loaded = PA.load_pm_authority()
    assert loaded.ok
    assert loaded.doc["pm"] == "operator"


def test_h_writer_auditor_remain_non_authorization(monkeypatch, tmp_path):
    _pin(
        monkeypatch,
        tmp_path,
        {"pm": "operator", "status": "active", "writer": "cursor", "auditor": "claude",
         "scope_paths": ["server.py"]},
    )
    loaded = PA.load_pm_authority()
    assert loaded.ok
    monkeypatch.setenv("ED_AGENT_ROLE", "gpt")
    assert OPL.pm_mission_edit_violation("server.py", agent="gpt") is None
    assert WDL.control_authority_violation("tools/pm_authority.py", agent="gpt")


def test_i_no_production_reader_treats_git_tracked_writer_auditor_as_auth():
    import ast as _ast

    tracked = subprocess.check_output(
        ["git", "ls-files", "*.py"], cwd=str(ROOT), text=True, encoding="utf-8"
    ).splitlines()
    hits: list[str] = []
    for rel in tracked:
        if rel.startswith("tests/") or rel.startswith("scratchpad/"):
            continue
        src = (ROOT / rel).read_text(encoding="utf-8")
        try:
            tree = _ast.parse(src)
        except SyntaxError:
            continue
        for node in _ast.walk(tree):
            key = None
            if (
                isinstance(node, _ast.Call)
                and isinstance(node.func, _ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], _ast.Constant)
                and node.args[0].value in ("writer", "auditor")
            ):
                key = node.args[0].value
            elif (
                isinstance(node, _ast.Subscript)
                and isinstance(node.slice, _ast.Constant)
                and node.slice.value in ("writer", "auditor")
            ):
                key = node.slice.value
            if key:
                hits.append(f"{rel}:{getattr(node, 'lineno', 0)} reads persisted {key!r}")
    assert hits == [], "production reader still uses persisted writer/auditor: " + "; ".join(hits)


def test_j_only_one_pm_authority_reader_path():
    """Production .py must load executable PM state only via tools.pm_authority."""
    tracked = subprocess.check_output(
        ["git", "ls-files", "tools/*.py"], cwd=str(ROOT), text=True, encoding="utf-8"
    ).splitlines()
    banned_openers = []
    for rel in tracked:
        if rel in {"tools/pm_authority.py", "tools/pm_authority_helper.py"}:
            continue
        src = (ROOT / rel).read_text(encoding="utf-8")
        if "governance/pm_mission.json" in src and (
            "read_text" in src or "json.loads" in src or "_load_json" in src
        ):
            # Allow comments / NON-AUTHORITATIVE pointers, not a load of that path
            # for executable state. Fail if the module still assigns PM_MISSION_PATH
            # and _load_json(PM_MISSION_PATH) together.
            if "_load_json(PM_MISSION_PATH)" in src or "json.loads(PM_MISSION_PATH" in src:
                banned_openers.append(rel)
            if "SOLE_WRITER_PATH).read_text" in src or "_load_json(SOLE_WRITER_PATH)" in src:
                banned_openers.append(rel)
    assert banned_openers == [], banned_openers
    rehab = (ROOT / "tools" / "rehab_daily_scan.py").read_text(encoding="utf-8")
    assert "load_pm_authority" in rehab
    assert OPL.pm_mission_record() == PA.executable_mission()


def test_k_helper_valid_pm_operator_pass(monkeypatch, tmp_path):
    path = _pin(monkeypatch, tmp_path, {"pm": "operator", "status": "active", "scope_paths": ["server.py"]})
    new = json.dumps({"pm": "operator", "status": "idle", "scope_paths": ["server.py"]})
    assert PAH.run(new) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "idle"


def test_l_helper_missing_pm_fail(monkeypatch, tmp_path):
    _pin(monkeypatch, tmp_path, {"pm": "operator", "status": "active"})
    assert PAH.run(json.dumps({"status": "idle"})) == 2


def test_m_helper_wrong_pm_fail(monkeypatch, tmp_path):
    _pin(monkeypatch, tmp_path, {"pm": "operator", "status": "active"})
    for pm in ("cursor", "claude", "codex", "gpt"):
        assert PAH.run(json.dumps({"pm": pm, "status": "active"})) == 2


def test_n_helper_malformed_json_fail(monkeypatch, tmp_path):
    _pin(monkeypatch, tmp_path, {"pm": "operator"})
    assert PAH.run("not-json") == 2


def test_o_arbitrary_path_injection_impossible(monkeypatch, tmp_path):
    _pin(monkeypatch, tmp_path, {"pm": "operator", "status": "active"})
    evil = tmp_path / "evil.json"
    rc = PAH.main(["--output", str(evil)])
    assert rc == 2
    assert not evil.exists()
    rc2 = PAH.main([str(tmp_path / "other.json")])
    assert rc2 == 2


def test_p_symlink_and_output_redirection_impossible_by_interface(monkeypatch, tmp_path):
    """Helper CLI has no output-path parameter; write_atomic refuses a different dest."""
    dest = _pin(monkeypatch, tmp_path, {"pm": "operator"})
    other = tmp_path / "redir.json"
    other.write_text("{}", encoding="utf-8")
    errs = PA.write_atomic_authority(
        json.dumps({"pm": "operator"}), dest=other
    )
    assert errs
    assert json.loads(other.read_text(encoding="utf-8")) == {}
    # symlink dest
    link = tmp_path / "link.json"
    if hasattr(os, "symlink"):
        try:
            link.symlink_to(dest)
        except OSError:
            pytest.skip("symlink not permitted")
        monkeypatch.setattr(PA, "CANONICAL_AUTHORITY_PATH", link)
        errs2 = PA.write_atomic_authority(json.dumps({"pm": "operator", "status": "x"}))
        assert errs2


def test_q_mutation_of_validation_condition_makes_tests_red():
    """If the helper/reader accepts a non-operator pm, this test goes RED."""
    src = (ROOT / "tools" / "pm_authority.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "REQUIRED_PM":
                    assert isinstance(node.value, ast.Constant)
                    assert node.value.value == "operator"
                    found = True
    assert found
    assert PA.validate_pm_authority_document('{"pm": "cursor"}')
    assert PA.validate_pm_authority_document('{"pm": "operator"}') == []


def test_shell_text_filter_is_not_a_security_function():
    assert not hasattr(WDL, "pm_authority_shell_violations")


def test_helper_source_is_not_claimed_as_the_boundary():
    src = (ROOT / "tools" / "pm_authority_helper.py").read_text(encoding="utf-8")
    assert "NOT THE SECURITY BOUNDARY" in src
    assert "NO arbitrary output path" in src or "no output path" in src.lower()


def test_file_tool_delete_of_repo_template_is_not_authority_block(monkeypatch, tmp_path):
    _pin(monkeypatch, tmp_path, {"pm": "operator", "status": "active"})
    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    bad = PLG.pretooluse_block(
        "Delete", {"path": str(ROOT / "governance" / "pm_mission.json")}
    )
    assert not any("pm=operator" in b and "delete" in b.lower() for b in bad)


def test_file_tool_write_canonical_wrong_pm_blocked(monkeypatch, tmp_path):
    path = _pin(monkeypatch, tmp_path, {"pm": "operator", "status": "active"})
    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    bad = PLG.pretooluse_block(
        "Write",
        {"file_path": str(path), "content": json.dumps({"pm": "claude"})},
    )
    assert any("required exactly 'operator'" in b or "PM_AUTHORITY" in b for b in bad)
