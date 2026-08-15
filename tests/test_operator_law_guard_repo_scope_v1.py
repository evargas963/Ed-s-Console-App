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
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import operator_law_guard as G  # noqa: E402

# RC-368: declared direct owner — this suite drives the guard's repo-scope resolution
# and the RC-360 grant reader.
TURN_AUDIT_OWNS = [
    "tools/operator_law_guard.py",
]

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
    # RC-367 repair: the obligation text moved from an RC-190 cite to the plain
    # "changed production code and ran NOTHING" clause when the supervised audit
    # took over turn verification — assert the real current clause.
    f = tmp_path / "thing.py"
    f.write_text("x", encoding="utf-8")
    ledger = [_attempt(str(f), f.stat().st_mtime_ns - 1)]
    assert any("changed production code and ran NOTHING" in v
               for v in G.stop_violations(ledger))


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
    ("$env:ED_OPERATOR_LAW_GUARD='off'", "disables a mechanical lock"),
    ("git add -A", "blind staging"),
    ("grep -r foo *.py", "shell grep"),
])
def test_universal_protections_fire_in_this_repository(cmd, needle):
    out = G.bash_violations(cmd, [], payload_cwd=str(REPO))
    assert any(needle in v for v in out), (cmd, out)


def test_rc360_head_grant_governs_no_verify_in_this_repository():
    """RC-367 repair of a stale expectation: since RC-360, a commit/push no-verify
    segment is allowed in THIS repository iff the HEAD-ratified operator grant covers
    it — the guard's verdict must agree with the grant reader either way. The
    revoke/worktree-inert paths are locked by the RC-360 tests above; the
    lock-disable env case stays unconditionally blocked (separate param)."""
    cmd = "git commit --no-verify -m x"
    covered = G._no_verify_grant_covers(cmd)
    out = G.bash_violations(cmd, [], payload_cwd=str(REPO))
    fired = any("disables a mechanical lock" in v for v in out)
    assert fired == (not covered), (covered, out)


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
    """The pre-fix module exposed no identity surface at all — the defect in one assertion.

    The comparison is against the PARENT of the commit that introduced
    ``resolve_target_repo``, not against HEAD. Reading HEAD made this control
    true for exactly one commit: the moment the fix landed, HEAD became the
    post-fix state and the control failed on its own success. A negative
    control that expires when the thing it guards is fixed is not a control.
    """
    for name in ("resolve_target_repo", "normalize_repo", "repo_root_of", "rc93_applies_to"):
        assert hasattr(G, name), name

    introduced = subprocess.run(
        ["git", "log", "--reverse", "--format=%H", "-S", "def resolve_target_repo",
         "--", "tools/operator_law_guard.py"],
        capture_output=True, text=True, cwd=str(REPO))
    if introduced.returncode != 0 or not introduced.stdout.split():
        pytest.skip("history unavailable: cannot locate the introducing commit")
    first = introduced.stdout.split()[0]

    before = subprocess.run(["git", "show", f"{first}~1:tools/operator_law_guard.py"],
                            capture_output=True, cwd=str(REPO))
    if before.returncode != 0:
        pytest.skip("the introducing commit has no parent revision of this file")
    src = before.stdout.decode("utf-8", "replace")
    assert "def resolve_target_repo" not in src, (
        f"{first[:8]} is not where the identity surface was introduced")

    after = subprocess.run(["git", "show", f"{first}:tools/operator_law_guard.py"],
                           capture_output=True, cwd=str(REPO))
    assert after.returncode == 0
    assert "def resolve_target_repo" in after.stdout.decode("utf-8", "replace"), (
        "the located commit does not actually introduce the surface")


_MOVING_REF = re.compile(
    r"""["']?git["']?[^\n]{0,80}?\bshow\b[^\n]{0,80}?["']\s*"""
    r"""(HEAD|main|master|origin/\w+)\s*[:~^]""")


def _moving_ref_offenders(text, label):
    """Lines inside NEGATIVE-CONTROL functions that pin a historical claim to a moving ref.

    Scoped to negative controls on purpose. Reading ``HEAD:<file>`` to compare
    what is committed against what is staged is a legitimate and common shape
    (tests/test_ui_mockup_lock_v1.py does exactly that). The decaying shape is
    specifically a control asserting a HISTORICAL ABSENCE against a ref that
    moves when the fix lands.
    """
    import ast
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if "negative_control" not in node.name:
            continue
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        for num in range(node.lineno, min(end, len(lines)) + 1):
            line = lines[num - 1]
            if line.lstrip().startswith("#") or "moving-ref-ok" in line:
                continue
            if _MOVING_REF.search(line):
                offenders.append(f"{label}:{num}: {line.strip()[:100]}")
    return offenders


