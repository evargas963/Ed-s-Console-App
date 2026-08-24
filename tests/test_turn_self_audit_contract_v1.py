"""TURN_SELF_AUDIT_REBUILD_V1 — adversarial contract tests.

These tests exercise the public audit CLI, its canonical Git scope, the
authoritative result validator, and the Stop supervisor.  Critical controls use
real temporary Git repositories and subprocesses rather than replacing the
enforcement implementation with mocks.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / "tools" / "turn_self_audit.py"
GUARD = ROOT / "tools" / "operator_law_guard.py"
TURN_AUDIT_OWNS = [
    "tools/turn_self_audit.py",
    "tools/operator_law_guard.py",
]


def _run(argv: list[str], *, cwd: Path, timeout: float = 60, stdin: str | None = None):
    return subprocess.run(
        argv,
        cwd=str(cwd),
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=repo)


def _commit(repo: Path, message: str) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "git", "-c", "user.name=Audit Contract",
            "-c", "user.email=audit@example.invalid",
            "commit", "-m", message,
        ],
        cwd=repo,
    )


def _repo(tmp_path: Path, *, owner: bool = True) -> Path:
    repo = tmp_path / "subject"
    repo.mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    test = "import mod\n\ndef test_value():\n    assert mod.VALUE > 0\n"
    if not owner:
        test = "# mod appears only in a comment\n\ndef test_unrelated():\n    assert True\n"
    (repo / "tests" / "test_mod.py").write_text(test, encoding="utf-8")
    assert _git(repo, "init").returncode == 0
    assert _git(repo, "add", ".").returncode == 0
    commit = _run(
        [
            "git",
            "-c",
            "user.name=Audit Contract",
            "-c",
            "user.email=audit@example.invalid",
            "commit",
            "-m",
            "baseline",
        ],
        cwd=repo,
    )
    assert commit.returncode == 0, commit.stderr
    return repo


def _invoke_audit(repo: Path, session: str = "session-v1", *extra: str, timeout: float = 90):
    proc = _run(
        [
            sys.executable,
            str(AUDIT),
            "--authoritative",
            "--repo",
            str(repo),
            "--session-id",
            session,
            *extra,
        ],
        cwd=ROOT,
        timeout=timeout,
    )
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = None
    return proc, result


def _modify(repo: Path, value: int = 2) -> None:
    (repo / "mod.py").write_text(f"VALUE = {value}\n", encoding="utf-8")


def test_scope_covers_untracked_rename_and_delete(tmp_path):
    import tools.turn_self_audit as audit

    repo = _repo(tmp_path)
    assert _git(repo, "mv", "mod.py", "renamed.py").returncode == 0
    (repo / "untracked.py").write_text("VALUE = 3\n", encoding="utf-8")
    (repo / "tests" / "test_mod.py").unlink()

    scope = audit.discover_scope(repo)
    assert scope.status == audit.STATUS_PASS, scope.errors
    rows = {(e.kind, e.path, e.old_path) for e in scope.entries}
    assert any(kind == "RENAME" and path == "renamed.py" and old == "mod.py"
               for kind, path, old in rows)
    assert ("UNTRACKED", "untracked.py", None) in rows
    assert ("DELETE", "tests/test_mod.py", None) in rows
    assert "untracked.py" in {e.path for e in scope.production_entries}


def test_git_scope_failure_is_incomplete(tmp_path):
    import tools.turn_self_audit as audit

    scope = audit.discover_scope(tmp_path)
    assert scope.status == audit.STATUS_INCOMPLETE
    assert scope.errors


@pytest.mark.parametrize("flag", ["--files", "--tests"])
def test_authoritative_narrowing_flags_are_rejected(tmp_path, flag):
    repo = _repo(tmp_path)
    _modify(repo)
    proc, result = _invoke_audit(repo, "narrowing", flag, "mod.py")
    assert proc.returncode == audit_exit("INCOMPLETE")
    assert result and result["verdict"] == "INCOMPLETE"
    assert any("narrow" in e.lower() for e in result["internal_errors"])


def audit_exit(verdict: str) -> int:
    return {"CLEAN": 0, "NO_RELEVANT_PRODUCTION_CHANGE": 0,
            "FAIL": 1, "NOT_PROVEN": 2, "INCOMPLETE": 3}[verdict]


def test_comment_or_string_does_not_create_test_ownership(tmp_path):
    repo = _repo(tmp_path, owner=False)
    _modify(repo)
    proc, result = _invoke_audit(repo, "comment-owner")
    assert proc.returncode == audit_exit("NOT_PROVEN")
    assert result["verdict"] == "NOT_PROVEN"
    assert "mod.py" in result["ownership"]["unknown"]
    # V3 Step 2 added the two always-on state measurements between scope_integrity and the
    # change-driven checks, so the executed list carries them too.
    assert result["checks_executed"] == [
        "scope_integrity", "index_worktree_state", "runtime_identity_state",
        "ruff_changed", "test_ownership", "owned_pytest"
    ]


def test_explicit_precedence_is_per_changed_production_entry(tmp_path):
    import tools.turn_self_audit as audit

    repo = _repo(tmp_path)
    (repo / "other.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "tests" / "test_mod.py").write_text(
        'TURN_AUDIT_OWNS = ["mod.py"]\n'
        "import mod\n\n"
        "def test_value():\n"
        "    assert mod.VALUE > 0\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_incidental.py").write_text(
        "import mod\n\n"
        "def test_incidental():\n"
        "    assert mod.VALUE > 0\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_other.py").write_text(
        "import other\n\n"
        "def test_other():\n"
        "    assert other.VALUE > 0\n",
        encoding="utf-8",
    )
    assert _git(repo, "add", ".").returncode == 0
    assert _commit(repo, "ownership fixtures").returncode == 0
    _modify(repo)
    (repo / "other.py").write_text("VALUE = 2\n", encoding="utf-8")

    ownership = audit.resolve_test_ownership(repo, audit.discover_scope(repo))

    assert ownership.status == audit.STATUS_PASS
    assert ownership.suites == ["tests/test_mod.py", "tests/test_other.py"]
    assert ownership.reasons["mod.py"] == [
        "tests/test_mod.py:TURN_AUDIT_OWNS"
    ]
    assert ownership.reasons["other.py"] == ["tests/test_other.py:import"]


def test_changed_executable_test_has_mechanical_exclusion_disposition(tmp_path):
    import tools.turn_self_audit as audit

    repo = _repo(tmp_path)
    changed = repo / "tests" / "test_changed_executable.py"
    changed.write_text("def test_changed():\n    assert True\n", encoding="utf-8")
    assert _git(repo, "add", ".").returncode == 0
    assert _commit(repo, "changed test baseline").returncode == 0
    _modify(repo)
    changed.write_text("def test_changed():\n    assert False\n", encoding="utf-8")

    ownership = audit.resolve_test_ownership(repo, audit.discover_scope(repo))

    assert "tests/test_changed_executable.py" not in ownership.suites
    assert ownership.excluded_changed_tests == {
        "tests/test_changed_executable.py": "no changed production ownership evidence"
    }


def test_session_subject_excludes_external_import_fanout_fail_closed(tmp_path):
    import tools.turn_self_audit as audit

    repo = _repo(tmp_path)
    (repo / "external.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "tests" / "test_external.py").write_text(
        "import external\n\n"
        "def test_external():\n"
        "    assert external.VALUE > 0\n",
        encoding="utf-8",
    )
    assert _git(repo, "add", ".").returncode == 0
    assert _commit(repo, "external fixture").returncode == 0
    _modify(repo)
    (repo / "external.py").write_text("VALUE = 2\n", encoding="utf-8")

    ownership = audit.resolve_test_ownership(
        repo, audit.discover_scope(repo), subject_paths={"mod.py"}
    )

    assert ownership.suites == ["tests/test_mod.py"]
    assert ownership.unknown == ["external.py"]
    assert ownership.excluded_production == {
        "external.py": "outside authoritative session subject"
    }


def test_repository_project_b_direct_owner_set_is_complete():
    import tools.turn_self_audit as audit

    ownership = audit.resolve_test_ownership(
        ROOT,
        audit.discover_scope(ROOT),
        subject_paths={"tools/turn_self_audit.py", "tools/operator_law_guard.py"},
    )

    assert ownership.suites == [
        "tests/test_audit_outcome_is_typed_v1.py",
        "tests/test_enforced_check_negative_controls_v1.py",
        "tests/test_operator_law_guard_repo_scope_v1.py",
        "tests/test_plus_player_law_v1.py",
        "tests/test_protected_paths_v1.py",
        "tests/test_turn_self_audit_contract_v1.py",
        "tests/test_ui_mockup_lock_v1.py",
    ]


def test_ownership_parser_failure_is_incomplete(tmp_path):
    repo = _repo(tmp_path)
    (repo / "tests" / "test_mod.py").write_text("def broken(:\n", encoding="utf-8")
    _modify(repo)
    proc, result = _invoke_audit(repo, "parse-owner")
    assert proc.returncode == audit_exit("INCOMPLETE")
    assert result["verdict"] == "INCOMPLETE"
    assert result["ownership"]["errors"]


def test_unknown_owner_cannot_produce_zero_test_clean(tmp_path):
    repo = _repo(tmp_path, owner=False)
    _modify(repo)
    proc, result = _invoke_audit(repo, "unknown-owner")
    assert proc.returncode != 0
    assert result["verdict"] == "NOT_PROVEN"
    assert result["pytest_result"]["status"] == "NOT_PROVEN"


def test_valid_current_audit_is_clean_and_identity_bound(tmp_path):
    import tools.turn_self_audit as audit

    repo = _repo(tmp_path)
    _modify(repo)
    proc, result = _invoke_audit(repo, "valid-current")
    assert proc.returncode == 0, proc.stderr
    assert result["contract_id"] == "CLEAN_FOR_TURN_CONTRACT_V1"
    assert result["verdict"] == "CLEAN"
    assert result["completed"] is True
    assert result["checks_required"] == result["checks_executed"]
    assert result["repo_head"] == _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert result["worktree_identity_start"] == result["worktree_identity_end"]
    assert audit.validate_result(
        result, repo=repo, session_id="valid-current", observed_exit_code=proc.returncode
    ) == []


def test_required_not_proven_blocks_stop(tmp_path):
    import tools.operator_law_guard as guard

    repo = _repo(tmp_path, owner=False)
    _modify(repo)
    violations, result = guard.supervise_turn_audit(repo, "required-not-proven")
    assert violations
    assert result["verdict"] == "NOT_PROVEN"


def test_audit_fail_blocks_stop(tmp_path):
    import tools.operator_law_guard as guard

    repo = _repo(tmp_path)
    (repo / "mod.py").write_text("VALUE = missing_name\n", encoding="utf-8")
    violations, result = guard.supervise_turn_audit(repo, "audit-fail")
    assert violations
    assert result["verdict"] == "FAIL"


@pytest.mark.parametrize(
    ("program", "expected"),
    [
        ("raise SystemExit(7)", "did not complete successfully"),
        ("import time; time.sleep(30)", "timed out"),
        ("print('not-json')", "malformed"),
    ],
)
def test_crash_timeout_and_malformed_child_block_stop(tmp_path, program, expected):
    import tools.operator_law_guard as guard

    repo = _repo(tmp_path)
    timeout = 0.2 if "sleep" in program else 10
    violations, result = guard.supervise_turn_audit(
        repo,
        "bad-child",
        command=[sys.executable, "-c", program],
        timeout=timeout,
    )
    assert violations
    assert result["verdict"] == "INCOMPLETE"
    assert expected in " ".join(violations).lower()


def test_required_check_omission_and_duplicate_are_rejected(tmp_path):
    import tools.turn_self_audit as audit

    repo = _repo(tmp_path)
    _modify(repo)
    proc, result = _invoke_audit(repo, "set-equality")
    assert proc.returncode == 0

    omitted = json.loads(json.dumps(result))
    omitted["checks_executed"] = omitted["checks_executed"][:-1]
    assert any("required" in e.lower() and "executed" in e.lower()
               for e in audit.validate_result(
                   omitted, repo=repo, session_id="set-equality", observed_exit_code=0))

    omitted_everywhere = json.loads(json.dumps(result))
    omitted_id = omitted_everywhere["checks_required"][-1]
    omitted_everywhere["checks_required"] = omitted_everywhere["checks_required"][:-1]
    omitted_everywhere["checks_executed"] = omitted_everywhere["checks_executed"][:-1]
    omitted_everywhere["checks"] = [
        c for c in omitted_everywhere["checks"] if c["check_id"] != omitted_id
    ]
    assert any("required check set mismatch" in e for e in audit.validate_result(
        omitted_everywhere, repo=repo, session_id="set-equality", observed_exit_code=0))

    duplicate = json.loads(json.dumps(result))
    duplicate["checks_executed"].append(duplicate["checks_executed"][0])
    assert any("duplicate" in e.lower() for e in audit.validate_result(
        duplicate, repo=repo, session_id="set-equality", observed_exit_code=0))


def test_stale_and_wrong_worktree_results_are_rejected(tmp_path):
    import tools.turn_self_audit as audit

    repo = _repo(tmp_path / "a")
    other = _repo(tmp_path / "b")
    _modify(repo)
    _modify(other, 4)
    proc, result = _invoke_audit(repo, "identity")
    assert proc.returncode == 0

    assert any("repo" in e.lower() or "worktree" in e.lower()
               for e in audit.validate_result(
                   result, repo=other, session_id="identity", observed_exit_code=0))

    _modify(repo, 9)
    assert any("identity" in e.lower() or "scope" in e.lower()
               for e in audit.validate_result(
                   result, repo=repo, session_id="identity", observed_exit_code=0))


def test_worktree_change_during_actual_audit_is_incomplete(tmp_path):
    repo = _repo(tmp_path)
    (repo / "tests" / "test_mod.py").write_text(
        "from pathlib import Path\n"
        "import mod\n\n"
        "def test_mutates_subject():\n"
        "    Path('mod.py').write_text('VALUE = 77\\n', encoding='utf-8')\n"
        "    assert mod.VALUE > 0\n",
        encoding="utf-8",
    )
    _modify(repo)
    proc, result = _invoke_audit(repo, "moving-subject")
    assert proc.returncode == audit_exit("INCOMPLETE")
    assert result["verdict"] == "INCOMPLETE"
    assert result["worktree_identity_start"] != result["worktree_identity_end"]


def test_fabricated_repository_json_is_ignored(tmp_path):
    import tools.operator_law_guard as guard

    repo = _repo(tmp_path, owner=False)
    _modify(repo)
    (repo / "reports").mkdir()
    (repo / "reports" / "turn_self_audit_result.json").write_text(
        json.dumps({"verdict": "CLEAN", "exit_code": 0}), encoding="utf-8"
    )
    violations, result = guard.supervise_turn_audit(repo, "fabricated")
    assert violations
    assert result["verdict"] == "NOT_PROVEN"


def test_invalid_stop_payload_and_missing_session_identity_block():
    invalid = _run([sys.executable, str(GUARD)], cwd=ROOT, stdin="{not-json")
    assert invalid.returncode == 2

    missing = _run(
        [sys.executable, str(GUARD)],
        cwd=ROOT,
        stdin=json.dumps({"tool_name": "Stop", "cwd": str(ROOT)}),
    )
    assert missing.returncode == 2
    assert "session" in missing.stderr.lower()

    missing_cwd = _run(
        [sys.executable, str(GUARD)],
        cwd=ROOT,
        stdin=json.dumps({"session_id": "missing-cwd", "tool_name": "Stop"}),
    )
    assert missing_cwd.returncode == 2
    assert "working-directory identity" in missing_cwd.stderr


def _hook(payload: dict) -> subprocess.CompletedProcess[str]:
    return _run(
        [sys.executable, str(GUARD)],
        cwd=ROOT,
        stdin=json.dumps(payload),
        timeout=120,
    )


def _seed_real_stop_ledger(repo: Path, session: str) -> None:
    edit = {
        "session_id": session,
        "tool_name": "Edit",
        "cwd": str(repo),
        "tool_input": {"file_path": str(repo / "mod.py"), "new_string": "VALUE = 2\n"},
    }
    assert _hook(edit).returncode == 0
    _modify(repo)
    for command in (
        f"{sys.executable} -m pytest tests/test_mod.py -q",
        f"{sys.executable} -c \"import urllib.request; "
        "urllib.request.urlopen('http://127.0.0.1:8000/api/build')\"",
    ):
        payload = {
            "session_id": session,
            "tool_name": "Bash",
            "cwd": str(repo),
            "tool_input": {"command": command},
        }
        assert _hook(payload).returncode == 0


def test_real_stop_path_launches_valid_audit_without_command_history(tmp_path):
    repo = _repo(tmp_path)
    session = f"real-stop-{time.time_ns()}"
    _seed_real_stop_ledger(repo, session)
    stop = _hook({"session_id": session, "tool_name": "Stop", "cwd": str(repo)})
    assert stop.returncode == 0, stop.stderr


def test_real_stop_derives_applicability_without_edit_ledger(tmp_path):
    repo = _repo(tmp_path, owner=False)
    _modify(repo)
    session = f"real-stop-out-of-band-{time.time_ns()}"
    live_probe = _hook({
        "session_id": session,
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": "curl http://127.0.0.1:8000/api/build"},
    })
    assert live_probe.returncode == 0
    stop = _hook({"session_id": session, "tool_name": "Stop", "cwd": str(repo)})
    assert stop.returncode == 2
    assert "authoritative verdict is NOT_PROVEN" in stop.stderr


def test_committed_turn_edit_remains_in_authoritative_session_scope(tmp_path):
    repo = _repo(tmp_path)
    session = f"real-stop-committed-{time.time_ns()}"
    edit = {
        "session_id": session,
        "tool_name": "Edit",
        "cwd": str(repo),
        "tool_input": {"file_path": str(repo / "mod.py"), "new_string": "VALUE = 2\n"},
    }
    assert _hook(edit).returncode == 0
    _modify(repo)
    assert _git(repo, "add", "mod.py").returncode == 0
    committed = _run(
        [
            "git",
            "-c",
            "user.name=Audit Contract",
            "-c",
            "user.email=audit@example.invalid",
            "commit",
            "-m",
            "turn change",
        ],
        cwd=repo,
    )
    assert committed.returncode == 0
    for command in (
        f"{sys.executable} -m pytest tests/test_mod.py -q",
        "curl http://127.0.0.1:8000/api/build",
    ):
        assert _hook({
            "session_id": session,
            "tool_name": "Bash",
            "cwd": str(repo),
            "tool_input": {"command": command},
        }).returncode == 0
    stop = _hook({"session_id": session, "tool_name": "Stop", "cwd": str(repo)})
    assert stop.returncode == 0, stop.stderr
    receipts = Path(tempfile.gettempdir()) / "ed_turn_audit_receipts" / session
    receipt = json.loads(next(receipts.glob("*.json")).read_text(encoding="utf-8"))
    result = receipt["result"]
    assert result["session_required_files"] == ["mod.py"]
    assert any(
        entry["kind"] == "SESSION_EDIT" and entry["path"] == "mod.py"
        for entry in result["actual_scope"]["production_entries"]
    )
    assert result["verdict"] == "CLEAN"


def test_real_stop_path_blocks_not_proven_even_if_command_text_was_recorded(tmp_path):
    repo = _repo(tmp_path, owner=False)
    session = f"real-stop-np-{time.time_ns()}"
    _seed_real_stop_ledger(repo, session)
    command_claim = {
        "session_id": session,
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": f"{sys.executable} tools/turn_self_audit.py"},
    }
    assert _hook(command_claim).returncode == 0
    stop = _hook({"session_id": session, "tool_name": "Stop", "cwd": str(repo)})
    assert stop.returncode == 2
    assert "authoritative verdict is NOT_PROVEN" in stop.stderr
    retry = _hook({
        "session_id": session,
        "tool_name": "Stop",
        "stop_hook_active": True,
        "cwd": str(repo),
    })
    assert retry.returncode == 2
    assert "authoritative verdict is NOT_PROVEN" in retry.stderr


def test_stop_retry_flag_grants_no_authorization(tmp_path):
    """SIMPLICITY REHAB 2026-08-24: RC-125 (probe-every-turn) is retired, so a Stop
    with an EMPTY ledger now legitimately passes — nothing was owed. The property that
    survives this shrink, pinned here: `stop_hook_active` is observability, never
    authority. The full Stop policy re-runs on a retry, and an unmet obligation (a
    production edit with nothing executed) blocks the retry exactly like a first Stop."""
    repo = _repo(tmp_path)

    clean_session = f"retry-clean-{time.time_ns()}"
    clean_retry = _hook({
        "session_id": clean_session,
        "tool_name": "Stop",
        "stop_hook_active": True,
        "cwd": str(repo),
    })
    assert clean_retry.returncode == 0, (
        "an empty-ledger retry must pass on the policy's merits (RC-125 retired), "
        "not deadlock on the flag itself (RC-379)")

    owing_session = f"retry-owing-{time.time_ns()}"
    edit = {
        "session_id": owing_session,
        "tool_name": "Edit",
        "cwd": str(repo),
        "tool_input": {"file_path": str(repo / "mod.py"), "new_string": "VALUE = 2\n"},
    }
    assert _hook(edit).returncode == 0
    _modify(repo)
    owing_retry = _hook({
        "session_id": owing_session,
        "tool_name": "Stop",
        "stop_hook_active": True,
        "cwd": str(repo),
    })
    assert owing_retry.returncode == 2, (
        "a retry with an unmet obligation must still block — the flag is not authority")
    assert "ran NOTHING" in owing_retry.stderr or "TURN AUDIT" in owing_retry.stderr


def test_malformed_structured_check_record_blocks_without_validator_crash(tmp_path):
    import tools.operator_law_guard as guard

    repo = _repo(tmp_path)
    _modify(repo)
    proc, result = _invoke_audit(repo, "malformed-check-record")
    assert proc.returncode == 0
    result["checks"] = [1]
    program = f"import json; print(json.dumps({result!r}))"
    violations, rejected = guard.supervise_turn_audit(
        repo,
        "malformed-check-record",
        command=[sys.executable, "-c", program],
        timeout=10,
    )
    assert rejected["verdict"] == "CLEAN"
    assert any("checks[0] must be object" in violation for violation in violations)


def test_actual_registered_owner_check_baseline_mutation_restoration(tmp_path):
    repo = _repo(tmp_path)
    _modify(repo)

    baseline, baseline_result = _invoke_audit(repo, "control-baseline")
    assert baseline.returncode == 0
    assert baseline_result["verdict"] == "CLEAN"

    owner = repo / "tests" / "test_mod.py"
    original = owner.read_text(encoding="utf-8")
    owner.write_text(
        "# mod is mentioned, not imported\n\ndef test_unrelated():\n    assert True\n",
        encoding="utf-8",
    )
    mutated, mutated_result = _invoke_audit(repo, "control-mutation")
    assert mutated.returncode == audit_exit("NOT_PROVEN")
    assert mutated_result["verdict"] == "NOT_PROVEN"
    assert "mod.py" in mutated_result["ownership"]["unknown"]

    owner.write_text(original, encoding="utf-8")
    restored, restored_result = _invoke_audit(repo, "control-restored")
    assert restored.returncode == 0
    assert restored_result["verdict"] == "CLEAN"


def test_actual_registered_ruff_check_baseline_mutation_restoration(tmp_path):
    repo = _repo(tmp_path)
    _modify(repo)
    baseline, baseline_result = _invoke_audit(repo, "ruff-baseline")
    assert baseline.returncode == 0
    assert baseline_result["ruff_result"]["status"] == "PASS"

    (repo / "mod.py").write_text("VALUE = missing_name\n", encoding="utf-8")
    mutated, mutated_result = _invoke_audit(repo, "ruff-mutation")
    assert mutated.returncode == audit_exit("FAIL")
    assert mutated_result["ruff_result"]["status"] == "FAIL"

    _modify(repo)
    restored, restored_result = _invoke_audit(repo, "ruff-restored")
    assert restored.returncode == 0
    assert restored_result["ruff_result"]["status"] == "PASS"


def test_actual_registered_pytest_check_baseline_mutation_restoration(tmp_path):
    repo = _repo(tmp_path)
    _modify(repo)
    baseline, baseline_result = _invoke_audit(repo, "pytest-baseline")
    assert baseline.returncode == 0
    assert baseline_result["pytest_result"]["status"] == "PASS"

    test_path = repo / "tests" / "test_mod.py"
    original = test_path.read_text(encoding="utf-8")
    test_path.write_text(
        "import mod\n\ndef test_value():\n    assert mod.VALUE < 0\n",
        encoding="utf-8",
    )
    mutated, mutated_result = _invoke_audit(repo, "pytest-mutation")
    assert mutated.returncode == audit_exit("FAIL")
    assert mutated_result["pytest_result"]["status"] == "FAIL"

    test_path.write_text(original, encoding="utf-8")
    restored, restored_result = _invoke_audit(repo, "pytest-restored")
    assert restored.returncode == 0
    assert restored_result["pytest_result"]["status"] == "PASS"


def test_actual_scope_check_baseline_failure_restoration(tmp_path):
    repo = _repo(tmp_path)
    _modify(repo)
    baseline, baseline_result = _invoke_audit(repo, "scope-baseline")
    assert baseline.returncode == 0
    assert baseline_result["checks"][0]["status"] == "PASS"

    git_dir = repo / ".git"
    hidden_git = repo / ".git.audit-control"
    git_dir.rename(hidden_git)
    mutated, mutated_result = _invoke_audit(repo, "scope-mutation")
    assert mutated.returncode == audit_exit("INCOMPLETE")
    assert mutated_result["checks"][0]["status"] == "INCOMPLETE"

    hidden_git.rename(git_dir)
    restored, restored_result = _invoke_audit(repo, "scope-restored")
    assert restored.returncode == 0
    assert restored_result["checks"][0]["status"] == "PASS"
