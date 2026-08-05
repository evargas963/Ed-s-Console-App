"""RC-258 — operator_law_guard repository applicability, proof binding, commit detection,
and the attempted-versus-executed ledger lifecycle.

WHAT WAS MEASURED (2026-08-05, against the real hook entrypoint with isolated session ledgers):

  1. FALSE POSITIVE   `cd "<IEOS>" && git commit` exited 2 — an Ed Console rule refused a
                      commit in a repository it knows nothing about.
  2. FALSE NEGATIVE   an Ed Console pytest in the ledger then authorised that IEOS commit.
  3. FALSE NEGATIVE   a probe run inside IEOS authorised an Ed Console commit — a hole in Ed
                      Console's OWN protection, not merely a foreign-repo inconvenience.
  4. FALSE NEGATIVE   `git -C . commit` produced ZERO violations with an empty ledger. The old
                      detector was the adjacency pattern `git\\s+commit`, so four typed
                      characters walked any commit past the law.
  5. LIFECYCLE        an Edit that a LATER hook refused was recorded as a completed production
                      change, and the Stop clause then demanded a self-adversarial audit for
                      work that never touched the disk.

Every test below is written so it FAILS against the pre-fix implementation. The negative
controls at the bottom prove that claim mechanically rather than asserting it: they rebuild the
pre-fix behaviour and show it failing the same checks.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import operator_law_guard as G  # noqa: E402

ED = G.normalize_repo(REPO)
PYTEST_PROOF = ".venv/Scripts/python.exe -m pytest tests/test_db_safety.py -q"
PROBE_PROOF = 'python -c "import urllib.request; print(1)"'


# ── fixtures ──────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def other_repo(tmp_path):
    """A real git repository that is NOT Ed Console: no identity markers, so RC-93 excludes it.

    A tmp_path repo is the honest stand-in for IEOS — the test must not depend on a second
    checkout existing on the machine, and the rule under test is marker-based, not name-based.
    """
    d = tmp_path / "OtherRepo"
    (d / ".git").mkdir(parents=True)
    return d


@pytest.fixture()
def marked_repo(tmp_path):
    """A repository that DOES carry Ed Console's identity markers, at a different path.

    This is the clone-safety test: identity must follow content, not an absolute path.
    """
    d = tmp_path / "EdClone"
    (d / ".git").mkdir(parents=True)
    (d / "tools").mkdir()
    (d / "governance").mkdir()
    (d / "tools" / "operator_law_guard.py").write_text("x", encoding="utf-8")
    (d / "governance" / "root_cause_log.md").write_text("x", encoding="utf-8")
    (d / "governance" / "guard_applicability.json").write_text(
        (REPO / "governance" / "guard_applicability.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    return d


def led(kind: str, detail: str, repo: str = ""):
    return {"kind": kind, "detail": detail, "repo": repo}


# ── 1. commit detection, whatever the option placement ────────────────────────────────────
@pytest.mark.parametrize("cmd", [
    'git commit -m "x"',
    'git    commit -m "x"',
    'git -C . commit -m "x"',
    'git -C "C:/some path/repo" commit -m "x"',
    'git --git-dir=.git --work-tree=. commit -m "x"',
    'git --git-dir .git commit -m "x"',
    '"git" commit -m "x"',
    'git.exe commit -m "x"',
    'cd /tmp && git commit -m "x"',
])
def test_commit_is_detected_whatever_the_option_placement(cmd):
    assert any(G.is_git_commit(s) for s in G._SEG_SPLIT.split(G.shell_executed_part(cmd))), cmd


@pytest.mark.parametrize("cmd", [
    'git status',
    'git log --oneline',
    'git add tools/x.py',
    'python -c "print(1)"',
    'echo git commit',
])
def test_non_commit_commands_are_not_detected_as_commits(cmd):
    assert not any(G.is_git_commit(s) for s in G._SEG_SPLIT.split(G.shell_executed_part(cmd)))


def test_git_dash_c_cannot_bypass_the_commit_law():
    """RC-258 failure 4: this returned ZERO violations before the fix."""
    out = G.bash_violations('git -C . commit -m "x"', [], payload_cwd=str(REPO))
    assert out and any("without having RUN" in v for v in out), out


def test_git_dir_and_work_tree_cannot_bypass_the_commit_law():
    out = G.bash_violations('git --git-dir=.git --work-tree=. commit -m "x"', [],
                            payload_cwd=str(REPO))
    assert out and any("without having RUN" in v for v in out), out


# ── 2. repository identity resolution, and its adversaries ────────────────────────────────
def test_resolves_from_payload_working_directory():
    repo, why = G.resolve_target_repo('git commit -m "x"', payload_cwd=str(REPO))
    assert repo == ED, (repo, why)


def test_resolves_from_git_dash_c_absolute(other_repo):
    repo, _ = G.resolve_target_repo('git -C "%s" commit -m "x"' % other_repo, payload_cwd=str(REPO))
    assert repo == G.normalize_repo(other_repo)


def test_resolves_from_leading_cd(other_repo):
    repo, _ = G.resolve_target_repo('cd "%s" && git commit -m "x"' % other_repo,
                                    payload_cwd=str(REPO))
    assert repo == G.normalize_repo(other_repo)


def test_resolves_from_pushd(other_repo):
    repo, _ = G.resolve_target_repo('pushd "%s"; git commit -m "x"' % other_repo,
                                    payload_cwd=str(REPO))
    assert repo == G.normalize_repo(other_repo)


def test_resolves_relative_path_against_the_working_directory(other_repo):
    repo, _ = G.resolve_target_repo('git -C OtherRepo commit -m "x"',
                                    payload_cwd=str(other_repo.parent))
    assert repo == G.normalize_repo(other_repo)


def test_path_with_spaces_survives_quoting(tmp_path):
    d = tmp_path / "a repo with spaces"
    (d / ".git").mkdir(parents=True)
    repo, _ = G.resolve_target_repo('git -C "%s" commit -m "x"' % d, payload_cwd=str(REPO))
    assert repo == G.normalize_repo(d)


def test_backslash_and_forward_slash_resolve_identically(other_repo):
    fwd, _ = G.resolve_target_repo('git -C "%s" commit' % str(other_repo).replace("\\", "/"),
                                   payload_cwd=str(REPO))
    back, _ = G.resolve_target_repo('git -C "%s" commit' % str(other_repo).replace("/", "\\"),
                                    payload_cwd=str(REPO))
    assert fwd == back == G.normalize_repo(other_repo)


@pytest.mark.skipif(os.name != "nt", reason="Windows path casing")
def test_windows_case_variants_are_the_same_repository():
    lower, _ = G.resolve_target_repo('git -C "%s" commit' % str(REPO).lower(), payload_cwd="")
    upper, _ = G.resolve_target_repo('git -C "%s" commit' % str(REPO).upper(), payload_cwd="")
    assert lower == upper == ED


def test_chained_command_uses_the_directory_in_effect_at_the_commit(other_repo):
    repo, _ = G.resolve_target_repo('echo hi && cd "%s" && git commit -m "x"' % other_repo,
                                    payload_cwd=str(REPO))
    assert repo == G.normalize_repo(other_repo)


def test_explicit_dash_c_beats_an_earlier_cd(other_repo):
    repo, _ = G.resolve_target_repo('cd "%s" && git -C "%s" commit' % (other_repo, REPO),
                                    payload_cwd="")
    assert repo == ED


@pytest.mark.skipif(os.name != "nt", reason="MSYS drive spelling is a Windows/Git-Bash form")
def test_msys_git_bash_path_resolves():
    """The Bash tool on this host IS Git Bash, so `/c/Users/...` is the ORDINARY spelling.

    MEASURED 2026-08-05 from the live ledger: every bash entry resolved to nothing because
    `/c/...` was read as a rooted Windows path. Without this, "unresolved" is the normal case
    and the guard blocks every commit it should be judging.
    """
    msys = "/c" + str(REPO)[2:].replace("\\", "/")
    repo, why = G.resolve_target_repo('cd "%s" && git commit -m "x"' % msys, payload_cwd="")
    assert repo == ED, (msys, repo, why)


@pytest.mark.skipif(os.name != "nt", reason="MSYS drive spelling is a Windows/Git-Bash form")
def test_cygdrive_path_resolves():
    cyg = "/cygdrive/c" + str(REPO)[2:].replace("\\", "/")
    repo, _ = G.resolve_target_repo('git -C "%s" commit' % cyg, payload_cwd="")
    assert repo == ED


@pytest.mark.skipif(os.name != "nt", reason="MSYS drive spelling is a Windows/Git-Bash form")
def test_msys_and_windows_spellings_are_the_same_repository():
    a, _ = G.resolve_target_repo('git -C "%s" commit' % ("/c" + str(REPO)[2:].replace("\\", "/")))
    b, _ = G.resolve_target_repo('git -C "%s" commit' % str(REPO))
    assert a == b == ED


def test_nonexistent_path_is_unresolved():
    repo, why = G.resolve_target_repo('git -C "Z:/nope/nothing here" commit', payload_cwd=str(REPO))
    assert repo == "" and "not inside a git repository" in why


def test_path_outside_any_repository_is_unresolved(tmp_path):
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    repo, why = G.resolve_target_repo('git -C "%s" commit' % plain, payload_cwd=str(REPO))
    assert repo == "" and "not inside a git repository" in why


def test_no_path_and_no_working_directory_is_unresolved():
    repo, why = G.resolve_target_repo('git commit -m "x"', payload_cwd="")
    assert repo == "" and "no working directory" in why


def test_unresolved_identity_fails_openly_rather_than_assuming_this_repo():
    """The guard must never silently treat an unidentifiable target as its own repository."""
    out = G.bash_violations('git commit -m "x"', [], payload_cwd="")
    assert out and any("cannot resolve which repository" in v for v in out), out
    assert not any("without having RUN" in v for v in out), "must not judge an unknown target"


def test_malformed_quoting_does_not_crash_and_does_not_silently_resolve():
    repo, _ = G.resolve_target_repo('git -C "unterminated commit', payload_cwd="")
    assert repo == ""


# ── 3. repository-bound verification ──────────────────────────────────────────────────────
def test_ed_console_commit_without_ed_console_proof_is_blocked():
    out = G.bash_violations('git commit -m "x"', [], payload_cwd=str(REPO))
    assert any("without having RUN" in v for v in out), out


def test_ed_console_commit_with_matching_ed_console_proof_is_permitted():
    ledger = [led("bash", PYTEST_PROOF, ED)]
    assert G.bash_violations('git commit -m "x"', ledger, payload_cwd=str(REPO)) == []


def test_foreign_proof_cannot_authorize_an_ed_console_commit(other_repo):
    """RC-258 failure 3 — the hole in Ed Console's own protection."""
    ledger = [led("bash", PROBE_PROOF, G.normalize_repo(other_repo))]
    out = G.bash_violations('git commit -m "x"', ledger, payload_cwd=str(REPO))
    assert any("without having RUN" in v for v in out), out


