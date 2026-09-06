"""RC-512 — who governs an agent event, and every way that answer can be gamed.

Every test drives the REAL `tools/stop_chain.py` in a REAL git repository with REAL linked
worktrees, over a real subprocess boundary. Nothing is mocked, because the defect was never in
anyone's model of the system — it was in which copy of the code actually ran.

THE SHAPE, reproduced rather than described. `.claude/settings.json` registers the hook as a
command relative to the session project directory, so the chain, its guards and their ledgers
all came from whichever checkout the session was launched in. On 2026-09-03 that checkout was
the production desk, 9 commits behind origin/main, and it ran `tools/proof_only_guard.py` — a
guard `main` had already DELETED for false-blocking a denial (RC-504) — against a turn whose
work was in a different worktree entirely.

So `primary` below carries a guard that ALWAYS BLOCKS, standing in for exactly that: a rule
the current tree no longer has. `alpha` and `beta` are linked worktrees whose guard content
each test chooses. If authority resolves correctly, work in a live worktree is never judged by
`primary`'s withdrawn rule, and no arrangement of session history lets an agent pick its judge.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
REAL_CHAIN = REPO / "tools" / "stop_chain.py"

BLOCKING_GUARD = '''"""Stands in for a rule the authority tree no longer carries."""
import sys


def main() -> int:
    sys.stderr.write("BLOCKED BY %s\\n" % __file__.replace("\\\\", "/").split("/")[-3])
    return 2
'''

PASSING_GUARD = '''"""The same guard as a current tree carries it: it does not fire."""


def main() -> int:
    return 0
'''


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if r.returncode != 0 and args[0] not in ("status", "rev-parse"):
        raise AssertionError(f"git {args} in {cwd}: {r.stderr}")
    return r


def _chain_modules() -> list[str]:
    """The chain plus everything it imports from `tools/`, resolved rather than listed.

    Copied REAL into each scratch tree, not stubbed: a tree missing them would exercise the
    ImportError path instead of the shell resolver, and every real worktree of this repo has
    them. Computed transitively so adding an import to the chain cannot silently turn these
    attacks into tests of the degraded path.
    """
    seen: set[str] = set()
    frontier = ["stop_chain", "operator_law_guard", "process_lock_guard"]
    while frontier:
        mod = frontier.pop()
        if mod in seen:
            continue
        seen.add(mod)
        src = REPO / "tools" / f"{mod}.py"
        if not src.is_file():
            continue
        for node in ast.walk(ast.parse(src.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            frontier += [n.split(".", 1)[1] for n in names if n.startswith("tools.")]
    return sorted(m for m in seen if (REPO / "tools" / f"{m}.py").is_file())


def _install_chain(tree: Path, guard_body: str) -> None:
    tools = tree / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    (tools / "__init__.py").write_text("", encoding="utf-8")
    for mod in _chain_modules():
        (tools / f"{mod}.py").write_bytes((REPO / "tools" / f"{mod}.py").read_bytes())
    (tools / "demo_guard.py").write_text(guard_body, encoding="utf-8")


def _commit_all(tree: Path, msg: str) -> None:
    _git(tree, "add", "-A")
    _git(tree, "commit", "-m", msg)


@pytest.fixture()
def trees(tmp_path):
    """A primary checkout and two linked worktrees of ONE repository.

    `primary` stands in for the production desk the session was launched from and carries the
    withdrawn rule. `alpha` and `beta` are where work actually happens.
    """
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "init", "-b", "main")
    _git(primary, "config", "user.email", "t@t.t")
    _git(primary, "config", "user.name", "t")
    _git(primary, "config", "core.autocrlf", "false")
    _install_chain(primary, BLOCKING_GUARD)
    _commit_all(primary, "primary: carries the stale blocking rule")

    made = {}
    for name, guard in (("alpha", PASSING_GUARD), ("beta", PASSING_GUARD)):
        path = tmp_path / name
        _git(primary, "worktree", "add", "-b", name, str(path))
        _install_chain(path, guard)
        _commit_all(path, f"{name}: the rule does not fire here")
        made[name] = path
    return primary, made["alpha"], made["beta"]


def set_guard(tree: Path, body: str, *, commit: bool = True) -> None:
    (tree / "tools" / "demo_guard.py").write_text(body, encoding="utf-8")
    if commit:
        _commit_all(tree, "guard change")


def run_from(tree: Path, payload: dict, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke the chain the way the hook does: a roster on argv, the payload on stdin."""
    env = dict(os.environ)
    env.pop("ED_GOVERNANCE_AUTHORITY_DELEGATED", None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(tree / "tools" / "stop_chain.py"), "tools/demo_guard.py"],
        cwd=str(tree), input=json.dumps(payload), text=True, capture_output=True,
        env=env, timeout=600,
    )


