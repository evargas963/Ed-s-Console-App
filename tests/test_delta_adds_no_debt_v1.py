"""RC-387 — the delta gate must FAIL a regression, or it is decoration.

Tests an author writes only encode failure modes that author imagined; the gate points the
repo's own ~35 enforced checks at a delta. The load-bearing property is asymmetry: a
comparison that cannot fail is a rubber stamp. The controls plant regressions and demand a
FAIL, plant honest paydowns and demand a PASS, and prove the three jobs the gate has kept
after 2026-09-10 (count delta, declared retirement, executed closure) in both directions.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# RC-368: declared direct owner of the tool under test.
TURN_AUDIT_OWNS = ["tools/check_delta_adds_no_debt.py"]


def _load():
    spec = importlib.util.spec_from_file_location(
        "delta_gate", REPO / "tools" / "check_delta_adds_no_debt.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GATE = _load()

BASE = {"root_cause_log": 71, "open_item_cap": 1}


# ── count delta ───────────────────────────────────────────────────────────────────────
def test_a_new_violation_fails_and_is_named():
    head = dict(BASE, checks_are_justified=1)
    added, improved = GATE.compare(BASE, head)
    assert added and any("checks_are_justified" in a for a in added) and "0 -> 1" in added[0], added


def test_a_rise_in_an_existing_violation_also_fails():
    added, _ = GATE.compare(BASE, dict(BASE, root_cause_log=72))
    assert added and "71 -> 72" in added[0], added


def test_unchanged_passes_and_improvement_passes():
    assert GATE.compare(BASE, dict(BASE)) == ([], [])
    added, improved = GATE.compare(BASE, dict(BASE, root_cause_log=27))
    assert added == [] and improved and "71 -> 27" in improved[0]


def test_a_preexisting_backlog_never_masks_a_fresh_regression():
    head = {"root_cause_log": 27, "open_item_cap": 1, "checks_are_justified": 1}
    added, _ = GATE.compare(BASE, head)
    assert sum(head.values()) < sum(BASE.values()), "precondition: HEAD is numerically better"
    assert added and any("checks_are_justified" in a for a in added), added


def test_parser_reads_the_real_gate_output_shape():
    for dash in ("-", "—"):
        text = (f"FAIL [root_cause_log] (ENFORCED) {dash} 71 violation(s):\n"
                f"FAIL [open_item_cap] (ENFORCED) {dash} 1 violation(s):\n"
                f"INSTITUTIONAL CORRECTNESS GATE: FAIL (72 enforced violation(s))")
        assert GATE.parse_counts(text) == {"root_cause_log": 71, "open_item_cap": 1}
    assert GATE.parse_counts("PASS [venv_parity] (ENFORCED)\nINSTITUTIONAL CORRECTNESS GATE: FAIL (5 enforced violation(s))") == {}


def test_a_silent_or_crashed_gate_must_raise_not_report_zero(monkeypatch):
    """H1: a crashed gate, an import error or a changed output format must never read as
    ZERO violations (the RC-90 class: a lock that cannot tell CLEAN from SILENT)."""
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
        def fake_run(args, cwd=None, timeout=3600, _p=proc, env=None):
            if args[:2] in (["git", "worktree"], ["git", "rev-parse"]):
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
    """RC-390: banner present, exit code sane, but the per-check lines do not parse — a
    parse that disagrees with the producer's own total is a PARSE FAILURE, not a finding."""
    import subprocess as sp

    drift = "FAIL [root_cause_log] 71 problems\nINSTITUTIONAL CORRECTNESS GATE: FAIL (71 enforced violation(s))"
    mismatch = ("FAIL [root_cause_log] (ENFORCED) - 5 violation(s):\n"
                "INSTITUTIONAL CORRECTNESS GATE: FAIL (71 enforced violation(s))")
    for label, out in (("format drift", drift), ("sum mismatch", mismatch)):
        def fake_run(args, cwd=None, timeout=3600, env=None, _out=out):
            if args[:2] in (["git", "worktree"], ["git", "rev-parse"]):
                return sp.CompletedProcess(args, 0, "deadbeef\n", "")
            return sp.CompletedProcess(args, 1, _out, "")
        monkeypatch.setattr(GATE, "_run", fake_run)
        try:
            GATE.enforced_counts("HEAD")
        except RuntimeError as exc:
            assert "not a clean tree" in str(exc) or "disagree" in str(exc), (label, str(exc))
        else:
            raise AssertionError(f"{label}: an unreadable FAIL was reported as a count")