def test_no_negative_control_compares_against_a_moving_reference():
    """Class-level lock for RC-260, not a second copy of the same one-site fix.

    RC-260 was one test comparing against ``git show HEAD:<file>``. The bug is
    not that one test picked the wrong revision -- it is that a proof bound to
    a MOVING reference inverts the moment the work it guards succeeds, and goes
    red for the one reason that should have made it green. Every negative
    control in this repository carries that decay risk, so the check sweeps
    them all rather than repairing one site.

    Pinned revisions, ``<sha>~1`` forms and ``-S`` lookups are all fine, and a
    line may opt out with ``# moving-ref-ok`` when it is a fixture rather than
    a claim.
    """
    # RC-307: repo-wide is the GIT INDEX. A filesystem walk here would judge untracked
    # scratch copies of old test files, which is how tests/test_coh_sa2_et_authority.py
    # spent weeks failing on 93 scripts the repository does not contain.
    tracked = subprocess.run(["git", "ls-files", "-z", "--", "tests/test_*.py"],
                             cwd=REPO, capture_output=True, text=True, check=True).stdout
    offenders = []
    for rel in sorted(p for p in tracked.split("\0") if p):
        path = REPO / rel
        if not path.exists():
            continue
        offenders += _moving_ref_offenders(
            path.read_text(encoding="utf-8", errors="replace"), rel)
    assert offenders == [], (
        "negative controls must name the revision they mean, not a moving ref "
        "(RC-260):\n  " + "\n  ".join(offenders))


def test_moving_reference_lock_rejects_only_its_target():
    """The lock above must reject the shape it exists to reject, and only that shape.

    Deliberately NOT named ``*negative_control*``: the fixtures below contain
    the very shape the scanner refuses, and a scanner that read its own test
    data as a finding would be unfixable.
    """
    bad = (
        "def test_negative_control_x():\n"
        "    subprocess.run(['git', 'show', 'HEAD:tools/x.py'])\n"
        "    run(['git', 'show', 'origin/main:tools/x.py'])\n")
    assert len(_moving_ref_offenders(bad, "f.py")) == 2

    # the same shape OUTSIDE a negative control is legitimate and must not trip
    elsewhere = (
        "def test_committed_matches_worktree():\n"
        "    _git(['show', 'HEAD:governance/root_cause_log.md'])\n")
    assert _moving_ref_offenders(elsewhere, "f.py") == []

    # pinned and derived forms are the accepted shapes
    good = (
        "def test_negative_control_y():\n"
        "    subprocess.run(['git', 'show', f'{first}~1:tools/x.py'])\n"
        "    subprocess.run(['git', 'show', f'{sha}:tools/x.py'])\n"
        "    git('log', '--reverse', '-S', 'def resolve_target_repo')\n")
    assert _moving_ref_offenders(good, "f.py") == []

    # and this very file must be clean under its own lock
    here = Path(__file__).read_text(encoding="utf-8")
    assert _moving_ref_offenders(here, "self") == []


# ── RC-360: the operator no-verify grant — HEAD-ratified, narrowly scoped ────────


def test_rc360_grant_is_head_ratified_and_narrow(tmp_path, monkeypatch):
    """The grant covers git commit/push --no-verify ONLY when committed at HEAD;
    a worktree-only grant (agent-writable) is IGNORED; lock-disables stay blocked."""
    import subprocess as sp

    # build a scratch repo with the grant COMMITTED at HEAD
    repo = tmp_path
    (repo / "governance").mkdir()
    grant = {"grants": {"claude_no_verify_checkpoints": {"granted": True}}}
    (repo / "governance" / "operator_grants.json").write_text(json.dumps(grant), encoding="utf-8")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=a@b", "-c", "user.name=t",
                 "commit", "-q", "--no-verify", "-m", "grant"]):
        sp.run(cmd, cwd=repo, check=True, capture_output=True)

    # point the guard's repo-root discovery at the scratch repo
    monkeypatch.setattr(G.os.path, "abspath", lambda p: str(repo / "tools" / "operator_law_guard.py"))
    assert G._no_verify_grant_covers("git commit --no-verify -m x") is True
    assert G._no_verify_grant_covers("git add a && git commit --no-verify -m x && git push --no-verify") is True
    # OUTSIDE scope: --no-verify not attached to git commit/push
    assert G._no_verify_grant_covers("some_tool --no-verify") is False
    # lock-disable rides along -> still blocked even with the grant
    assert G._no_verify_grant_covers("ED_UI_MOCKUP_LOCK=off git commit --no-verify -m x") is False

    # revoke at HEAD -> no coverage
    (repo / "governance" / "operator_grants.json").write_text(
        json.dumps({"grants": {"claude_no_verify_checkpoints": {"granted": False}}}),
        encoding="utf-8")
    sp.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    sp.run(["git", "-c", "user.email=a@b", "-c", "user.name=t",
            "commit", "-q", "--no-verify", "-m", "revoke"],
           cwd=repo, check=True, capture_output=True)
    assert G._no_verify_grant_covers("git commit --no-verify -m x") is False