def tool_use(name: str, path: Path) -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": name, "input": {"file_path": str(path)}}]}}


def bash_use(command: str) -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": command}}]}}


def prose(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def write_transcript(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def stop_payload(transcript: Path | None = None) -> dict:
    out = {"hook_event_name": "Stop", "stop_hook_active": False}
    if transcript is not None:
        out["transcript_path"] = str(transcript)
    return out


# ============================================================ the two resolution shapes

def test_a_file_payload_is_judged_by_the_tree_the_file_is_in(trees):
    """The stale tree runs the hook; the work is elsewhere; the withdrawn rule must not fire."""
    primary, alpha, _beta = trees
    result = run_from(primary, {
        "tool_name": "Edit", "tool_input": {"file_path": str(alpha / "app.py")}})
    assert result.returncode == 0, (
        "work in a linked worktree was judged by the stale tree's withdrawn rule — this is the "
        f"2026-09-03 false block, unfixed.\nSTDERR:\n{result.stderr}")
    assert "BLOCKED BY primary" not in result.stderr, result.stderr


def test_a_stop_event_is_judged_by_the_tree_the_session_worked_in(trees, tmp_path):
    """The half a no-file event needs: the session's own record of where its work went."""
    primary, alpha, _beta = trees
    t = write_transcript(tmp_path / "s.jsonl", [tool_use("Edit", alpha / "app.py")])
    result = run_from(primary, stop_payload(t))
    assert result.returncode == 0, (
        "a Stop event was judged by the tree the session was LAUNCHED in rather than the tree "
        f"it WORKED in.\nSTDERR:\n{result.stderr}")
    assert "BLOCKED BY primary" not in result.stderr, result.stderr


# ================================================================== ATTACK: reads are not work

def test_a_read_in_a_stale_tree_cannot_take_authority_from_an_edit_in_another(trees, tmp_path):
    """ATTACK 1. Edit in A, then Read in stale B -> A still governs.

    The first cut accepted any tool_use carrying a path, so ending a turn with a Read inside a
    stale checkout handed that checkout the verdict. Looking at a file is not working in it.
    """
    primary, alpha, _beta = trees
    t = write_transcript(tmp_path / "s.jsonl", [
        tool_use("Edit", alpha / "app.py"),
        tool_use("Read", primary / "tools" / "demo_guard.py"),
        tool_use("Grep", primary / "tools" / "stop_chain.py"),
        tool_use("Glob", primary / "app.py"),
    ])
    result = run_from(primary, stop_payload(t))
    assert result.returncode == 0, (
        "a READ nominated the tree that judges the turn — an agent can choose its own judge "
        f"with one inspection.\nSTDERR:\n{result.stderr}")
    assert "BLOCKED BY primary" not in result.stderr, result.stderr


def test_prose_that_merely_quotes_a_path_is_not_a_place_work_happened(trees, tmp_path):
    """Transcript resolution reads TOOL TARGETS, not assistant text."""
    primary, alpha, _beta = trees
    t = write_transcript(tmp_path / "s.jsonl", [
        prose(f"I considered editing {alpha / 'app.py'} but did not."),
    ])
    result = run_from(primary, stop_payload(t))
    assert result.returncode != 0, (
        "a path merely MENTIONED in assistant prose was accepted as the session's work tree")
    assert "BLOCKED BY primary" in result.stderr, result.stderr


# ======================================================= ATTACK: Bash as a mutation channel
#
# The roster once excluded Bash on the written claim that this repo already refuses shell
# writes to governed state. That claim was FALSE and the operator caught it: operator_law_guard
# permits heredoc and `-c` writes to .md/.json/.jsonl/.txt/.csv/.log and names governance-row
# edits as a legitimate shell-write case. Governance ledgers are .md. So the sanctioned path
# was an untracked mutation channel, and Stop fell back to the launch checkout through it.

def test_a_bash_write_to_an_allowed_data_file_puts_that_worktree_in_the_set(trees, tmp_path):
    """ATTACK 8. Bash writes an allowed .md / .json in worktree A -> Stop must include A."""
    primary, alpha, _beta = trees
    for command in (f'echo "| RC-999 | OPEN |" >> "{alpha / "governance_row.md"}"',
                    f'printf "{{}}" > "{alpha / "artifact.json"}"'):
        t = write_transcript(tmp_path / "s.jsonl", [bash_use(command)])
        result = run_from(primary, stop_payload(t))
        assert result.returncode == 0, (
            "a shell write to a SANCTIONED data extension did not put its worktree in the "
            f"authority set, so Stop fell back to the launch checkout.\ncmd: {command}\n"
            f"STDERR:\n{result.stderr}")
        assert "BLOCKED BY primary" not in result.stderr, result.stderr


def test_a_bash_mutation_and_an_edit_in_different_trees_are_both_adjudicated(trees, tmp_path):
    """ATTACK 9. Bash mutates A, Edit mutates B, one authority blocks -> Stop blocks.

    The BASH-touched tree is the blocking one and the Edit-touched tree passes, so a resolver
    that sees only file-target tools clears the turn.
    """
    primary, alpha, beta = trees
    set_guard(beta, BLOCKING_GUARD)
    t = write_transcript(tmp_path / "s.jsonl", [
        bash_use(f'echo hi >> "{beta / "notes.md"}"'),
        tool_use("Edit", alpha / "app.py"),
    ])
    result = run_from(primary, stop_payload(t))
    assert result.returncode != 0, (
        "a worktree materially changed only through Bash never entered adjudication.\n"
        f"STDERR:\n{result.stderr}")
    assert "BLOCKED BY beta" in result.stderr, result.stderr


def test_a_git_dash_c_operation_is_not_judged_solely_by_the_launch_tree(trees, tmp_path):
    """ATTACK 10. `git -C <worktree>` material operation.

    `git -C alpha commit` changes alpha, not the tree the session was launched in. The target
    is resolved by process_lock_guard's own git parser, so `-C` is not re-parsed here.
    """
    primary, alpha, _beta = trees
    for command in (f'git -C "{alpha}" commit --allow-empty -m x',
                    f'git -C "{alpha}" merge --ff-only origin/main'):
        t = write_transcript(tmp_path / "s.jsonl", [bash_use(command)])
        result = run_from(primary, stop_payload(t))
        assert result.returncode == 0, (
            f"a git operation aimed at another worktree was judged by the launch tree.\n"
            f"cmd: {command}\nSTDERR:\n{result.stderr}")
        assert "BLOCKED BY primary" not in result.stderr, result.stderr


def test_a_harmless_bash_read_establishes_no_worktree(trees, tmp_path):
    """ATTACK 11. Inspection is not work — including through the shell.

    The counterpart to attack 8: treating Bash as a mutation channel must not degrade into
    treating every shell command as one. Edit in alpha, then read inside the stale primary;
    alpha must still govern.
    """
    primary, alpha, _beta = trees
    t = write_transcript(tmp_path / "s.jsonl", [
        tool_use("Edit", alpha / "app.py"),
        bash_use(f'cat "{primary / "tools" / "demo_guard.py"}"'),
        bash_use(f'git -C "{primary}" status --porcelain'),
        bash_use(f'ls -la "{primary}"'),
    ])
    result = run_from(primary, stop_payload(t))
    assert result.returncode == 0, (
        "a harmless shell READ established a worktree and took authority from the tree where "
        f"work actually happened.\nSTDERR:\n{result.stderr}")
    assert "BLOCKED BY primary" not in result.stderr, result.stderr


def test_a_mutating_bash_action_with_no_locatable_tree_fails_explicitly(trees, tmp_path):
    """ATTACK 12. `git apply` rewrites tracked files it never names.

    With no working directory to resolve it against, the tree it changed cannot be named. That
    is exactly when falling back to the launch checkout is the defect, so the event is refused
    and the reason is printed.
    """
    primary, _alpha, _beta = trees
    t = write_transcript(tmp_path / "s.jsonl", [bash_use("git apply /tmp/some.patch")])
    result = run_from(primary, stop_payload(t))       # no `cwd` in the payload, by design
    assert result.returncode != 0
    assert "REFUSED" in result.stderr, result.stderr
    assert "cannot determine" in result.stderr, result.stderr


# ============================================ ATTACK: a session that touched several worktrees

def test_every_materially_touched_worktree_is_adjudicated_and_the_worst_verdict_wins(trees, tmp_path):
    """ATTACK 2. Mutations in A and B, one blocks -> Stop blocks.

    The BLOCKING tree is the first one touched and the passing tree is the last, so a resolver
    that collapses to a single tree by recency clears the turn. Both are judged; worst wins.
    """
    primary, alpha, beta = trees
    set_guard(alpha, BLOCKING_GUARD)
    t = write_transcript(tmp_path / "s.jsonl", [
        tool_use("Edit", alpha / "app.py"),
        tool_use("Write", beta / "other.py"),
    ])
    result = run_from(primary, stop_payload(t))
    assert result.returncode != 0, (
        "a session that materially modified two worktrees was cleared because the LAST one "
        f"passed.\nSTDERR:\n{result.stderr}")
    assert "BLOCKED BY alpha" in result.stderr, result.stderr


def test_a_harmless_final_mutation_cannot_hide_earlier_governed_work(trees, tmp_path):
    """ATTACK 3. The earlier cut took the MOST RECENT target.

    So: do the governed work in B, then finish with one innocuous write in A. Taking the last
    target clears the turn. Work in B does not stop having happened because something later
    happened in A.
    """
    primary, alpha, beta = trees
    set_guard(beta, BLOCKING_GUARD)
    t = write_transcript(tmp_path / "s.jsonl", [
        tool_use("Edit", beta / "the_real_work.py"),
        prose("now something harmless"),
        tool_use("Write", alpha / "notes.txt"),
    ])
    result = run_from(primary, stop_payload(t))
    assert result.returncode != 0, (
        "a trailing harmless write in another worktree buried the tree where the governed work "
        f"actually happened.\nSTDERR:\n{result.stderr}")
    assert "BLOCKED BY beta" in result.stderr, result.stderr


def test_a_real_mutation_older_than_the_old_tail_window_cannot_disappear(trees, tmp_path):
    """ATTACK 4. The earlier cut read a fixed 2 MB tail.

    So: put the governed mutation first, then push it out of the window with bulk, then finish
    innocently. Under a tail read the blocking tree is invisible and the turn falls back to
    bootstrap authority silently — the failure mode is a QUIET pass, which is the worst kind.
    """
    primary, alpha, beta = trees
    set_guard(beta, BLOCKING_GUARD)
    padding = [prose("x" * 4000) for _ in range(700)]        # ~2.8 MB, past the old 2 MB tail
    t = write_transcript(tmp_path / "s.jsonl", [
        tool_use("Edit", beta / "the_real_work.py"),
        *padding,
        tool_use("Write", alpha / "notes.txt"),
    ])
    assert t.stat().st_size > 2_000_000, f"padding did not exceed the old window: {t.stat().st_size}"
    result = run_from(primary, stop_payload(t))
    assert result.returncode != 0, (
        "a real mutation older than the old 2 MB tail vanished, and with it the tree it "
        f"established.\nSTDERR:\n{result.stderr}")
    assert "BLOCKED BY beta" in result.stderr, result.stderr


# ==================================================== ATTACK: choosing an obliging authority

def test_a_path_outside_this_repository_cannot_take_authority(trees, tmp_path):
    """ATTACK 5. Resolution reads paths the agent influences, so a prepared directory with
    obliging guards is the obvious attack. `repo_worktrees()` is why it is never selected."""
    primary, _alpha, _beta = trees
    outsider = tmp_path / "outsider"
    outsider.mkdir()
    _git(outsider, "init", "-b", "main")
    _git(outsider, "config", "user.email", "t@t.t")
    _git(outsider, "config", "user.name", "t")
    _install_chain(outsider, PASSING_GUARD)
    _commit_all(outsider, "a different repository entirely")

    by_payload = run_from(primary, {
        "tool_name": "Edit", "tool_input": {"file_path": str(outsider / "anything.py")}})
    assert by_payload.returncode != 0, "governance was delegated OUT of this repository"
    assert "BLOCKED BY primary" in by_payload.stderr, by_payload.stderr

    t = write_transcript(tmp_path / "s.jsonl", [tool_use("Edit", outsider / "anything.py")])
    by_transcript = run_from(primary, stop_payload(t))
    assert by_transcript.returncode != 0, (
        "a transcript naming a foreign repository handed it authority over the turn")
    assert "BLOCKED BY primary" in by_transcript.stderr, by_transcript.stderr


def test_a_tree_with_uncommitted_guards_is_refused_authority(trees, tmp_path):
    """ATTACK 6. An agent may not edit a guard and then be judged by the edit.

    A COMMITTED guard change is ordinary development answering to CI at merge, so the trigger
    is uncommitted state, not change. The refused tree is not skipped: this tree judges for it.
    """
    primary, alpha, _beta = trees
    set_guard(alpha, "def main() -> int:\n    return 0  # neutered, uncommitted\n", commit=False)

    by_payload = run_from(primary, {
        "tool_name": "Edit", "tool_input": {"file_path": str(alpha / "app.py")}})
    assert by_payload.returncode != 0, (
        "authority was handed to a tree whose guards exist only in its working copy")
    assert "UNCOMMITTED guard files" in by_payload.stderr, by_payload.stderr
    assert "BLOCKED BY primary" in by_payload.stderr, by_payload.stderr

    t = write_transcript(tmp_path / "s.jsonl", [tool_use("Edit", alpha / "app.py")])
    by_transcript = run_from(primary, stop_payload(t))
    assert by_transcript.returncode != 0, by_transcript.stderr
    assert "UNCOMMITTED guard files" in by_transcript.stderr, by_transcript.stderr


# ============================================================ ATTACK: the delegation itself

def test_delegation_returns_the_authority_tree_s_real_verdict(trees):
    """Not a way to make blocks disappear: when the authority tree blocks, the block stands."""
    primary, alpha, _beta = trees
    set_guard(alpha, BLOCKING_GUARD)
    result = run_from(primary, {
        "tool_name": "Edit", "tool_input": {"file_path": str(alpha / "app.py")}})
    assert result.returncode != 0, "a real block was lost in transit"
    assert "BLOCKED BY alpha" in result.stderr, result.stderr


def test_authority_hops_exactly_once(trees):
    """ATTACK 7a. The delegate must judge, not delegate again."""
    primary, alpha, _beta = trees
    result = run_from(
        primary, {"tool_name": "Edit", "tool_input": {"file_path": str(alpha / "f.py")}},
        env_extra={"ED_GOVERNANCE_AUTHORITY_DELEGATED": "1"})
    assert result.returncode != 0, "a delegated run delegated again instead of judging"
    assert "BLOCKED BY primary" in result.stderr, result.stderr


def test_a_delegate_that_cannot_run_blocks(trees):
    """ATTACK 7b. Fail-closed: a guard run that did not happen is not one that passed."""
    primary, alpha, _beta = trees
    (alpha / "tools" / "stop_chain.py").write_text(
        "this is not valid python(((\n", encoding="utf-8")
    _commit_all(alpha, "alpha: chain is broken")
    result = run_from(primary, {
        "tool_name": "Edit", "tool_input": {"file_path": str(alpha / "app.py")}})
    assert result.returncode != 0, "a delegate that could not run was treated as a pass"


# ================================================ unresolved authority fails, never guesses

def test_an_unreadable_transcript_refuses_the_event(trees, tmp_path):
    """The evidence channel exists and is broken. Quietly trusting the bootstrap tree here is
    exactly the defect, so the event is refused and the reason is named."""
    primary, _alpha, _beta = trees
    result = run_from(primary, stop_payload(tmp_path / "no_such_transcript.jsonl"))
    assert result.returncode != 0
    assert "REFUSED" in result.stderr, result.stderr
    assert "could not be read" in result.stderr, result.stderr


def test_a_session_with_no_mutations_is_judged_here_and_says_so(trees, tmp_path):
    """Nothing was materially modified, so there is no work tree to defer to. The bootstrap
    judges — which is correct — and the banner names it, so it is never silent."""
    primary, alpha, _beta = trees
    t = write_transcript(tmp_path / "s.jsonl", [
        tool_use("Read", alpha / "app.py"), prose("just looking")])
    result = run_from(primary, stop_payload(t))
    assert result.returncode != 0
    assert "BLOCKED BY primary" in result.stderr, result.stderr
    assert "GOVERNANCE AUTHORITY:" in result.stderr and "[bootstrap]" in result.stderr, result.stderr


def test_every_block_names_the_tree_that_judged_it(trees):
    """The 2026-09-03 block named a rule but never its tree, so staleness read as a mystery."""
    primary, _alpha, _beta = trees
    result = run_from(primary, stop_payload())
    assert result.returncode != 0
    assert str(primary.resolve()) in result.stderr.replace("\\\\", "\\"), result.stderr


# ====================================================================== resolver unit controls

def test_only_mutating_tools_establish_where_work_happened():
    from tools.stop_chain import MUTATING_TOOLS, _mutation_targets_in

    assert MUTATING_TOOLS == {"Edit", "Write", "MultiEdit", "NotebookEdit"}
    for tool in ("Read", "Grep", "Glob", "WebFetch", "Task"):
        found, unresolved = _mutation_targets_in(tool_use(tool, REPO / "server.py"))
        assert (found, unresolved) == ([], []), f"{tool} counted as a mutation"
    for tool in sorted(MUTATING_TOOLS):
        found, unresolved = _mutation_targets_in(tool_use(tool, REPO / "server.py"))
        assert (found, unresolved) == ([str(REPO / "server.py")], []), tool


def test_the_bash_resolver_reuses_the_existing_owner_and_reads_no_authority_from_reads():
    """`bash_mutation_targets` composes process_lock_guard; it must parse nothing itself.

    Pinned because the fix for this hole is a composition, and a later "small tweak" that
    reaches for its own regex would put two answers to one question back in the tree.
    """
    from tools.stop_chain import bash_mutation_targets

    writes, unresolved = bash_mutation_targets(
        f'printf x >> "{REPO / "governance" / "root_cause_log.md"}"')
    assert [Path(p) for p in writes] == [REPO / "governance" / "root_cause_log.md"]
    assert unresolved == []

    git_targets, _ = bash_mutation_targets(f'git -C "{REPO}" commit -m x')
    assert any(Path(p).resolve() == REPO for p in git_targets), git_targets

    for harmless in (f'cat "{REPO / "server.py"}"', f'git -C "{REPO}" status',
                     f'git -C "{REPO}" log --oneline -1', f'ls -la "{REPO}"'):
        assert bash_mutation_targets(harmless) == ([], []), harmless

    _paths, reasons = bash_mutation_targets("git apply /tmp/x.patch")
    assert reasons and "cannot determine" in reasons[0], reasons

    # no second parser: the resolver owns no regex of its own
    src = (REPO / "tools" / "stop_chain.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "bash_mutation_targets")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert {"_shell_write_targets", "iter_git_invocations", "iter_command_segments",
            "git_segment_mutates_checkout", "_shell_rewrites_tracked_tree"} <= called, called
    assert "re.compile" not in ast.get_source_segment(src, fn)


def test_canonical_authority_prefers_the_work_target_over_the_session_record(tmp_path):
    """Both signals present: the file being touched NOW wins over where the session has been."""
    from tools.stop_chain import canonical_authority

    t = write_transcript(tmp_path / "t.jsonl", [tool_use("Edit", REPO / "server.py")])
    trees, source, failure = canonical_authority(json.dumps({
        "tool_input": {"file_path": str(REPO / "config" / "decision_path_admissions.json")},
        "transcript_path": str(t),
    }))
    assert trees == (REPO,) and source == "work target" and failure == "", (trees, source, failure)


def test_canonical_authority_reports_bootstrap_and_unresolved_distinctly(tmp_path):
    from tools.stop_chain import canonical_authority

    for junk in ("", "not json", json.dumps(["a", "list"]), json.dumps({})):
        trees, source, failure = canonical_authority(junk)
        assert (trees, source, failure) == ((), "bootstrap", ""), (junk[:30], trees, source)

    trees, source, failure = canonical_authority(
        json.dumps({"transcript_path": str(tmp_path / "missing.jsonl")}))
    assert trees == () and source == "unresolved" and "could not be read" in failure


def test_this_repository_is_its_own_authority_for_its_own_files():
    """Sanity on the live tree: no delegation loop, no surprise third party."""
    from tools.stop_chain import REPO as CHAIN_REPO, repo_worktrees, resolve_authority

    assert CHAIN_REPO in repo_worktrees()
    delegate_to, run_here, _source, _notes, failure = resolve_authority(
        json.dumps({"tool_input": {"file_path": str(REPO / "server.py")}}),
        ("tools.stop_guard",))
    assert failure == "" and delegate_to == () and run_here is True


# ============================================================ RC-520 A: Monitor is a shell channel
#
# MEASURED 2026-09-05: the Monitor tool runs a shell `command` exactly as Bash does, was absent
# from `.claude/settings.json`'s matcher and from three separate tool tuples in the guards, and
# rewrote `tools/mission_latch.py` through a Python one-liner that no guard judged. The class is
# now ONE roster (`stop_chain.BASH_TOOLS`) imported by both shell guards, and the matcher
# carries Monitor. These controls drive the same real seams the Bash controls above drive.

def monitor_use(command: str) -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Monitor", "input": {"command": command}}]}}


def run_pretooluse(payload: dict) -> subprocess.CompletedProcess:
    """The REAL PreToolUse chain of this repository with the REAL shell roster, as the hook runs it."""
    env = dict(os.environ)
    env.pop("ED_GOVERNANCE_AUTHORITY_DELEGATED", None)
    return subprocess.run(
        [sys.executable, str(REPO / "tools" / "pretooluse_chain.py"),
         "tools/operator_law_guard.py", "tools/process_lock_guard.py"],
        cwd=str(REPO), input=json.dumps(payload), text=True, capture_output=True, env=env,
        timeout=600)


def _literal_shell_tuples(module_path: Path) -> list[str]:
    """Container literals in `module_path` that name PowerShell — a private copy of the roster."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            names = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if "PowerShell" in names:
                found.append(", ".join(names))
    return found


def test_monitor_is_in_the_one_shell_roster_and_the_hook_matcher():
    import re as _re

    import tools.operator_law_guard as olg
    import tools.process_lock_guard as plg
    from tools.stop_chain import BASH_TOOLS

    assert {"Bash", "PowerShell", "Monitor"} <= BASH_TOOLS
    assert olg.BASH_TOOLS is BASH_TOOLS and plg.BASH_TOOLS is BASH_TOOLS, "a guard kept its own copy"
    for mod in (olg, plg):
        assert _literal_shell_tuples(Path(mod.__file__)) == [], mod.__name__
    settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    matcher = next(h["matcher"] for h in settings["hooks"]["PreToolUse"] if "Bash" in h["matcher"])
    assert _re.fullmatch(matcher, "Monitor"), matcher
    assert _re.fullmatch("Bash|PowerShell", "Monitor") is None, "the pre-RC-520 matcher never ran the hook for Monitor"


def test_a_monitor_command_is_judged_exactly_like_the_same_bash_command():
    """Through the real chain: a harmless read passes for both; the exact RC-520 bypass — a
    `python -c` write to a guard module — is refused for both, for the same reason."""
    bypass = ("python -c 'p=\"tools/mission_latch.py\"\ns=open(p).read()\n"
              "open(p,\"w\").write(s)'")
    for command, expect_block in ((f'git -C "{REPO}" status --porcelain', False), (bypass, True)):
        verdicts = {}
        for tool in ("Bash", "Monitor"):
            r = run_pretooluse({"tool_name": tool, "tool_input": {"command": command},
                                "cwd": str(REPO), "session_id": f"rc520-{tool}"})
            verdicts[tool] = (r.returncode != 0, r.stderr)
        assert verdicts["Bash"][0] is expect_block, verdicts["Bash"][1]
        assert verdicts["Monitor"][0] is expect_block, verdicts["Monitor"][1]
        if expect_block:
            reason = lambda err: next(l for l in err.splitlines() if "ACTION BLOCKED" in l)  # noqa: E731
            assert reason(verdicts["Monitor"][1]) == reason(verdicts["Bash"][1])


def test_a_monitor_mutation_puts_its_worktree_in_the_set_and_removal_reopens_the_hole(trees, tmp_path):
    """Session-record seam: a Monitor write to alpha makes alpha the authority exactly as a Bash
    write does; a chain whose roster lacks Monitor falls back to the launch tree — the defect."""
    primary, alpha, _beta = trees
    command = f'echo "| RC-999 | OPEN |" >> "{alpha / "governance_row.md"}"'
    for maker in (bash_use, monitor_use):
        t = write_transcript(tmp_path / "s.jsonl", [maker(command)])
        result = run_from(primary, stop_payload(t))
        assert result.returncode == 0, result.stderr
        assert "BLOCKED BY primary" not in result.stderr, result.stderr
    chain = primary / "tools" / "stop_chain.py"
    src = chain.read_text(encoding="utf-8")
    assert src.count('"Shell", "Monitor"}') == 1
    chain.write_text(src.replace('"Shell", "Monitor"}', '"Shell"}'), encoding="utf-8")
    _commit_all(primary, "roster without Monitor (the pre-RC-520 state)")
    t = write_transcript(tmp_path / "s.jsonl", [monitor_use(command)])
    result = run_from(primary, stop_payload(t))
    assert result.returncode != 0 and "BLOCKED BY primary" in result.stderr, result.stderr


def test_the_resolver_reads_monitor_records_through_the_one_roster(monkeypatch):
    from tools import stop_chain as sc

    command = f'printf x >> "{REPO / "governance" / "root_cause_log.md"}"'
    assert sc._mutation_targets_in(monitor_use(command)) == sc._mutation_targets_in(bash_use(command))
    assert sc._mutation_targets_in(monitor_use(command))[0], "a Monitor write resolved to nothing"
    monkeypatch.setattr(sc, "BASH_TOOLS", frozenset({"Bash", "PowerShell"}))
    assert sc._mutation_targets_in(monitor_use(command)) == ([], [])


# ============================================================ RC-520 B: the delegated chain self-lock
#
# OBSERVED 2026-09-05: a guard-imported module in the delegated worktree was left referencing
# a helper before the call that defined it. Every delegated run crashed before adjudicating,
# the crash is a BLOCK by design, and the Edit that would have restored the module was judged
# by the same crashing delegate. The only way back in was an unhooked tool. The repair: a
# crashed delegate names the file it crashed in, and exactly one mutation is admitted for that
# tree — an edit of that file — judged by the launch tree under the identical roster.

GUARD_USING_HELPER = '''"""A rostered guard that depends on a sibling module, like the real ones do."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import demo_helper  # noqa: E402


def main() -> int:
    demo_helper.rows()
    sys.stderr.write("BLOCKED BY %s\\n" % __file__.replace("\\\\", "/").split("/")[-3])
    return 2
'''

BROKEN_HELPER = "def rows():\n    return _is_row('x')   # helper referenced before it was defined\n"
GOOD_HELPER = "def _is_row(line):\n    return True\n\n\ndef rows():\n    return _is_row('x')\n"


def break_delegate(tree: Path) -> Path:
    (tree / "tools" / "demo_guard.py").write_text(GUARD_USING_HELPER, encoding="utf-8")
    helper = tree / "tools" / "demo_helper.py"
    helper.write_text(BROKEN_HELPER, encoding="utf-8")
    _commit_all(tree, "guard-imported module left half-edited")
    return helper


def edit(path: Path) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": str(path)}}


def test_a_broken_guard_module_blocks_ordinary_work_and_names_itself(trees):
    primary, alpha, _beta = trees
    set_guard(primary, PASSING_GUARD)     # the launch tree would pass: the block is the crash
    break_delegate(alpha)
    result = run_from(primary, edit(alpha / "app.py"))
    assert result.returncode != 0, "a crashed delegate was treated as a pass"
    assert " crashed: NameError" in result.stderr, result.stderr
    assert "[broken file: tools/demo_helper.py]" in result.stderr, result.stderr
    assert "GOVERNANCE RECOVERY" not in result.stderr, result.stderr


def test_only_the_file_the_crash_named_can_be_restored_and_only_by_an_edit(trees, tmp_path):
    primary, alpha, _beta = trees
    set_guard(primary, PASSING_GUARD)
    helper = break_delegate(alpha)

    admitted = run_from(primary, edit(helper))
    assert admitted.returncode == 0, admitted.stderr
    assert "GOVERNANCE RECOVERY" in admitted.stderr, admitted.stderr
    assert str(primary.resolve()) in admitted.stderr.replace("\\\\", "\\"), "the judge was not named"

    for other in (alpha / "app.py", alpha / "tools" / "demo_guard.py", alpha / "tools" / "stop_chain.py"):
        refused = run_from(primary, edit(other))
        assert refused.returncode != 0 and "GOVERNANCE RECOVERY" not in refused.stderr, (other, refused.stderr)

    # Exactly Edit. The other file-target mutation tools replace or bulk-rewrite the file, and
    # a recovery that can replace a guard wholesale is not the narrow door (operator correction).
    for tool in ("Write", "MultiEdit", "NotebookEdit"):
        for key in ("file_path", "notebook_path"):
            wide = run_from(primary, {"tool_name": tool, "tool_input": {key: str(helper), "content": "x"}})
            assert wide.returncode != 0 and "GOVERNANCE RECOVERY" not in wide.stderr, (tool, key, wide.stderr)

    # A shell write to the exact file is never a recovery, whichever shell channel carries it.
    for maker in (bash_use, monitor_use, lambda c: {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "PowerShell", "input": {"command": c}}]}}):
        t = write_transcript(tmp_path / "s.jsonl", [maker(f'printf x >> "{helper}"')])
        shell = run_from(primary, stop_payload(t))
        assert shell.returncode != 0 and "GOVERNANCE RECOVERY" not in shell.stderr, shell.stderr


def test_normal_delegated_authority_resumes_by_itself_once_the_module_imports(trees):
    primary, alpha, _beta = trees
    set_guard(primary, PASSING_GUARD)
    helper = break_delegate(alpha)
    assert run_from(primary, edit(alpha / "app.py")).returncode != 0
    helper.write_text(GOOD_HELPER, encoding="utf-8")          # the recovery edit, applied
    for target in (alpha / "app.py", helper):
        result = run_from(primary, edit(target))
        assert "BLOCKED BY alpha" in result.stderr, (target, result.stderr)
        assert "GOVERNANCE RECOVERY" not in result.stderr and "crashed" not in result.stderr, result.stderr


def test_another_worktree_cannot_nominate_itself_as_recovery_authority(trees):
    primary, alpha, beta = trees
    set_guard(primary, PASSING_GUARD)
    break_delegate(alpha)
    set_guard(beta, BLOCKING_GUARD)
    # beta's copy of the same file name is not the file alpha's crash named: beta judges it.
    result = run_from(primary, edit(beta / "tools" / "demo_helper.py"))
    assert "BLOCKED BY beta" in result.stderr and "GOVERNANCE RECOVERY" not in result.stderr, result.stderr
    # a file outside every worktree of this repository is never a recovery of alpha either.
    result = run_from(primary, edit(primary.parent / "elsewhere" / "tools" / "demo_helper.py"))
    assert "GOVERNANCE RECOVERY" not in result.stderr, result.stderr


def test_mutating_the_recovery_boundary_reopens_the_self_lock_or_the_bypass(trees):
    primary, alpha, _beta = trees
    set_guard(primary, PASSING_GUARD)
    helper = break_delegate(alpha)
    chain = primary / "tools" / "stop_chain.py"
    pristine = chain.read_text(encoding="utf-8")

    removed = pristine.replace("    if not _delegate_crashed(delegate_stderr):\n        return None\n",
                               "    return None\n", 1)
    assert removed != pristine
    chain.write_text(removed, encoding="utf-8")
    _commit_all(primary, "recovery boundary removed")
    locked = run_from(primary, edit(helper))
    assert locked.returncode != 0 and "GOVERNANCE RECOVERY" not in locked.stderr, (
        "with the boundary removed the self-lock must return; it did not")

    widened = pristine.replace(
        "    return target if target in recovery_files(root, delegate_stderr) else None\n",
        "    return target\n", 1)
    assert widened != pristine
    chain.write_text(widened, encoding="utf-8")
    _commit_all(primary, "recovery boundary widened to any file")
    leaked = run_from(primary, edit(alpha / "app.py"))
    assert leaked.returncode == 0 and "GOVERNANCE RECOVERY" in leaked.stderr, (
        "a widened boundary must admit an unrelated edit — that is the attack the boundary refuses")