def test_the_tool_measures_in_a_clean_worktree_not_the_dirty_tree(monkeypatch):
    """Every subprocess the tool launches passes through `_run`; the gate must run with the
    materialised detached worktree as cwd, never the live tree, and remove it after."""
    import subprocess as sp

    calls: list[tuple[list[str], object]] = []
    banner = "INSTITUTIONAL CORRECTNESS GATE: PASS (enforced checks clean)"

    def recording_run(args, cwd=None, timeout=3600, env=None):
        calls.append((list(args), cwd))
        if args[:2] == ["git", "rev-parse"]:
            return sp.CompletedProcess(args, 0, "deadbeef\n", "")
        if args[:2] == ["git", "worktree"]:
            return sp.CompletedProcess(args, 0, "", "")
        return sp.CompletedProcess(args, 0, banner, "")

    monkeypatch.setattr(GATE, "_run", recording_run)
    monkeypatch.setattr(GATE, "enforced_roster", lambda wt: {"venv_parity", "root_cause_log"})
    counts, sha, roster = GATE.enforced_counts("HEAD")
    assert (counts, sha) == ({}, "deadbeef") and roster
    add = next(a for a, _ in calls if a[:3] == ["git", "worktree", "add"])
    assert "--detach" in add and add[-1] == "HEAD"
    wt = add[-2]
    gate_argv, gate_cwd = next((a, c) for a, c in calls if any("check_institutional_correctness.py" in str(x) for x in a))
    assert "--enforced-only" in gate_argv and str(gate_cwd) == str(wt) and str(gate_cwd) != str(REPO)
    removed = [a for a, _ in calls if a[:3] == ["git", "worktree", "remove"]]
    assert removed and str(wt) in removed[-1]


def test_each_tree_is_measured_in_its_own_process_never_imported(tmp_path):
    """CROSS-TREE IMPORT ISOLATION (RC-546 finding B): base and candidate are never loaded
    into the judge's interpreter. Two trees whose checkers print different verdicts are
    measured by `run_gate` as two subprocesses with cwd set to each tree, and the gate module
    itself imports no checker. (The deleted judge loaded both trees' modules into one process
    with `sys.path` order as the only isolation.)"""
    for name, n in (("a", 3), ("b", 5)):
        tree = tmp_path / name / "tools"
        tree.mkdir(parents=True)
        (tree / "check_institutional_correctness.py").write_text(
            "import sys\n"
            f"print('FAIL [root_cause_log] (ENFORCED) - {n} violation(s):')\n"
            f"print('INSTITUTIONAL CORRECTNESS GATE: FAIL ({n} enforced violation(s))')\n"
            "sys.exit(1)\n", encoding="utf-8")
    assert GATE.run_gate(tmp_path / "a", "a") == {"root_cause_log": 3}
    assert GATE.run_gate(tmp_path / "b", "b") == {"root_cause_log": 5}
    assert GATE.run_gate(tmp_path / "a", "a") == {"root_cause_log": 3}   # no cached module wins
    src = (REPO / "tools" / "check_delta_adds_no_debt.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = {getattr(n, "module", None) or a.name for n in ast.walk(tree)
                if isinstance(n, (ast.Import, ast.ImportFrom)) for a in getattr(n, "names", [])}
    assert not any("check_institutional" in str(m) for m in imported), imported
    assert "sys.path.insert" not in src and "load_tree_module" not in src


# ── the roster and the declared retirement (RC-391 / the base-side contract's successor) ──
def test_the_roster_is_read_statically_from_the_repo_s_own_CHECKS_authority():
    spec = importlib.util.spec_from_file_location("_cic_authority", REPO / "tools" / "check_institutional_correctness.py")
    cic = importlib.util.module_from_spec(spec)
    sys.modules["_cic_authority"] = cic
    spec.loader.exec_module(cic)
    authority = {name for name, _fn, enforced in cic.CHECKS if enforced}
    assert GATE.enforced_roster(REPO) == authority and authority
    assert GATE.declared_retirements(REPO) == cic.RETIRED_CHECKS


def test_an_unreadable_or_empty_roster_raises_rather_than_reporting_none(tmp_path):
    for label, text in (("not python", "Traceback (most recent call last):"), ("no CHECKS", "x = 1\n"),
                        ("empty CHECKS", "CHECKS = []\n")):
        (tmp_path / "tools").mkdir(exist_ok=True)
        (tmp_path / GATE.CHECKER_REL).write_text(text, encoding="utf-8")
        try:
            GATE.enforced_roster(tmp_path)
        except RuntimeError as exc:
            assert "roster" in str(exc), (label, str(exc))
        else:
            raise AssertionError(f"{label}: a broken roster read was reported as a roster")


