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
# The repo-scoped proof machinery survives ONLY for edit_violations' close-a-row clause;
# commits are quiet for this guard regardless of ledger state (pre-commit battery is the
# enforcement). One contract test replaces the five per-shape blocked-commit controls.
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


def test_applicability_declaration_marks_the_rc93_entry_retired():
    doc = json.loads((REPO / "governance" / "archive" / "guard_applicability.json")
                     .read_text(encoding="utf-8"))
    mechs = {m.get("governing_mechanism_id"): m for m in doc.get("mechanisms") or []}
    rc93 = mechs.get("ED-OPERATOR-LAW-GUARD/RC-93-COMMIT-BEFORE-PROOF")
    assert rc93 is not None, "the historical declaration row must stay (append-only history)"
    assert rc93.get("retired"), "the entry must be marked retired with its date/reason"


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
    assert any("destructive git" in v for v in OPL.reset_guard_violations(cmd)), cmd
    assert not hasattr(G, "_DESTRUCTIVE_GIT"), "the second destructive-git rule came back"


@pytest.mark.parametrize("cmd,needle", [
    ("$env:ED_OPERATOR_LAW_GUARD='off'", "disables a mechanical lock"),
    ("git add -A", "blind staging"),
    ("grep -r foo *.py", "shell grep"),
])
def test_universal_protections_fire_in_this_repository(cmd, needle):
    out = G.bash_violations(cmd, [], payload_cwd=str(REPO))
    assert any(needle in v for v in out), (cmd, out)


def test_rc360_head_grant_cannot_authorize_no_verify_in_this_repository():
    """Architecture A: --no-verify is never authorized, grant file or not."""
    cmd = "git commit --no-verify -m x"
    assert not hasattr(G, "_no_verify_grant_covers")
    out = G.bash_violations(cmd, [], payload_cwd=str(REPO))
    assert any("disables a mechanical lock" in v for v in out), out