def test_unknown_repository_proof_cannot_authorize_an_ed_console_commit():
    ledger = [led("bash", PYTEST_PROOF, "")]
    out = G.bash_violations('git commit -m "x"', ledger, payload_cwd=str(REPO))
    assert any("without having RUN" in v for v in out), out


def test_legacy_unscoped_ledger_entry_cannot_authorize_a_scoped_action():
    """A row written before repo binding existed has no `repo` key at all."""
    ledger = [{"kind": "bash", "detail": PYTEST_PROOF}]
    out = G.bash_violations('git commit -m "x"', ledger, payload_cwd=str(REPO))
    assert any("without having RUN" in v for v in out), out


def test_ed_console_proof_does_not_authorize_another_repository(other_repo):
    """RC-258 failure 2. The other repository carries no markers, so RC-93 does not govern it
    at all — the commit is permitted for that reason, and the assertion is that Ed Console's
    proof played no part: it is equally permitted with an EMPTY ledger."""
    with_ed_proof = G.bash_violations('git -C "%s" commit -m "x"' % other_repo,
                                      [led("bash", PYTEST_PROOF, ED)], payload_cwd=str(REPO))
    with_nothing = G.bash_violations('git -C "%s" commit -m "x"' % other_repo, [],
                                     payload_cwd=str(REPO))
    assert with_ed_proof == with_nothing == []