def test_removing_an_enforced_check_blocks_and_cannot_read_as_paydown():
    """Counts alone see `71 -> 0` and print PAID DOWN; the roster comparison refuses it."""
    added, improved = GATE.compare(BASE, {"open_item_cap": 1})
    assert added == [] and improved and "71 -> 0" in improved[0]
    assert GATE.removed_enforced_checks({"root_cause_log", "open_item_cap", "venv_parity"}, {"open_item_cap", "venv_parity"}) == ["root_cause_log"]
    assert GATE.removed_enforced_checks({"root_cause_log", "venv_parity"}, {"root_cause_log_v2", "venv_parity"}) == ["root_cause_log"]
    assert GATE.removed_enforced_checks({"a", "b"}, {"b"}) == ["a"]
    assert GATE.removed_enforced_checks({"a", "b"}, {"a", "b"}) == []


def test_a_retirement_is_declared_in_the_checker_and_read_from_the_candidate(tmp_path):
    """The declaration lives in the same file and the same diff as the removal, so review
    sees it; an undeclared removal keeps blocking. (Replaces the base-side `retire:` contract
    rows and their executor, deleted 2026-09-10 — a two-step base authorization added nothing
    against the operator's own credential and needed a policy engine to read it.)"""
    (tmp_path / "tools").mkdir()
    (tmp_path / GATE.CHECKER_REL).write_text(
        'CHECKS = [("a_check", check_a, True), ("c_check", check_c, False)]\n'
        'RETIRED_CHECKS: dict[str, str] = {"b_check": "folded into a_check", "z_check": "no consumer"}\n',
        encoding="utf-8")
    assert GATE.enforced_roster(tmp_path) == {"a_check"}
    assert GATE.declared_retirements(tmp_path) == {"b_check": "folded into a_check", "z_check": "no consumer"}
    removed = GATE.removed_enforced_checks({"a_check", "b_check", "q_check"}, GATE.enforced_roster(tmp_path))
    retired, blocked = GATE.split_removals(removed, set(GATE.declared_retirements(tmp_path)))
    assert retired == ["b_check"] and blocked == ["q_check"], "undeclared removal must keep blocking"
    assert GATE.split_removals(removed, set()) == ([], ["b_check", "q_check"])


def test_fold_moves_exactly_the_base_standing_debt_to_the_survivor():
    base = {"rc_numeric": 22, "root_cause_log": 52}
    out, moved = GATE.refold_base_counts(base, {"rc_numeric": "root_cause_log"}, retired={"rc_numeric"}, head_roster={"root_cause_log"})
    assert out == {"root_cause_log": 74} and len(moved) == 1
    assert GATE.compare(out, {"root_cause_log": 74}) == ([], [])
    assert GATE.compare(out, {"root_cause_log": 75})[0] == ["  root_cause_log: 74 -> 75  (+1)"]
    # fail-closed: not retired, no fold declared, or survivor not enforced -> nothing moves
    assert GATE.refold_base_counts(base, {"rc_numeric": "root_cause_log"}, set(), {"root_cause_log", "rc_numeric"}) == (base, [])
    assert GATE.refold_base_counts(base, {}, {"rc_numeric"}, {"root_cause_log"}) == (base, [])
    assert GATE.refold_base_counts(base, {"rc_numeric": "root_cause_log"}, {"rc_numeric"}, {"open_item_cap"}) == (base, [])


def test_declarations_only_touch_removal_accounting_and_come_from_the_candidate():
    """A retirement excuses a REMOVAL only; compare() never consults it, so a declaration
    cannot excuse a violation being ADDED. And main() reads the declaration from the
    candidate worktree (the diff under review), never from a base-side registry."""
    src_main = inspect.getsource(GATE.main)
    fn = ast.parse(src_main).body[0]
    decl = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "declared_retirements"]
    assert len(decl) == 1 and getattr(decl[0].args[0], "id", "") == "cand_wt"
    assert "declared_retirements" not in inspect.getsource(GATE.compare)
    code = inspect.getsource(GATE).split('"""', 2)[-1]          # past the module docstring
    assert "OPEN_ITEMS" not in code and "--trusted" not in code and "contract" not in code