def test_rc360_worktree_only_grant_is_inert(tmp_path, monkeypatch):
    """Self-grant hole closed: a grant present ONLY in the worktree (never committed)
    provides no coverage — the guard reads HEAD, not the file on disk."""
    import subprocess as sp

    repo = tmp_path
    (repo / "governance").mkdir()
    (repo / "governance" / "keep.txt").write_text("x", encoding="utf-8")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=a@b", "-c", "user.name=t",
                 "commit", "-q", "--no-verify", "-m", "base"]):
        sp.run(cmd, cwd=repo, check=True, capture_output=True)
    # grant written to the WORKTREE only — exactly what an agent could do alone
    (repo / "governance" / "operator_grants.json").write_text(
        json.dumps({"grants": {"claude_no_verify_checkpoints": {"granted": True}}}),
        encoding="utf-8")
    monkeypatch.setattr(G.os.path, "abspath", lambda p: str(repo / "tools" / "operator_law_guard.py"))
    assert G._no_verify_grant_covers("git commit --no-verify -m x") is False


# ── RC-367: the RC-350 one-app launch lock gets an owning suite ──────────────────────────
# tools/check_live_path_is_main.py shipped as a launch preflight with no test importing it,
# so the turn audit's ownership scan reported it unowned. These tests drive the REAL
# violations() against a scratch repo in every state the lock exists to catch.

def _lock_scratch_repo(tmp_path):
    import subprocess as sp
    repo = tmp_path / "lockrepo"
    repo.mkdir()
    def g(*args):
        return sp.run(["git", *args], cwd=str(repo), capture_output=True,
                      text=True, encoding="utf-8")
    g("init", "-b", "main")
    g("config", "user.email", "t@t.t")
    g("config", "user.name", "t")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    g("add", "app.py")
    g("commit", "-m", "seed")
    # fabricate origin/main == HEAD (released state)
    head = g("rev-parse", "HEAD").stdout.strip()
    g("update-ref", "refs/remotes/origin/main", head)
    return repo, g


def test_rc367_live_path_lock_clean_released_tree_passes(tmp_path, monkeypatch):
    from tools.check_live_path_is_main import violations
    repo, _g = _lock_scratch_repo(tmp_path)
    monkeypatch.chdir(repo)
    assert violations() == []