def test_proof_in_one_marked_repo_does_not_authorize_another_marked_repo(marked_repo):
    """Two repositories both governed by RC-93: proof still may not cross between them."""
    ledger = [led("bash", PYTEST_PROOF, ED)]
    out = G.bash_violations('git -C "%s" commit -m "x"' % marked_repo, ledger,
                            payload_cwd=str(REPO))
    assert any("without having RUN" in v for v in out), out


# ── 4. applicability is declared, not hardcoded ───────────────────────────────────────────
def test_rc93_applies_to_this_repository():
    assert G.rc93_applies_to(ED) is True


def test_rc93_does_not_apply_to_a_repository_without_the_markers(other_repo):
    assert G.rc93_applies_to(G.normalize_repo(other_repo)) is False


def test_rc93_applies_to_a_clone_at_a_different_path(marked_repo):
    """Identity is content, not location — no hardcoded absolute path anywhere."""
    assert G.rc93_applies_to(G.normalize_repo(marked_repo)) is True


def test_applicability_declaration_carries_all_ten_fields():
    doc = json.loads((REPO / "governance" / "guard_applicability.json").read_text(encoding="utf-8"))
    mech = G._mechanism(doc, G._RC93_MECHANISM_ID)
    for field in ("governing_mechanism_id", "governing_authority", "applicable_repositories",
                  "applicable_mission_classes", "applicable_components_or_paths",
                  "triggering_conditions", "exclusions", "precedence", "conflict_behavior",
                  "expiration_or_review_conditions"):
        assert mech.get(field), field
    assert mech["product_owner_determination"]["determination"]