# ── executed closure (RC-540 / RC-545) ────────────────────────────────────────────────
def test_closure_commands_are_executed_not_matched(tmp_path):
    good = "| RC-9001 | CLOSED | 2026-09-10 | 2026-09-11 | d | w -> ROOT | fixed. `python -c pass` |"
    bad = '| RC-9002 | CLOSED | 2026-09-10 | 2026-09-11 | d | w -> ROOT | fixed. `python -c "import sys; sys.exit(3)"` |'
    live = "| RC-9003 | CLOSED | 2026-09-10 | 2026-09-11 | d | w -> ROOT | fixed. `curl -s http://127.0.0.1:8000/api/build` |"
    named = "| RC-9004 | CLOSED | 2026-09-10 | 2026-09-11 | d | w -> ROOT | edited `pytest.yml`; `tools/stop_chain.py` shrank; proof `python -c pass` |"
    assert GATE.executable_commands(good) == ["python -c pass"]
    assert GATE.executable_commands(live) == []
    assert GATE.executable_commands(named) == ["python -c pass"], "a backticked file name is a mention"
    assert GATE.executable_commands("| RC-9006 | CLOSED | d | d | d | w | see `tools/check_delta_adds_no_debt.py --base origin/main` |") == []
    assert GATE.run_closure_command(GATE.executable_commands(good)[0], tmp_path)[0] == 0
    assert GATE.run_closure_command(GATE.executable_commands(bad)[0], tmp_path)[0] == 3
    base = "| RC-9001 | OPEN | 2026-09-10 | 2026-09-11 | d | w | in progress |\n"
    cand = "\n".join([good, bad, live]) + "\n"
    closing = GATE.closing_rows(base, cand)
    assert sorted(closing) == ["RC-9001", "RC-9002", "RC-9003"]
    assert GATE.executable_commands(closing["RC-9001"]) == ["python -c pass"]
    assert GATE.closing_rows(cand, cand) == {}


def test_execute_closures_fails_the_failing_and_live_only_rows_and_passes_the_good_one(tmp_path, monkeypatch):
    good = "| RC-9001 | CLOSED | 2026-09-10 | 2026-09-11 | d | w -> ROOT | fixed. `python -c pass` |"
    bad = '| RC-9002 | CLOSED | 2026-09-10 | 2026-09-11 | d | w -> ROOT | fixed. `python -c "import sys; sys.exit(3)"` |'
    live = "| RC-9003 | CLOSED | 2026-09-10 | 2026-09-11 | d | w -> ROOT | fixed. `curl -s http://x` |"
    (tmp_path / "governance").mkdir()
    (tmp_path / "governance" / "root_cause_log.md").write_text("\n".join([good, bad, live]) + "\n", encoding="utf-8")
    monkeypatch.setattr(GATE, "_show", lambda ref, rel: "| RC-9001 | OPEN | d | d | d | w | wip |\n")
    failures = GATE.execute_closures("origin/main", tmp_path)
    assert [f.split(":")[0].split(" ")[0] for f in failures] == ["RC-9002", "RC-9003"], failures


# ── the index candidate (RC-391), proven against real git ─────────────────────────────
def _git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    out = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    assert out.returncode == 0, (args, out.stderr)
    return out.stdout


