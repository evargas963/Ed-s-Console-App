"""RC-387 — the delta gate must FAIL a regression, or it is decoration.

The tool exists because tests an author writes only encode failure modes that author
already imagined. It would be self-refuting to ship it without a lock, and it was: the
Stop supervisor's ownership resolution found no owning suite for
tools/check_delta_adds_no_debt.py, which is what these controls repair.

The load-bearing property is asymmetry. A comparison that cannot fail is a rubber stamp —
the exact defect that produced four bad ledger closes earlier in the same session — so the
first control plants a regression and demands a FAIL.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# RC-368: declared direct owner of the tool under test.
TURN_AUDIT_OWNS = ["tools/check_delta_adds_no_debt.py", "tools/precommit_institutional.py"]


def _load():
    spec = importlib.util.spec_from_file_location(
        "delta_gate", REPO / "tools" / "check_delta_adds_no_debt.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GATE = _load()

BASE = {"root_cause_log": 71, "open_item_cap": 1}


def test_a_new_violation_fails_and_is_named():
    """THE PROPERTY: a check that appears on HEAD and not on base must fail, by name."""
    head = dict(BASE, checks_are_justified=1)
    added, improved = GATE.compare(BASE, head)
    assert added, "a brand-new enforced violation did not fail the delta gate"
    assert any("checks_are_justified" in a for a in added), added
    assert "0 -> 1" in added[0], added


def test_a_rise_in_an_existing_violation_also_fails():
    """Regressions arrive as +1 on an existing check as often as a new one."""
    added, _ = GATE.compare(BASE, dict(BASE, root_cause_log=72))
    assert added and "71 -> 72" in added[0], added


def test_unchanged_passes_and_improvement_passes():
    """It must not block ordinary work, or it gets switched off."""
    assert GATE.compare(BASE, dict(BASE)) == ([], [])
    added, improved = GATE.compare(BASE, dict(BASE, root_cause_log=27))
    assert added == []
    assert improved and "71 -> 27" in improved[0]


def test_a_preexisting_backlog_never_masks_a_fresh_regression():
    """The design decision that decides whether this tool survives contact.

    Base carries 72 violations; HEAD pays 44 of them AND adds one new check. A
    whole-number comparison would report a big net improvement and wave the regression
    through. Added must be reported on its own terms.
    """
    head = {"root_cause_log": 27, "open_item_cap": 1, "checks_are_justified": 1}
    added, improved = GATE.compare(BASE, head)
    assert sum(head.values()) < sum(BASE.values()), "precondition: HEAD is numerically better"
    assert added, "a regression was masked by a net-improved total"
    assert any("checks_are_justified" in a for a in added), added


def test_parser_reads_the_real_gate_output_shape():
    """Parsed from --enforced-only stdout; the separator glyph varies by console encoding."""
    for dash in ("-", "—"):
        text = (f"FAIL [root_cause_log] (ENFORCED) {dash} 71 violation(s):\n"
                f"FAIL [open_item_cap] (ENFORCED) {dash} 1 violation(s):\n"
                f"INSTITUTIONAL CORRECTNESS GATE: FAIL (72 enforced violation(s))")
        assert GATE.parse_counts(text) == {"root_cause_log": 71, "open_item_cap": 1}


def test_parser_ignores_passing_checks_and_summary_lines():
    text = ("PASS [venv_parity] (ENFORCED)\n"
            "INSTITUTIONAL CORRECTNESS GATE: FAIL (5 enforced violation(s))")
    assert GATE.parse_counts(text) == {}


def test_a_silent_or_crashed_gate_must_raise_not_report_zero(monkeypatch):
    """H1, the hole Cursor found: as first shipped this tool was FAIL-OPEN.

    enforced_counts ignored the return code and parse_counts("") is {}, so a crashed gate,
    an import error, or a changed output format rendered that side as ZERO violations —
    printing PASS and a fabricated 'PAID DOWN'. A lock that cannot tell CLEAN from SILENT
    is the RC-90 class. Each case below reproduces one way the gate can go quiet.
    """
    import subprocess as sp

    class FakeProc:
        def __init__(self, rc, out): self.returncode, self.stdout, self.stderr = rc, out, ""

    good = ("FAIL [root_cause_log] (ENFORCED) - 71 violation(s):\n"
            "INSTITUTIONAL CORRECTNESS GATE: FAIL (71 enforced violation(s))")
    cases = {
        "empty stdout (process died)": FakeProc(1, ""),
        "traceback, no banner": FakeProc(1, "Traceback (most recent call last):\nImportError"),
        "hard crash exit code": FakeProc(2, good),
        "output format changed": FakeProc(0, "FAIL [root_cause_log] 71 problems"),
    }
    for label, proc in cases.items():
        def fake_run(args, cwd=None, timeout=3600, _p=proc):
            if args[:2] == ["git", "worktree"] or args[:2] == ["git", "rev-parse"]:
                return sp.CompletedProcess(args, 0, "deadbeef\n", "")
            return _p
        monkeypatch.setattr(GATE, "_run", fake_run)
        try:
            GATE.enforced_counts("HEAD")
        except RuntimeError as exc:
            assert "silence is not cleanliness" in str(exc), (label, str(exc)[:200])
        else:
            raise AssertionError(f"{label}: a silent gate was reported as a clean count")


def test_an_unreadable_fail_is_not_a_clean_tree(monkeypatch):
    """RC-390: the residual fail-open the FIRST H1 fix missed.

    Banner present and exit code sane — the gate demonstrably RAN — but the per-check
    lines do not match the regex. counts is {} and the comparison then reports a
    fabricated 'root_cause_log: 71 -> 0 (-71)' and PASSES. Reproduced against the shipped
    code before this was fixed. A parse that disagrees with the producer's own total is a
    PARSE FAILURE, not a finding.
    """
    import subprocess as sp

    drift = ("FAIL [root_cause_log] 71 problems\n"          # regex cannot read this
             "INSTITUTIONAL CORRECTNESS GATE: FAIL (71 enforced violation(s))")
    mismatch = ("FAIL [root_cause_log] (ENFORCED) - 5 violation(s):\n"
                "INSTITUTIONAL CORRECTNESS GATE: FAIL (71 enforced violation(s))")

    for label, out in (("format drift", drift), ("sum mismatch", mismatch)):
        class FakeProc:
            returncode, stdout, stderr = 1, out, ""

        def fake_run(args, cwd=None, timeout=3600, _p=FakeProc()):
            if args[:2] in (["git", "worktree"], ["git", "rev-parse"]):
                return sp.CompletedProcess(args, 0, "deadbeef\n", "")
            return _p

        monkeypatch.setattr(GATE, "_run", fake_run)
        try:
            GATE.enforced_counts("HEAD")
        except RuntimeError as exc:
            assert "not a clean tree" in str(exc) or "disagree" in str(exc), (label, str(exc))
        else:
            raise AssertionError(f"{label}: an unreadable FAIL was reported as a count")


def test_a_completed_gate_with_zero_violations_is_still_accepted(monkeypatch):
    """Fail-closed must not mean fail-always: a genuinely clean run has the banner."""
    import subprocess as sp

    class FakeProc:
        def __init__(self): self.returncode, self.stdout, self.stderr = 0, (
            "INSTITUTIONAL CORRECTNESS GATE: PASS (enforced checks clean)"), ""

    def fake_run(args, cwd=None, timeout=3600, env=None):
        if args[:2] == ["git", "worktree"] or args[:2] == ["git", "rev-parse"]:
            return sp.CompletedProcess(args, 0, "deadbeef\n", "")
        if "-c" in args:                                  # the CHECKS roster read
            return sp.CompletedProcess(args, 0, "ROSTER_BEGIN\nvenv_parity\nROSTER_END\n", "")
        return FakeProc()

    monkeypatch.setattr(GATE, "_run", fake_run)
    counts, sha, roster = GATE.enforced_counts("HEAD")
    assert counts == {} and sha == "deadbeef" and roster == {"venv_parity"}


def test_the_tool_measures_in_a_clean_worktree_not_the_dirty_tree(monkeypatch):
    """A dirty tree carries scratch that is not the change — the source of the
    filtered-count error this tool exists to prevent.

    The first version of this control asserted that the strings "worktree", "--detach"
    and "worktree remove" appear in the tool's SOURCE. That confirmed the words were
    written, not that the measurement happens anywhere but the dirty tree: moving the
    gate subprocess back to cwd=REPO while leaving the worktree calls in place would
    have kept it green. The property is observable — every subprocess the tool launches
    passes through `_run` — so it is observed here instead.
    """
    import subprocess as sp

    calls: list[tuple[list[str], object]] = []
    banner = "INSTITUTIONAL CORRECTNESS GATE: PASS (enforced checks clean)"
    # RC-391 widened enforced_counts to also read the CHECKS roster from the SAME
    # materialised side, and an unreadable roster is fail-closed. So the stub speaks that
    # contract too; a bare banner is (correctly) refused.
    roster = "ROSTER_BEGIN\nvenv_parity\nroot_cause_log\nROSTER_END"

    def recording_run(args, cwd=None, timeout=3600):
        calls.append((list(args), cwd))
        if args[:2] == ["git", "rev-parse"]:
            return sp.CompletedProcess(args, 0, "deadbeef\n", "")
        if args[:2] == ["git", "worktree"]:
            return sp.CompletedProcess(args, 0, "", "")
        if any("ROSTER_BEGIN" in str(a) for a in args):
            return sp.CompletedProcess(args, 0, roster, "")
        return sp.CompletedProcess(args, 0, banner, "")

    monkeypatch.setattr(GATE, "_run", recording_run)
    counts, sha, roster_names = GATE.enforced_counts("HEAD")
    assert (counts, sha) == ({}, "deadbeef")
    assert roster_names, "the roster was read as empty; an unreadable roster is not empty"

    add = next((a for a, _ in calls if a[:3] == ["git", "worktree", "add"]), None)
    assert add is not None, "no worktree was materialised; the tool read some other tree"
    assert "--detach" in add, f"the worktree is not detached, so it carries a branch state: {add}"
    wt = add[-2]
    assert add[-1] == "HEAD", f"the worktree was not materialised at the requested ref: {add}"

    gate = next(((a, c) for a, c in calls
                 if any("check_institutional_correctness.py" in str(x) for x in a)), None)
    assert gate is not None, "the enforced gate was never launched"
    gate_argv, gate_cwd = gate
    assert "--enforced-only" in gate_argv, gate_argv
    # THE property: the measurement runs in the clean worktree, never in the live tree.
    assert str(gate_cwd) == str(wt), (
        f"the gate was measured in {gate_cwd!r}, not in the clean worktree {wt!r} — a "
        f"dirty tree's scratch files would be counted as part of the delta")
    assert str(gate_cwd) != str(REPO), "the gate was measured in the live repository tree"

    removed = [a for a, _ in calls if a[:3] == ["git", "worktree", "remove"]]
    assert removed and str(wt) in removed[-1], (
        f"the temporary worktree was not removed; it accumulates on disk: {calls}")


# ---------------------------------------------------------------------------
# RC-391 — the two properties the PRE-COMMIT seam needs, which HEAD-mode lacked.
# ---------------------------------------------------------------------------

def test_removing_an_enforced_check_blocks_and_cannot_read_as_paydown():
    """The blind spot in a pure count comparison, and the most valuable thing to catch.

    Base enforces root_cause_log with 71 violations. The candidate deletes that check.
    Counts alone see `71 -> 0` and print a triumphant PAID DOWN line — the comparison is
    structurally incapable of telling "fixed it" from "deleted the check that noticed".
    So the roster is compared as well, and the removal blocks.
    """
    base_roster = {"root_cause_log", "open_item_cap", "venv_parity"}
    head_roster = {"open_item_cap", "venv_parity"}

    # Precondition: counts alone WOULD have waved this through as an improvement.
    added, improved = GATE.compare(BASE, {"open_item_cap": 1})
    assert added == [] and improved and "71 -> 0" in improved[0], (added, improved)

    removed = GATE.removed_enforced_checks(base_roster, head_roster)
    assert removed == ["root_cause_log"], removed


def test_a_rename_cannot_masquerade_as_a_paydown():
    """A rename is a removal plus an addition; the removal half must still block."""
    removed = GATE.removed_enforced_checks(
        {"root_cause_log", "venv_parity"}, {"root_cause_log_v2", "venv_parity"})
    assert removed == ["root_cause_log"], removed


def test_demoting_an_enforced_check_to_advisory_blocks():
    """Advisory checks cannot fail the gate, so a demotion is a removal of enforcement."""
    assert GATE.removed_enforced_checks({"a", "b"}, {"b"}) == ["a"]


def test_an_unchanged_roster_does_not_block():
    """Zero-failure enforced checks stay VISIBLE through CHECKS, not through counts.

    A check with no violations never prints a FAIL line, so it is absent from both count
    dicts and invisible to the count comparison. It is present in both rosters, which is
    the whole reason the roster is read from CHECKS rather than inferred from output.
    """
    roster = {"venv_parity", "root_cause_log"}
    assert GATE.removed_enforced_checks(roster, set(roster)) == []
    assert "venv_parity" not in BASE, "precondition: a clean check emits no count"


def test_the_roster_is_read_from_the_repo_s_own_CHECKS_authority():
    """No second registry: the names come from check_institutional_correctness.CHECKS."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_cic_authority", REPO / "tools" / "check_institutional_correctness.py")
    cic = importlib.util.module_from_spec(spec)
    sys.modules["_cic_authority"] = cic
    spec.loader.exec_module(cic)
    authority = {name for name, _fn, enforced in cic.CHECKS if enforced}

    assert GATE.enforced_roster(REPO) == authority, (
        "the roster the delta gate reads must BE the repo's CHECKS authority")
    assert authority, "precondition: the repo declares enforced checks"