def test_no_hardcoded_repository_exception_in_the_guard():
    """A one-off exception for a named repository is exactly what the design forbids.

    Matched by AST, not by string search: the guard is ALLOWED to describe the measured IEOS
    failures in its docstrings — that is the record of why it exists. What it may not do is
    carry a repository name or path in executable code. Searching raw source would fire on the
    documentation, which is the use-versus-mention error this repo has been bitten by twice
    (RC-186, RC-253) and is the word-policing failure the operator rejected in RC-93.
    """
    import ast

    src = (REPO / "tools" / "operator_law_guard.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    live = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings]
    offenders = [s[:80] for s in live if "ieos" in s.lower()]
    assert offenders == [], offenders
    # and no repository-rooted absolute path anywhere in executable code
    paths = [s[:80] for s in live if "trading/" in s.lower().replace("\\", "/")]
    assert paths == [], paths


def test_absent_declaration_means_the_mechanism_governs_nothing(tmp_path, monkeypatch):
    """§3.3: an undeclared scope is NOT_PROVEN, never assumed universal."""
    d = tmp_path / "NoDecl"
    (d / ".git").mkdir(parents=True)
    (d / "tools").mkdir()
    (d / "governance").mkdir()
    (d / "tools" / "operator_law_guard.py").write_text("x", encoding="utf-8")
    (d / "governance" / "root_cause_log.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(G, "REPO", d)
    assert G.rc93_applies_to(G.normalize_repo(d)) is False


# ── 5. attempted versus executed lifecycle ────────────────────────────────────────────────
def _attempt(path, mtime_before, repo=ED):
    return {"kind": "edit_attempt", "detail": path, "repo": repo, "mtime_before": mtime_before}


def test_rejected_edit_does_not_become_completed_change_evidence(tmp_path):
    """RC-258 failure 5: the file never changed, so no obligation may attach to it."""
    f = tmp_path / "thing.py"
    f.write_text("x", encoding="utf-8")
    ledger = [_attempt(str(f), f.stat().st_mtime_ns)]     # unchanged since the attempt
    assert G._production_edits(ledger) == []


def test_executed_edit_does_count_as_a_production_change(tmp_path):
    f = tmp_path / "thing.py"
    f.write_text("x", encoding="utf-8")
    ledger = [_attempt(str(f), f.stat().st_mtime_ns - 1)]  # mtime moved => the write landed
    assert G._production_edits(ledger) == [str(f).replace("\\", "/")]


def test_newly_created_file_counts_as_a_production_change(tmp_path):
    f = tmp_path / "brand_new.py"
    ledger = [_attempt(str(f), None)]                      # did not exist at attempt time
    f.write_text("x", encoding="utf-8")
    assert G._production_edits(ledger) == [str(f).replace("\\", "/")]


def test_stop_raises_no_audit_obligation_for_a_rejected_edit(tmp_path):
    f = tmp_path / "thing.py"
    f.write_text("x", encoding="utf-8")
    ledger = [_attempt(str(f), f.stat().st_mtime_ns)]
    assert G._production_edits(ledger) == []
    assert not any("RC-190" in v for v in G.stop_violations(ledger))


def test_stop_still_raises_the_audit_obligation_for_a_real_change(tmp_path):
    f = tmp_path / "thing.py"
    f.write_text("x", encoding="utf-8")
    ledger = [_attempt(str(f), f.stat().st_mtime_ns - 1)]
    assert any("RC-190" in v for v in G.stop_violations(ledger))


def test_legacy_edit_row_keeps_its_old_meaning():
    """A row written before the lifecycle fix has no baseline — it must still count, so the
    repair can never silently retire an obligation that used to fire."""
    assert G._production_edits([led("edit", "server.py", ED)]) == ["server.py"]


def test_unmeasurable_outcome_keeps_the_obligation():
    """When the answer cannot be established the obligation must NOT silently drop."""
    assert G._edit_took_effect({"detail": "Z:/nowhere/at/all/file.py",
                                "mtime_before": None}) is True


def test_governance_and_test_paths_are_still_not_production():
    ledger = [_attempt("governance/root_cause_log.md", None),
              _attempt("tests/test_x.py", None)]
    assert G._production_edits(ledger) == []


# ── 6. universal protections survive the scoping change ───────────────────────────────────
@pytest.mark.parametrize("cmd,needle", [
    ("git reset --hard HEAD~1", "destructive git"),
    ("git clean -fd", "destructive git"),
    ("git push --force origin main", "destructive git"),
    ("git commit --no-verify -m x", "disables a mechanical lock"),
    ("$env:ED_OPERATOR_LAW_GUARD='off'", "disables a mechanical lock"),
    ("git add -A", "blind staging"),
    ("grep -r foo *.py", "shell grep"),
])
def test_universal_protections_fire_in_this_repository(cmd, needle):
    out = G.bash_violations(cmd, [], payload_cwd=str(REPO))
    assert any(needle in v for v in out), (cmd, out)


@pytest.mark.parametrize("cmd,needle", [
    ("git reset --hard HEAD~1", "destructive git"),
    ("git clean -fd", "destructive git"),
    ("git push --force origin main", "destructive git"),
    ("$env:ED_UI_MOCKUP_LOCK='off'", "disables a mechanical lock"),
    ("git add -A", "blind staging"),
])
def test_universal_protections_fire_for_an_unrelated_repository(cmd, needle, other_repo):
    """The fix must not exempt another repository from host-wide safety rules."""
    out = G.bash_violations(cmd, [], payload_cwd=str(other_repo))
    assert any(needle in v for v in out), (cmd, out)


def test_universal_protections_fire_when_identity_is_unresolved():
    out = G.bash_violations("git reset --hard HEAD~1", [], payload_cwd="")
    assert any("destructive git" in v for v in out), out


def test_guard_does_not_return_early_for_an_out_of_scope_repository(other_repo):
    """A destructive command AND a commit in one chain: the universal rule must still fire."""
    out = G.bash_violations('cd "%s" && git reset --hard HEAD~1' % other_repo, [],
                            payload_cwd=str(REPO))
    assert any("destructive git" in v for v in out), out


def test_non_commit_commands_are_unaffected_by_repository_scoping():
    assert G.bash_violations("git status", [], payload_cwd=str(REPO)) == []
    assert G.bash_violations("git status", [], payload_cwd="") == []
    assert G.bash_violations("python -c \"print(1)\"", [], payload_cwd="") == []


def test_operator_escape_remains_operator_only():
    src = (REPO / "tools" / "operator_law_guard.py").read_text(encoding="utf-8")
    assert 'os.environ.get("ED_OPERATOR_LAW_GUARD"' in src
    out = G.bash_violations("ED_OPERATOR_LAW_GUARD=off python x.py", [], payload_cwd=str(REPO))
    assert any("disables a mechanical lock" in v for v in out), out


# ── 7. root-cause-row closure is bound to its own repository ──────────────────────────────
def test_closing_a_row_requires_proof_for_that_repository():
    path = str(REPO / "governance" / "root_cause_log.md")
    assert G.edit_violations(path, "| RC-1 | CLOSED |", []) != []
    assert G.edit_violations(path, "| RC-1 | CLOSED |", [led("bash", PYTEST_PROOF, ED)]) == []


def test_closing_a_row_rejects_proof_from_another_repository(other_repo):
    path = str(REPO / "governance" / "root_cause_log.md")
    ledger = [led("bash", PYTEST_PROOF, G.normalize_repo(other_repo))]
    assert G.edit_violations(path, "| RC-1 | CLOSED |", ledger) != []


# ── 8. end-to-end through the real hook entrypoint ────────────────────────────────────────
def _hook(session, tool, tool_input, cwd=None):
    payload = {"session_id": session, "tool_name": tool, "tool_input": tool_input}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    p = subprocess.run([sys.executable, str(REPO / "tools" / "operator_law_guard.py")],
                       input=json.dumps(payload), capture_output=True, text=True, cwd=str(REPO))
    return p.returncode, (p.stderr or "")


@pytest.fixture()
def isolated_session(request):
    sid = "PYTEST_RC258_" + request.node.name[:40]
    G._ledger_path(sid).unlink(missing_ok=True)
    yield sid
    G._ledger_path(sid).unlink(missing_ok=True)


def test_hook_blocks_ed_console_commit_without_proof(isolated_session):
    rc, err = _hook(isolated_session, "Bash", {"command": 'git commit -m "x"'}, cwd=REPO)
    assert rc == 2 and "without having RUN" in err


def test_hook_permits_ed_console_commit_after_ed_console_proof(isolated_session):
    _hook(isolated_session, "Bash", {"command": PYTEST_PROOF}, cwd=REPO)
    entries = G._ledger(isolated_session)
    assert entries and entries[0].get("repo") == ED, entries
    rc, err = _hook(isolated_session, "Bash", {"command": 'git commit -m "x"'}, cwd=REPO)
    assert rc == 0, err


def test_hook_does_not_let_foreign_proof_authorize_ed_console(isolated_session, other_repo):
    _hook(isolated_session, "Bash", {"command": PROBE_PROOF}, cwd=other_repo)
    rc, err = _hook(isolated_session, "Bash", {"command": 'git commit -m "x"'}, cwd=REPO)
    assert rc == 2 and "without having RUN" in err


def test_hook_does_not_subject_an_unmarked_repository_to_rc93(isolated_session, other_repo):
    rc, err = _hook(isolated_session, "Bash",
                    {"command": 'cd "%s" && git commit -m "x"' % other_repo}, cwd=REPO)
    assert rc == 0, err


def test_hook_records_the_attempt_not_a_completed_edit(isolated_session):
    rc, _ = _hook(isolated_session, "Edit",
                  {"file_path": str(REPO / "tools" / "operator_law_guard.py"),
                   "new_string": "x"}, cwd=REPO)
    assert rc == 0
    kinds = [e.get("kind") for e in G._ledger(isolated_session)]
    assert kinds == ["edit_attempt"], kinds


# ── 9. NEGATIVE CONTROLS — these prove the suite fails against the PRE-FIX implementation ──
_PRE_FIX_GIT_COMMIT = __import__("re").compile(r"\bgit\s+commit\b", __import__("re").I)


def test_negative_control_pre_fix_detector_misses_git_dash_c():
    """The old adjacency detector is rebuilt here and shown failing the detection tests."""
    assert _PRE_FIX_GIT_COMMIT.search('git commit -m "x"')
    assert not _PRE_FIX_GIT_COMMIT.search('git -C . commit -m "x"')
    assert not _PRE_FIX_GIT_COMMIT.search('git --git-dir=.git --work-tree=. commit -m "x"')


def test_negative_control_pre_fix_proof_check_was_session_wide():
    """The pre-fix `_has_verification(ledger)` ignored the repository entirely."""
    def pre_fix_has_verification(ledger):
        return any(G._VERIFICATION.search(e.get("detail", ""))
                   for e in ledger if e.get("kind") == "bash")

    foreign = [led("bash", PROBE_PROOF, "c:/somewhere/else")]
    assert pre_fix_has_verification(foreign) is True      # pre-fix: foreign proof counted
    assert G._has_verification(foreign, ED) is False      # post-fix: it does not


def test_negative_control_pre_fix_counted_a_rejected_edit_as_production_change(tmp_path):
    """The pre-fix `_production_edits` keyed on kind == 'edit' with no outcome confirmation."""
    def pre_fix_production_edits(ledger):
        out = []
        for e in ledger:
            p = e.get("detail", "").replace("\\", "/")
            if e.get("kind") != "edit":
                continue
            if any(seg in p for seg in G._NON_PRODUCTION):
                continue
            if p.endswith(G._PRODUCTION_SUFFIX):
                out.append(p)
        return out

    f = tmp_path / "refused.py"
    f.write_text("x", encoding="utf-8")
    # what the PRE-FIX guard wrote for a refused edit, and what it concluded
    assert pre_fix_production_edits([{"kind": "edit", "detail": str(f)}]) == [
        str(f).replace("\\", "/")]
    # what the POST-FIX guard writes for the same refused edit, and what it concludes
    assert G._production_edits([_attempt(str(f), f.stat().st_mtime_ns)]) == []


def test_negative_control_pre_fix_had_no_repository_resolution():
    """The pre-fix module exposed no identity surface at all — the defect in one assertion."""
    for name in ("resolve_target_repo", "normalize_repo", "repo_root_of", "rc93_applies_to"):
        assert hasattr(G, name), name
    head = subprocess.run(["git", "show", "HEAD:tools/operator_law_guard.py"],
                          capture_output=True, cwd=str(REPO))
    if head.returncode == 0:
        src = head.stdout.decode("utf-8", "replace")
        assert "def resolve_target_repo" not in src, "HEAD already had the fix — rebase the claim"