def _seeded_repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "kept.txt").write_text("one\ntwo\n", encoding="utf-8")
    (repo / "doomed.txt").write_text("bye\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


def _candidate_tree(monkeypatch, repo):
    monkeypatch.setattr(GATE, "REPO", repo)
    sha = GATE.index_candidate()
    listing = _git(repo, "ls-tree", "-r", "--name-only", sha).split()
    return sha, {p: _git(repo, "show", f"{sha}:{p}") for p in listing}


def test_index_candidate_is_the_staged_tree_and_excludes_unstaged_work(tmp_path, monkeypatch):
    repo = _seeded_repo(tmp_path)
    (repo / "kept.txt").write_text("STAGED\n", encoding="utf-8")
    _git(repo, "add", "kept.txt")
    (repo / "kept.txt").write_text("UNSTAGED CONTAMINATION\n", encoding="utf-8")
    (repo / "scratch.tmp").write_text("not part of the commit\n", encoding="utf-8")
    _, tree = _candidate_tree(monkeypatch, repo)
    assert tree["kept.txt"] == "STAGED\n" and "scratch.tmp" not in tree


def test_index_candidate_includes_staged_additions_and_deletions_and_partial_staging(tmp_path, monkeypatch):
    repo = _seeded_repo(tmp_path)
    (repo / "added.txt").write_text("new\n", encoding="utf-8")
    _git(repo, "add", "added.txt")
    _git(repo, "rm", "-q", "doomed.txt")
    (repo / "kept.txt").write_text("one\nSTAGED-HALF\n", encoding="utf-8")
    _git(repo, "add", "kept.txt")
    (repo / "kept.txt").write_text("one\nSTAGED-HALF\nUNSTAGED-HALF\n", encoding="utf-8")
    _, tree = _candidate_tree(monkeypatch, repo)
    assert tree.get("added.txt") == "new\n" and "doomed.txt" not in tree and tree["kept.txt"] == "one\nSTAGED-HALF\n"


def test_index_candidate_is_parented_on_head_and_leaves_no_residue(tmp_path, monkeypatch):
    repo = _seeded_repo(tmp_path)
    (repo / "added.txt").write_text("new\n", encoding="utf-8")
    _git(repo, "add", "added.txt")
    before_head, before_refs, before_status = (_git(repo, "rev-parse", "HEAD").strip(), _git(repo, "show-ref"), _git(repo, "status", "--porcelain"))
    sha, _ = _candidate_tree(monkeypatch, repo)
    assert _git(repo, "rev-parse", f"{sha}^").strip() == before_head
    assert _git(repo, "rev-parse", "HEAD").strip() == before_head and _git(repo, "show-ref") == before_refs
    assert _git(repo, "status", "--porcelain") == before_status


def test_measurement_worktrees_do_not_inherit_the_caller_s_git_bindings():
    """RC-391: a hook exports GIT_INDEX_FILE etc.; the measurement worktrees must not see them."""
    planted = {"GIT_DIR": "C:/nope/not-a-repo/.git", "GIT_INDEX_FILE": "C:/nope/index",
               "GIT_WORK_TREE": "C:/nope", "GIT_OBJECT_DIRECTORY": "C:/nope/objects"}
    previous = {k: os.environ.get(k) for k in planted}
    os.environ.update(planted)
    try:
        env = GATE._clean_env()
        assert not [k for k in planted if k in env] and "PATH" in env
        probe = GATE._run(["git", "rev-parse", "--is-inside-work-tree"], cwd=REPO)
        assert probe.returncode == 0 and probe.stdout.strip() == "true", (probe.returncode, probe.stderr)
    finally:
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_the_index_candidate_still_honours_an_explicit_GIT_INDEX_FILE(tmp_path, monkeypatch):
    repo = _seeded_repo(tmp_path)
    alt = tmp_path / "alt-index"
    monkeypatch.setenv("GIT_INDEX_FILE", str(alt))
    _git(repo, "read-tree", "HEAD")
    (repo / "only-in-alt-index.txt").write_text("staged elsewhere\n", encoding="utf-8")
    _git(repo, "add", "only-in-alt-index.txt")
    _, tree = _candidate_tree(monkeypatch, repo)
    assert "only-in-alt-index.txt" in tree


def test_the_candidate_worktree_presents_the_change_as_STAGED(tmp_path, monkeypatch):
    repo = _seeded_repo(tmp_path)
    (repo / "added.txt").write_text("new\n", encoding="utf-8")
    _git(repo, "add", "added.txt")
    monkeypatch.setattr(GATE, "REPO", repo)
    sha = GATE.index_candidate()
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "--detach", str(wt), sha)
    try:
        assert _git(wt, "diff", "--cached", "--name-only").split() == []
        GATE._stage(wt, f"{sha}^")
        assert _git(wt, "diff", "--cached", "--name-only").split() == ["added.txt"]
        assert _git(wt, "rev-parse", "HEAD").strip() == _git(repo, "rev-parse", "HEAD").strip()
    finally:
        _git(repo, "worktree", "remove", "--force", str(wt))


# ── wiring ────────────────────────────────────────────────────────────────────────────
def test_the_required_hardening_job_uses_the_debt_owner_and_no_trusted_lane_exists():
    wf = (REPO / ".github" / "workflows" / "hardening.yml").read_text(encoding="utf-8")
    blocking = [ln for ln in wf.splitlines() if ln.strip().startswith(("run:", "python "))]
    joined = "\n".join(blocking)
    assert "check_delta_adds_no_debt.py" in joined and "--base" in joined
    assert not any("check_institutional_correctness.py" in ln for ln in blocking)
    assert not (REPO / ".github" / "workflows" / "trusted-closure.yml").exists()
    assert not (REPO / "governance" / "acceptance.py").exists()
    assert not (REPO / "tools" / "precommit_institutional.py").exists()
    for retired in ("trusted_main", "overlay", "trust_anchor", "contract_regressions", "_base_cache_key", "parse_roster"):
        assert not hasattr(GATE, retired), retired


def test_ci_never_fabricates_an_agent_identity():
    """RC-396: a GitHub runner has no agent identity, so it must not export one."""
    import re as _re
    for wf in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        code = [ln for ln in wf.read_text(encoding="utf-8").splitlines() if not ln.strip().startswith("#")]
        for ln in code:
            assert _re.search(r"ED_AGENT_ROLE\s*:\s*(\S+)", ln) is None, (wf.name, ln)