def test_rc367_live_path_lock_flags_uncommitted_app_code(tmp_path, monkeypatch):
    from tools.check_live_path_is_main import violations
    repo, _g = _lock_scratch_repo(tmp_path)
    (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    out = violations()
    assert any("uncommitted APP file" in v for v in out), out


def test_rc367_live_path_lock_flags_private_divergent_lineage(tmp_path, monkeypatch):
    from tools.check_live_path_is_main import violations
    repo, g = _lock_scratch_repo(tmp_path)
    (repo / "app.py").write_text("x = 3\n", encoding="utf-8")
    g("add", "app.py")
    g("commit", "-m", "private")
    monkeypatch.chdir(repo)
    out = violations()
    assert any("NOT on origin/main" in v for v in out), out


def test_rc367_live_path_lock_flags_detached_head(tmp_path, monkeypatch):
    from tools.check_live_path_is_main import violations
    repo, g = _lock_scratch_repo(tmp_path)
    head = g("rev-parse", "HEAD").stdout.strip()
    g("checkout", "--detach", head)
    monkeypatch.chdir(repo)
    out = violations()
    assert any("DETACHED HEAD" in v for v in out), out


# ── RC-379: a sibling hook's Stop block is not this guard's forgery ────────────────────────
#
# MEASURED LIVE 2026-08-15: honesty_guard (RC-209) blocked a Stop, the HOST then set
# stop_hook_active=True on every retry, and this guard refused each one because ITS OWN
# ledger held no stop_blocked entry — 15+ identical blocks naming no unmet obligation, with
# no output the agent could produce to clear it. The clauses below are driven through the
# REAL entrypoint as a subprocess: the deadlock message must be gone AND the genuine Stop
# policy must still fire under the same flag, proving the fix fell THROUGH to the policy
# rather than past it.

FORGERY_MSG = "a caller-controlled retry flag is not authority"
UNVERIFIED_EDIT_MSG = "changed production code and ran NOTHING"


def _write_ledger(sid: str, entries: list[dict]) -> Path:
    path = G._ledger_path(sid)
    with path.open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")
    return path


def _run_stop(sid: str, cwd: Path, *, retry_flag: bool):
    """Drive the guard's Stop path exactly as the host does: JSON on stdin, no tool_name.

    `cwd` is a CLEAN scratch repository on purpose. Pointing it at Ed Console would put the
    working tree's own production changes in scope, and main() then spawns the full
    supervised turn audit (~15 min) — measured while writing this test. The deadlock under
    test lives ABOVE that branch, so a clean subject isolates it.
    """
    payload = {"session_id": sid, "cwd": str(cwd)}
    if retry_flag:
        payload["stop_hook_active"] = True
    env = {k: v for k, v in os.environ.items() if k != "ED_OPERATOR_LAW_GUARD"}
    proc = subprocess.run(
        [sys.executable, str(REPO / "tools" / "operator_law_guard.py")],
        input=json.dumps(payload), capture_output=True, text=True, env=env,
        check=False, timeout=120,
    )
    return proc.returncode, (proc.stderr or "")


#: A turn that owes nothing: clean tree, no production edits, and the RC-125 live probe
#: actually recorded. Measured while writing this test — an EMPTY ledger is not "clean",
#: it still owes the probe, and the guard names it. PROBE_PROOF alone does NOT satisfy
#: RC-125 (it matches _VERIFICATION, not _LIVE_PROBE), so the entry below carries a real
#: live-session command that _LIVE_PROBE recognises.
LIVE_PROBE_CMD = 'curl -s -m 5 http://127.0.0.1:8000/api/build'
SATISFIED_LEDGER = [led("bash", LIVE_PROBE_CMD)]


@pytest.fixture()
def clean_stop_subject(tmp_path, request):
    """A clean repo and a ledger whose obligations are genuinely discharged."""
    repo, _g = _lock_scratch_repo(tmp_path)
    sid = f"rc379-{request.node.name}"
    _write_ledger(sid, SATISFIED_LEDGER)
    yield sid, repo
    G._ledger_path(sid).unlink(missing_ok=True)


def test_rc379_sibling_retry_flag_does_not_block_a_satisfied_turn(clean_stop_subject):
    """THE DEADLOCK: pre-fix this returned 2 forever once any sibling hook had blocked,
    no matter what the turn had actually done."""
    sid, repo = clean_stop_subject
    rc, err = _run_stop(sid, repo, retry_flag=True)
    assert FORGERY_MSG not in err, (
        "RC-379 regression: a sibling hook's Stop block is being read as a forged retry, "
        f"which deadlocks every later Stop in the session. stderr={err!r}")
    assert rc == 0, f"a turn that owes nothing must not be blocked by the retry flag: {err!r}"


def test_rc379_the_flag_changes_nothing_about_the_verdict(clean_stop_subject):
    sid, repo = clean_stop_subject
    rc_flag, err_flag = _run_stop(sid, repo, retry_flag=True)
    _write_ledger(sid, SATISFIED_LEDGER)
    rc_plain, err_plain = _run_stop(sid, repo, retry_flag=False)
    assert rc_flag == rc_plain == 0, (rc_flag, err_flag, rc_plain, err_plain)


def test_rc379_the_policy_below_still_bites_under_the_flag(tmp_path, request):
    """Fell THROUGH to the policy, not PAST it: an unverified production edit still blocks."""
    repo, g = _lock_scratch_repo(tmp_path)
    sid = f"rc379-{request.node.name}"
    # An edit recorded against the scratch repo, with no verification command in the ledger.
    _write_ledger(sid, [led("edit", str(repo / "app.py"), str(repo))])
    try:
        rc, err = _run_stop(sid, repo, retry_flag=True)
        assert FORGERY_MSG not in err, err
        assert rc == 2, f"the real Stop policy must still block an unverified edit: {err!r}"
        assert UNVERIFIED_EDIT_MSG in err or "TURN AUDIT" in err, (
            f"blocked, but named no genuine obligation: {err!r}")
    finally:
        G._ledger_path(sid).unlink(missing_ok=True)


def test_rc379_sibling_retry_is_recorded_not_swallowed(clean_stop_subject):
    """Absence of an own stop_blocked entry becomes evidence, never a fatal verdict."""
    sid, repo = clean_stop_subject
    _run_stop(sid, repo, retry_flag=True)
    # A clean Stop clears the ledger on success, so read the record the guard wrote during
    # the run rather than after it: re-run with a poisoned ledger kept alive by the block.
    _write_ledger(sid, [led("edit", str(repo / "app.py"), str(repo))])
    _run_stop(sid, repo, retry_flag=True)
    kinds = [e.get("kind") for e in G._ledger(sid)]
    assert "sibling_stop_retry" in kinds, (
        f"the fall-through must leave an audit trail of the sibling retry; kinds={kinds}")