@pytest.mark.parametrize("cmd,needle", [
    ("$env:ED_UI_MOCKUP_LOCK='off'", "disables a mechanical lock"),
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
    src = (REPO / "tools" / "operator_law_guard.py").read_text(encoding="utf-8")
    assert 'os.environ.get("ED_OPERATOR_LAW_GUARD"' not in src
    out = G.bash_violations("ED_OPERATOR_LAW_GUARD=off python x.py", [], payload_cwd=str(REPO))
    assert any("disables a mechanical lock" in v for v in out), out


# ── 7. root-cause-row closure is bound to its own repository ──────────────────────────────
def test_closing_a_row_requires_proof_for_that_repository():
    path = str(REPO / "governance" / "root_cause_log.md")
    ok = frozenset({PYTEST_PROOF})
    assert G.edit_violations(path, "| RC-1 | CLOSED |", [], ok) != []
    assert G.edit_violations(path, "| RC-1 | CLOSED |",
                             [led("bash", PYTEST_PROOF, ED)], ok) == []
    # 2026-08-25 tightening: the same ledger row WITHOUT a successful result no longer closes.
    assert G.edit_violations(path, "| RC-1 | CLOSED |",
                             [led("bash", PYTEST_PROOF, ED)], frozenset()) != []


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


def test_negative_control_pre_fix_proof_check_was_session_wide():
    """The pre-fix `_has_verification(ledger)` ignored the repository entirely."""
    def pre_fix_has_verification(ledger):
        return any(G._VERIFICATION.search(e.get("detail", ""))
                   for e in ledger if e.get("kind") == "bash")

    foreign = [led("bash", PROBE_PROOF, "c:/somewhere/else")]
    assert pre_fix_has_verification(foreign) is True      # pre-fix: foreign proof counted
    assert G._has_verification(foreign, ED) is False      # post-fix: it does not


def test_negative_control_pre_fix_had_no_repository_resolution():
    """The pre-fix module exposed no identity surface at all — the defect in one assertion.

    The comparison is against the PARENT of the commit that introduced
    ``resolve_target_repo``, not against HEAD. Reading HEAD made this control
    true for exactly one commit: the moment the fix landed, HEAD became the
    post-fix state and the control failed on its own success. A negative
    control that expires when the thing it guards is fixed is not a control.
    """
    for name in ("resolve_target_repo", "normalize_repo", "repo_root_of"):
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


def test_no_negative_control_compares_against_a_moving_reference(repo_index):
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
    #
    # TEST_SYSTEM_REHAB_V2 final remediation: migrated the independent `git ls-files`
    # re-scan onto the shared `repo_index` fixture. In the same edit, widened the file
    # filter from the literal pathspec `tests/test_*.py` to "any tracked test_*.py
    # under tests/, at any depth" -- that literal pathspec cannot match a file whose
    # immediate parent segment isn't "test_"-prefixed (git pathspec semantics), so it
    # silently never saw tests/adversarial/*.py, tests/decision_reconstruction/*.py,
    # tests/release_object/*.py, tests/runtime_proof/*.py (the same 13-file gap the
    # semantic-family manifest independently found and fixed).
    offenders = []
    for relpath, text, _tree in repo_index.items():
        rel = relpath.as_posix()
        if not (rel.startswith("tests/") and relpath.name.startswith("test_")):
            continue
        offenders += _moving_ref_offenders(text, rel)
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


def test_rc360_grant_file_cannot_authorize_no_verify(tmp_path):
    """Architecture A: a committed granted:true file is not an authority surface."""
    (tmp_path / "governance").mkdir()
    (tmp_path / "governance" / "operator_grants.json").write_text(
        json.dumps({"grants": {"claude_no_verify_checkpoints": {"granted": True}}}),
        encoding="utf-8",
    )
    src = (REPO / "tools" / "operator_law_guard.py").read_text(encoding="utf-8")
    assert "claude_no_verify_checkpoints" not in src
    assert "git show HEAD:governance/operator_grants.json" not in src
    for cmd in (
        "git commit --no-verify -m x",
        "git add a && git commit --no-verify -m x && git push --no-verify",
        "some_tool --no-verify",
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
    assert any("detached HEAD" in v for v in out), out


def test_rc367_live_path_lock_flags_feature_branch_not_main(tmp_path, monkeypatch):
    # live-checkout invariant #1: production must be on `main`, not merely non-detached. A
    # feature branch pointed at origin/main used to PASS (the exact 2026-08-26 drift that downed
    # the desk); it must now be flagged before the desk can launch on it.
    from tools.check_live_path_is_main import violations
    repo, g = _lock_scratch_repo(tmp_path)
    g("checkout", "-b", "cleanup/delete-now-root-stubs")
    monkeypatch.chdir(repo)
    out = violations()
    assert any("not `main`" in v for v in out), out


def test_rc367_live_path_lock_flags_behind_origin_main(tmp_path, monkeypatch):
    # live-checkout invariant #1 is EQUALITY: a desk BEHIND origin/main runs stale code and must
    # fast-forward (invariant #5) before launch — the old lock only barred being AHEAD.
    from tools.check_live_path_is_main import violations
    repo, g = _lock_scratch_repo(tmp_path)
    (repo / "app.py").write_text("x = 9\n", encoding="utf-8")
    g("add", "app.py")
    g("commit", "-m", "released ahead")
    g("update-ref", "refs/remotes/origin/main", g("rev-parse", "HEAD").stdout.strip())
    g("reset", "--hard", "HEAD~1")     # HEAD now one commit BEHIND origin/main, clean tree
    monkeypatch.chdir(repo)
    out = violations()
    assert any("BEHIND origin/main" in v for v in out), out


# RC-379 (sibling-retry deadlock at Stop) controls were REMOVED 2026-09-06 with this guard's
# Stop role: there is no Stop path here to deadlock. tools/stop_guard.py is the one Stop
# owner and tests/test_stop_guard_v1.py pins its retry-flag behaviour.
