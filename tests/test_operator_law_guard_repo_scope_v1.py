"""RC-258 — operator_law_guard repository applicability, proof binding and commit detection.

BEDROCK 2026-09-06: the attempted-versus-executed ledger lifecycle (failure 5 below) and the
RC-379 sibling-retry controls left with the guard's Stop role and its per-session ledger file;
the ledger rows the CLOSE rule reads are now built from the transcript (`turn_ledger`), and the
hand-built rows in this suite exercise the same binding.

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

import types as _types  # noqa: E402

import operator_law_guard as _olg  # noqa: E402
import shell_parse as _sp  # noqa: E402

# The repository-identity resolver moved to tools/shell_parse.py (BEDROCK 2026-09-06) and
# the guard no longer re-exports it (2026-09-10, the re-export block was test-only surface):
# this namespace presents both modules under the name the controls were written against.
_merged = {k: v for k, v in vars(_sp).items() if not k.startswith("__")}
_merged.update({k: v for k, v in vars(_olg).items() if not k.startswith("__")})
G = _types.SimpleNamespace(**_merged)
G.__file__ = _olg.__file__

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
    # (the applicability file was archived 2026-09-06; identity follows `.git`, not markers)
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


def test_commit_law_is_retired_commits_are_quiet_for_this_guard():
    """SIMPLICITY REHAB (operator full-go 2026-08-24): the RC-258 commit-needs-prior-
    verification clause is RETIRED — a commit cannot run without the pre-commit battery,
    so the guard's re-ask bought nothing and its unresolved-repo branch turned resolver
    failures into work stoppages. Contract now: git commit is QUIET for this guard in
    every spelling, and the OTHER bash protections are untouched by commit text."""
    for cmd in ('git commit -m "x"', 'git -C . commit -m "x"',
                'git --git-dir=.git --work-tree=. commit -m "x"'):
        assert G.bash_violations(cmd, [], payload_cwd=str(REPO)) == [], cmd
    # the universal protections still fire on a commit command line
    out = G.bash_violations('git add -A && git commit -m "x"', [], payload_cwd=str(REPO))
    assert out and any("blind staging" in v for v in out), out


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
    """RC-397: separator equivalence is a WINDOWS property, asserted here unconditionally.

    On POSIX a backslash is a legal filename character, not a separator, so
    `str(path).replace("/", "\\")` does not spell the same path — it spells a different,
    non-existent one. The required Linux runner proved it: the forward form resolved to
    `/tmp/pytest-.../OtherRepo` while the backslash form correctly resolved to `''`, and
    this test read the guard being RIGHT as a failure. Asserting a Windows path property
    on POSIX does not make the guard portable; it makes the suite lie about its platform.

    Each platform is now asserted for what is true there, and on POSIX the claim is the
    STRONGER one: a backslash string must not be mistaken for the real repository.
    """
    fwd, _ = G.resolve_target_repo('git -C "%s" commit' % str(other_repo).replace("\\", "/"),
                                   payload_cwd=str(REPO))
    assert fwd == G.normalize_repo(other_repo), (
        "the forward-slash form must resolve on every platform")

    backslashed = str(other_repo).replace("/", "\\")
    back, _ = G.resolve_target_repo('git -C "%s" commit' % backslashed,
                                    payload_cwd=str(REPO))
    if os.name == "nt":
        assert back == fwd, "on Windows both separators name the same repository"
    else:
        assert back != G.normalize_repo(other_repo), (
            f"on POSIX {backslashed!r} is a DIFFERENT path (backslash is a legal filename "
            f"character there, not a separator) — resolving it to the real repo would let "
            f"a payload aim at one tree while naming another")


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


def test_unresolved_identity_no_longer_stops_work():
    """SIMPLICITY REHAB: the retired RC-258 clause turned an UNRESOLVED repo identity
    into a hard block — a resolver failure became a work stoppage. Retired contract:
    quiet. resolve_target_repo itself still answers correctly (tested above) for the
    surviving close-a-row clause."""
    assert G.bash_violations('git commit -m "x"', [], payload_cwd="") == []


def test_malformed_quoting_does_not_crash_and_does_not_silently_resolve():
    repo, _ = G.resolve_target_repo('git -C "unterminated commit', payload_cwd="")
    assert repo == ""


# ── 3. repository-bound verification — commit clause RETIRED (SIMPLICITY REHAB) ──────────
# Commits are quiet for this guard regardless of ledger state (the pre-commit battery and
# required CI are the enforcement); the close-a-row clause that once consumed the ledger rows
# below was deleted 2026-09-10. The `ledger` argument is accepted and ignored.
def test_commit_is_quiet_regardless_of_ledger_proof_state(other_repo):
    for ledger in ([], [led("bash", PYTEST_PROOF, ED)],
                   [led("bash", PROBE_PROOF, G.normalize_repo(other_repo))],
                   [led("bash", PYTEST_PROOF, "")],
                   [{"kind": "bash", "detail": PYTEST_PROOF}]):
        assert G.bash_violations('git commit -m "x"', ledger, payload_cwd=str(REPO)) == []


def test_ed_console_proof_does_not_authorize_another_repository(other_repo):
    """RC-258 failure 2. The other repository carries no markers, so RC-93 does not govern it
    at all — the commit is permitted for that reason, and the assertion is that Ed Console's
    proof played no part: it is equally permitted with an EMPTY ledger."""
    with_ed_proof = G.bash_violations('git -C "%s" commit -m "x"' % other_repo,
                                      [led("bash", PYTEST_PROOF, ED)], payload_cwd=str(REPO))
    with_nothing = G.bash_violations('git -C "%s" commit -m "x"' % other_repo, [],
                                     payload_cwd=str(REPO))
    assert with_ed_proof == with_nothing == []


def test_marked_repo_commit_is_also_quiet(marked_repo):
    """SIMPLICITY REHAB: with the commit clause retired, a commit in another marked repo
    is equally quiet — its own pre-commit battery is its enforcement."""
    ledger = [led("bash", PYTEST_PROOF, ED)]
    assert G.bash_violations('git -C "%s" commit -m "x"' % marked_repo, ledger,
                             payload_cwd=str(REPO)) == []


# ── 4. applicability machinery retired with its rule (audit round 2, 2026-08-25) ──────────
def test_rc93_applicability_machinery_is_gone():
    """The commit-before-proof rule the applicability declaration scoped was retired
    2026-08-24; its scoping machinery had no production callers and is deleted. This lock
    keeps it deleted (the resurrection would be dead code shading back into authority)."""
    for name in ("rc93_applies_to", "_load_applicability", "_mechanism", "_RC93_MECHANISM_ID"):
        assert not hasattr(G, name), name


# test_applicability_declaration_marks_the_rc93_entry_retired left with governance/archive/
# (UNIVERSAL_QUANTITATIVE_CLOSURE_V1, 2026-09-10): git history is the archive, and a test
# that read a retired declaration's JSON proved the file, not the guard.


# (test_absent_declaration_means_the_mechanism_governs_nothing removed 2026-08-25 with the
# rc93 applicability machinery it exercised — the retirement lock above owns this ground.)


# ── 6. universal protections survive the scoping change ───────────────────────────────────
# BEDROCK 2026-09-06: tree-destructive git has ONE owner on the same PreToolUse chain —
# operating_process_lock.reset_guard_violations — so the three destructive spellings are
# driven at that owner. It takes no repository at all, which is the property these controls
# exist to pin: the checkout in front of the command never exempts it.
DESTRUCTIVE_GIT = ("git reset --hard HEAD~1", "git clean -fd", "git push --force origin main")


@pytest.mark.parametrize("cmd", DESTRUCTIVE_GIT)
def test_destructive_git_has_one_owner_and_it_fires_unscoped(cmd):
    import tools.operating_process_lock as OPL
    assert any("RESET_GUARD" in v for v in OPL.reset_guard_violations(cmd)), cmd
    assert not hasattr(G, "_DESTRUCTIVE_GIT"), "the second destructive-git rule came back"


@pytest.mark.parametrize("cmd,needle", [
    ("git commit --no-verify -m x", "disables a mechanical lock"),
    ("git config core.hooksPath /dev/null", "disables a mechanical lock"),
    ("python -m pre_commit uninstall", "disables a mechanical lock"),
    ("rm .git/hooks/pre-commit", "disables a mechanical lock"),
    ("git add -A", "blind staging"),
    ("rm -rf data/ed_console.db", "data/ or backups/"),
    ("git push origin HEAD:main", "only through a PR"),
    ("git push origin main", "only through a PR"),
])
def test_universal_protections_fire_in_this_repository(cmd, needle):
    out = G.bash_violations(cmd, [], payload_cwd=str(REPO))
    assert any(needle in v for v in out), (cmd, out)


@pytest.mark.parametrize("cmd", [
    "git push -u origin fix/main-screen",
    "git config --get core.hooksPath",
    "gh pr merge 427 --merge",
    "gh pr view 427",
    "grep -n no-verify tools/operator_law_guard.py",
])
def test_the_action_is_refused_never_the_word(cmd):
    """Reading about a lock, pushing a branch whose name contains "main", or merging a PR (the
    agent merges under AGENTS.md § Authority) is not a refused action."""
    assert G.bash_violations(cmd, [], payload_cwd=str(REPO)) == [], cmd


def test_rc360_head_grant_cannot_authorize_no_verify_in_this_repository():
    """Architecture A: --no-verify is never authorized, grant file or not."""
    cmd = "git commit --no-verify -m x"
    assert not hasattr(G, "_no_verify_grant_covers")
    out = G.bash_violations(cmd, [], payload_cwd=str(REPO))
    assert any("disables a mechanical lock" in v for v in out), out


@pytest.mark.parametrize("cmd,needle", [
    ("git commit --no-verify -m x", "disables a mechanical lock"),
    ("git add -A", "blind staging"),
])
def test_universal_protections_fire_for_an_unrelated_repository(cmd, needle, other_repo):
    """The fix must not exempt another repository from host-wide safety rules."""
    out = G.bash_violations(cmd, [], payload_cwd=str(other_repo))
    assert any(needle in v for v in out), (cmd, out)


def test_universal_protections_fire_when_identity_is_unresolved():
    out = G.bash_violations("git add -A", [], payload_cwd="")
    assert any("blind staging" in v for v in out), out


def test_guard_does_not_return_early_for_an_out_of_scope_repository(other_repo):
    """A banned action AND a commit in one chain aimed at another repository: the universal
    rule must still fire (RC-258: applicability is per rule, never an early return)."""
    out = G.bash_violations('cd "%s" && git add -A && git commit -m x' % other_repo, [],
                            payload_cwd=str(REPO))
    assert any("blind staging" in v for v in out), out
    chain = 'cd "%s" && git reset --hard HEAD~1' % other_repo
    import tools.operating_process_lock as OPL
    assert OPL.reset_guard_violations(chain), chain


def test_non_commit_commands_are_unaffected_by_repository_scoping():
    assert G.bash_violations("git status", [], payload_cwd=str(REPO)) == []
    assert G.bash_violations("git status", [], payload_cwd="") == []
    assert G.bash_violations("python -c \"print(1)\"", [], payload_cwd="") == []


def test_operator_escape_remains_operator_only():
    out = G.bash_violations("git commit --no-verify -m x", [], payload_cwd=str(REPO))
    assert any("disables a mechanical lock" in v for v in out), out


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
    # BEDROCK 2026-09-06: no per-session ledger file exists any more; the id is just identity.
    return "PYTEST_RC258_" + request.node.name[:40]


def test_hook_permits_commit_without_proof(isolated_session):
    """SIMPLICITY REHAB: commit clause retired — the hook is quiet; pre-commit enforces."""
    rc, err = _hook(isolated_session, "Bash", {"command": 'git commit -m "x"'}, cwd=REPO)
    assert rc == 0, err


def test_hook_commit_quiet_with_foreign_proof_too(isolated_session, other_repo):
    """SIMPLICITY REHAB: with the commit clause retired the ledger's repo binding no
    longer gates commits at all — quiet either way."""
    _hook(isolated_session, "Bash", {"command": PROBE_PROOF}, cwd=other_repo)
    rc, err = _hook(isolated_session, "Bash", {"command": 'git commit -m "x"'}, cwd=REPO)
    assert rc == 0, err


def test_hook_does_not_subject_an_unmarked_repository_to_rc93(isolated_session, other_repo):
    rc, err = _hook(isolated_session, "Bash",
                    {"command": 'cd "%s" && git commit -m "x"' % other_repo}, cwd=REPO)
    assert rc == 0, err


# ── 9. NEGATIVE CONTROLS — these prove the suite fails against the PRE-FIX implementation ──
_PRE_FIX_GIT_COMMIT = __import__("re").compile(r"\bgit\s+commit\b", __import__("re").I)


def test_negative_control_pre_fix_detector_misses_git_dash_c():
    """The old adjacency detector is rebuilt here and shown failing the detection tests."""
    assert _PRE_FIX_GIT_COMMIT.search('git commit -m "x"')
    assert not _PRE_FIX_GIT_COMMIT.search('git -C . commit -m "x"')
    assert not _PRE_FIX_GIT_COMMIT.search('git --git-dir=.git --work-tree=. commit -m "x"')


# ── RC-360: the operator no-verify grant — HEAD-ratified, narrowly scoped ────────


def test_rc360_grant_file_cannot_authorize_no_verify(tmp_path):
    """Architecture A: a committed granted:true file is not an authority surface."""
    (tmp_path / "governance").mkdir()
    (tmp_path / "governance" / "operator_grants.json").write_text(
        json.dumps({"grants": {"claude_no_verify_checkpoints": {"granted": True}}}),
        encoding="utf-8",
    )
    for cmd in (
        "git commit --no-verify -m x",
        "git add a && git commit --no-verify -m x && git push --no-verify",
        "ED_UI_MOCKUP_LOCK=off git commit --no-verify -m x",
    ):
        out = G.bash_violations(cmd, [], payload_cwd=str(REPO))
        assert any("disables a mechanical lock" in v for v in out), (cmd, out)


def test_rc360_worktree_only_grant_is_inert(tmp_path):
    """A worktree-only grant file still cannot authorize --no-verify (capability removed)."""
    (tmp_path / "governance").mkdir()
    (tmp_path / "governance" / "operator_grants.json").write_text(
        json.dumps({"grants": {"claude_no_verify_checkpoints": {"granted": True}}}),
        encoding="utf-8",
    )
    out = G.bash_violations("git commit --no-verify -m x", [], payload_cwd=str(tmp_path))
    assert any("disables a mechanical lock" in v for v in out), out