def test_an_unreadable_or_empty_roster_raises_rather_than_reporting_none():
    """Fail closed: an empty roster would make every check removal invisible."""
    for label, text in (("no sentinels", "Traceback (most recent call last):"),
                        ("empty body", "ROSTER_BEGIN\n\nROSTER_END\n")):
        try:
            GATE.parse_roster(text)
        except RuntimeError as exc:
            assert "roster" in str(exc), (label, str(exc))
        else:
            raise AssertionError(f"{label}: a broken roster read was reported as a roster")


# ---------------------------------------------------------------------------
# RC-391 — INDEX candidate, proven against real git rather than a mock.
# ---------------------------------------------------------------------------

def _git(repo, *args):
    import subprocess

    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    out = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                         encoding="utf-8", errors="replace", env=env)
    assert out.returncode == 0, (args, out.stderr)
    return out.stdout


def _seeded_repo(tmp_path):
    """A real repo whose HEAD carries kept.txt and doomed.txt."""
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "kept.txt").write_text("one\ntwo\n", encoding="utf-8")
    (repo / "doomed.txt").write_text("bye\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


def _candidate_tree(monkeypatch, repo):
    """Build the index candidate in `repo` and return {path: content} of its tree."""
    monkeypatch.setattr(GATE, "REPO", repo)
    sha = GATE.index_candidate()
    listing = _git(repo, "ls-tree", "-r", "--name-only", sha).split()
    return sha, {p: _git(repo, "show", f"{sha}:{p}") for p in listing}


def test_index_candidate_is_the_staged_tree_and_excludes_unstaged_work(tmp_path, monkeypatch):
    """The load-bearing isolation property.

    kept.txt gets a STAGED edit and then a further UNSTAGED edit on top. The candidate must
    carry the staged content exactly — not the working-tree content, which is not part of
    the commit and is how a contaminated count got quoted before. An untracked scratch file
    must not appear at all.
    """
    repo = _seeded_repo(tmp_path)
    (repo / "kept.txt").write_text("STAGED\n", encoding="utf-8")
    _git(repo, "add", "kept.txt")
    (repo / "kept.txt").write_text("UNSTAGED CONTAMINATION\n", encoding="utf-8")
    (repo / "scratch.tmp").write_text("not part of the commit\n", encoding="utf-8")

    _, tree = _candidate_tree(monkeypatch, repo)
    assert tree["kept.txt"] == "STAGED\n", tree["kept.txt"]
    assert "scratch.tmp" not in tree, sorted(tree)


def test_index_candidate_includes_staged_additions_and_deletions(tmp_path, monkeypatch):
    repo = _seeded_repo(tmp_path)
    (repo / "added.txt").write_text("new\n", encoding="utf-8")
    _git(repo, "add", "added.txt")
    _git(repo, "rm", "-q", "doomed.txt")

    _, tree = _candidate_tree(monkeypatch, repo)
    assert tree.get("added.txt") == "new\n", sorted(tree)
    assert "doomed.txt" not in tree, "a staged deletion was not carried into the candidate"


def test_index_candidate_honours_partial_staging_of_one_file(tmp_path, monkeypatch):
    """`git add -p` territory: one file, half staged. The candidate is the staged half."""
    repo = _seeded_repo(tmp_path)
    (repo / "kept.txt").write_text("one\nSTAGED-HALF\n", encoding="utf-8")
    _git(repo, "add", "kept.txt")
    (repo / "kept.txt").write_text("one\nSTAGED-HALF\nUNSTAGED-HALF\n", encoding="utf-8")

    _, tree = _candidate_tree(monkeypatch, repo)
    assert tree["kept.txt"] == "one\nSTAGED-HALF\n", tree["kept.txt"]


def test_index_candidate_is_parented_on_head_and_leaves_no_residue(tmp_path, monkeypatch):
    """MUTATION PROOF. The gate must not move HEAD, create a ref, or dirty the tree."""
    repo = _seeded_repo(tmp_path)
    (repo / "added.txt").write_text("new\n", encoding="utf-8")
    _git(repo, "add", "added.txt")

    before_head = _git(repo, "rev-parse", "HEAD").strip()
    before_refs = _git(repo, "show-ref")
    before_status = _git(repo, "status", "--porcelain")

    sha, _ = _candidate_tree(monkeypatch, repo)

    assert _git(repo, "rev-parse", f"{sha}^").strip() == before_head, (
        "the candidate must be parented on HEAD so the comparison is base -> this commit")
    assert _git(repo, "rev-parse", "HEAD").strip() == before_head, "HEAD moved"
    assert _git(repo, "show-ref") == before_refs, "the candidate left a ref behind"
    assert _git(repo, "status", "--porcelain") == before_status, "the tree was mutated"


def test_measurement_worktrees_do_not_inherit_the_caller_s_git_bindings():
    """RC-391, found by this gate firing on its OWN landing commit.

    A git hook runs with repository bindings exported, and children inherit them. With the
    seam wired in, `git diff --cached` executed INSIDE a freshly materialised measurement
    worktree read the CALLER'S index: `research_before_act` then reported the caller's
    staged files and the candidate scored +1 against its own base — contamination that
    reads as NEW DEBT and blocks honest commits. The clean detached worktree IS the
    isolation this tool rests on; an inherited GIT_INDEX_FILE silently dissolves it.
    """
    planted = {"GIT_DIR": "C:/nope/not-a-repo/.git", "GIT_INDEX_FILE": "C:/nope/index",
               "GIT_WORK_TREE": "C:/nope", "GIT_OBJECT_DIRECTORY": "C:/nope/objects"}
    previous = {k: os.environ.get(k) for k in planted}
    os.environ.update(planted)
    try:
        env = GATE._clean_env()
        leaked = [k for k in planted if k in env]
        assert not leaked, f"repository binding(s) survived scrubbing: {leaked}"
        assert "PATH" in env, "scrubbing must not gut the environment the gate needs"

        # Behavioural, not just structural: a git subprocess launched through _run must
        # ignore the planted bindings entirely. With them inherited, this call fails.
        probe = GATE._run(["git", "rev-parse", "--is-inside-work-tree"], cwd=REPO)
        assert probe.returncode == 0 and probe.stdout.strip() == "true", (
            probe.returncode, probe.stdout, probe.stderr)
    finally:
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_the_index_candidate_still_honours_an_explicit_GIT_INDEX_FILE(tmp_path, monkeypatch):
    """The other half: the CANDIDATE must read the index git is about to commit.

    Scrubbing bindings everywhere would be the mirror-image bug — git points a hook at the
    index under commit via GIT_INDEX_FILE, so the candidate must use the ambient
    environment even though the measurement worktrees must not.
    """
    repo = _seeded_repo(tmp_path)
    alt = tmp_path / "alt-index"
    monkeypatch.setenv("GIT_INDEX_FILE", str(alt))
    _git(repo, "read-tree", "HEAD")
    (repo / "only-in-alt-index.txt").write_text("staged elsewhere\n", encoding="utf-8")
    _git(repo, "add", "only-in-alt-index.txt")

    _, tree = _candidate_tree(monkeypatch, repo)
    assert "only-in-alt-index.txt" in tree, (
        "the candidate ignored the index git actually pointed it at")


def test_the_candidate_worktree_presents_the_change_as_STAGED(tmp_path, monkeypatch):
    """RC-391 second order: a check removed by ACCIDENT is still a check removed.

    Several enforced checks ask `git diff --cached` what is being committed. In a plain
    materialised worktree HEAD is the candidate and the index matches it, so that question
    answers EMPTY on both sides and those checks fall silent at the exact seam they were
    written for. `_stage_the_delta` moves HEAD back to the parent, leaving the index holding
    the candidate tree, so the staged set IS the change under commit.
    """
    repo = _seeded_repo(tmp_path)
    (repo / "added.txt").write_text("new\n", encoding="utf-8")
    _git(repo, "add", "added.txt")
    monkeypatch.setattr(GATE, "REPO", repo)
    sha = GATE.index_candidate()

    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "--detach", str(wt), sha)
    try:
        assert _git(wt, "diff", "--cached", "--name-only").split() == [], (
            "precondition: a plain materialised worktree shows NOTHING staged")
        GATE._stage_the_delta(wt, sha)
        assert _git(wt, "diff", "--cached", "--name-only").split() == ["added.txt"], (
            "the change under commit is not visible to the checks that ask for it")
        assert _git(wt, "rev-parse", "HEAD").strip() == \
            _git(repo, "rev-parse", "HEAD").strip(), "HEAD must sit at the candidate's parent"
    finally:
        _git(repo, "worktree", "remove", "--force", str(wt))


def test_local_evidence_the_checks_read_is_carried_into_the_worktree(tmp_path, monkeypatch):
    """`research_before_act` reads a GITIGNORED log; absent, it fires on every candidate."""
    assert "reports/turn_self_audit_log.jsonl" in GATE._LOCAL_EVIDENCE, GATE._LOCAL_EVIDENCE

    repo = tmp_path / "src"
    (repo / "reports").mkdir(parents=True)
    (repo / "reports" / "turn_self_audit_log.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    monkeypatch.setattr(GATE, "REPO", repo)
    GATE._copy_local_evidence(wt)

    copied = wt / "reports" / "turn_self_audit_log.jsonl"
    assert copied.is_file() and copied.read_text(encoding="utf-8") == '{"a":1}\n'


def test_the_precommit_seam_measures_the_index_against_the_trunk():
    """The wiring, not just the capability: an unwired gate blocks nothing.

    The seam previously invoked check_institutional_correctness directly, demanding ABSOLUTE
    ZERO on a repo carrying ~70 inherited violations — so it blocked every honest commit,
    including the ones paying that debt down, and got routed around.

    2026-08-17: the first form of this control matched three strings in
    precommit_institutional.py. That is a spelling check — the delta owner could be named
    in a branch that never runs, or the launch assembled through a variable, and all three
    assertions stay true while the seam blocks nothing. What the hook DOES is one
    subprocess launch, so the launch is recorded and asserted here instead.
    """
    import importlib.util
    import subprocess as sp

    spec = importlib.util.spec_from_file_location(
        "precommit_seam", REPO / "tools" / "precommit_institutional.py")
    seam = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seam)

    launches: list[list[str]] = []
    real_run = sp.run

    def recording_run(args, **kw):
        if list(args[:2]) == ["git", "rev-parse"]:
            return real_run(args, **kw)
        launches.append([str(a) for a in args])
        return sp.CompletedProcess(args, 0)

    seam.subprocess.run = recording_run
    try:
        rc = seam.main()
    finally:
        seam.subprocess.run = real_run

    assert rc == 0, "the seam did not return the gate's exit code"
    assert len(launches) == 1, f"expected exactly one gate launch, got {launches}"
    argv = launches[0]
    assert any("check_delta_adds_no_debt.py" in a for a in argv), (
        f"the seam does not run the delta owner: {argv}")
    assert "--index" in argv, f"the seam does not measure the staged index: {argv}"
    assert "--base" in argv, f"the seam does not name a base trunk: {argv}"
    assert not any("check_institutional_correctness.py" in a for a in argv), (
        f"the seam still runs the absolute-zero gate as its blocking decision: {argv}")

    # …and the gate's exit code must BE the hook's (RC-254), or a failing gate sails past.
    launches.clear()

    def failing_run(args, **kw):
        if list(args[:2]) == ["git", "rev-parse"]:
            return real_run(args, **kw)
        launches.append([str(a) for a in args])
        return sp.CompletedProcess(args, 3)

    seam.subprocess.run = failing_run
    try:
        assert seam.main() == 3, "a failing gate did not fail the hook — commits sail past"
    finally:
        seam.subprocess.run = real_run


def test_the_precommit_seam_refuses_when_no_base_trunk_resolves(monkeypatch):
    """Fail closed: no baseline must not silently mean 'nothing is new debt'."""
    import importlib.util
    import subprocess as sp

    spec = importlib.util.spec_from_file_location(
        "precommit_inst", REPO / "tools" / "precommit_institutional.py")
    seam = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seam)

    assert seam._base_ref() in ("origin/main", "main"), "a real trunk must resolve here"

    monkeypatch.setattr(seam.subprocess, "run",
                        lambda *a, **k: sp.CompletedProcess(a, 1, "", ""))
    try:
        seam._base_ref()
    except SystemExit as exc:
        assert "cannot resolve a base trunk" in str(exc), str(exc)
    else:
        raise AssertionError("an unmeasurable commit was allowed to proceed")
