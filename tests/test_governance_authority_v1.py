"""RC-512 / RC-544 — who governs an agent event, resolved from the event's own payload.

Every test drives the REAL `tools/stop_chain.py` in a REAL git repository with REAL linked
worktrees, over a real subprocess boundary. Nothing is mocked, because the defect was never in
anyone's model of the system — it was in which copy of the code actually ran.

THE SHAPE. `.claude/settings.json` registers the hook relative to the session project
directory, so the chain, its guards and their ledgers came from whichever checkout the session
was launched in. `primary` below carries a guard that ALWAYS BLOCKS, standing in for a rule the
current tree no longer has; `alpha` and `beta` are linked worktrees whose guard content each
test chooses. If authority resolves correctly, a mutation in a live worktree is judged by that
worktree's own registered guards and never by `primary`'s withdrawn rule.

THE INVARIANT (RC-544, 2026-09-10): a blocked or unexecuted action has ZERO authority-state
effect. Authority is a pure function of the payload in hand; no transcript is read, no session
record exists, nothing is remembered between events. The earlier resolver read the session
transcript for "every worktree this session modified", and a tool_use record cannot tell an
executed mutation from one the hook refused — one BLOCKED command poisoned every later event.
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
    """The chain plus everything it imports from `tools/`, resolved rather than listed, and
    copied REAL into each scratch tree so the shell resolver (not an ImportError path) runs."""
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
    wire(tree)


def wire(tree: Path, stop: tuple[str, ...] = ("tools/demo_guard.py",),
         pre: tuple[str, ...] = ("tools/demo_guard.py",)) -> None:
    """The tree's CANONICAL hook wiring — the roster a delegate is judged under (RC-522),
    DERIVED from this repository's real wiring files with the fixture's roster substituted."""
    def chain_of(command: str) -> str:
        return next(t.replace("\\", "/") for t in command.split()
                    if t.replace("\\", "/").startswith("tools/") and t.endswith("_chain.py"))

    real = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks: dict = {}
    for event, entries in real["hooks"].items():
        members = stop if event.lower() == "stop" else pre
        derived = []
        for entry in entries:
            cmds = [{"type": "command", "command": " ".join(["python", chain_of(h["command"]), *members])}
                    for h in entry["hooks"]]
            item = {"hooks": cmds}
            if "matcher" in entry:
                item["matcher"] = entry["matcher"]
            derived.append(item)
        hooks[event] = derived
    (tree / ".claude").mkdir(parents=True, exist_ok=True)
    (tree / ".claude" / "settings.json").write_text(json.dumps({"hooks": hooks}, indent=1), encoding="utf-8")

    cursor = json.loads((REPO / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    chooks: dict = {}
    for event, entries in cursor["hooks"].items():
        members = stop if event.lower() == "stop" else pre
        chooks[event] = [{"command": " ".join(["python", chain_of(entry["command"]), *members])}
                         for entry in entries]
    (tree / ".cursor").mkdir(parents=True, exist_ok=True)
    (tree / ".cursor" / "hooks.json").write_text(
        json.dumps({"version": cursor.get("version", 1), "hooks": chooks}, indent=1), encoding="utf-8")


def _commit_all(tree: Path, msg: str) -> None:
    _git(tree, "add", "-A")
    _git(tree, "commit", "-m", msg)


@pytest.fixture()
def trees(tmp_path):
    """A primary checkout (the stale launch tree, carrying a withdrawn blocking rule) and two
    linked worktrees where work actually happens."""
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


def run_from(tree: Path, payload: dict, env_extra: dict | None = None,
             roster: tuple[str, ...] = ("tools/demo_guard.py",)) -> subprocess.CompletedProcess:
    """Invoke the chain the way the hook does: the LAUNCH tree's roster on argv, the payload
    on stdin. A delegate ignores the argv roster and reads its own wiring (RC-522)."""
    env = dict(os.environ)
    env.pop("ED_GOVERNANCE_AUTHORITY_DELEGATED", None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(tree / "tools" / "stop_chain.py"), *roster],
        cwd=str(tree), input=json.dumps(payload), text=True, capture_output=True,
        env=env, timeout=600,
    )


def edit(path: Path) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": str(path)}}


def bash(command: str, cwd: Path | None = None, tool: str = "Bash") -> dict:
    out = {"tool_name": tool, "tool_input": {"command": command}}
    if cwd is not None:
        out["cwd"] = str(cwd)
    return out


def stop_payload(transcript: Path | None = None) -> dict:
    out = {"hook_event_name": "Stop", "stop_hook_active": False}
    if transcript is not None:
        out["transcript_path"] = str(transcript)
    return out


def write_transcript(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def tool_use(name: str, path: Path) -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": name, "input": {"file_path": str(path)}}]}}


# ============================================================ the resolution shapes

def test_a_file_payload_is_judged_by_the_tree_the_file_is_in(trees):
    """The stale tree runs the hook; the work is elsewhere; the withdrawn rule must not fire."""
    primary, alpha, _beta = trees
    result = run_from(primary, edit(alpha / "app.py"))
    assert result.returncode == 0, (
        "work in a linked worktree was judged by the stale tree's withdrawn rule — the "
        f"2026-09-03 false block, unfixed.\nSTDERR:\n{result.stderr}")
    assert "BLOCKED BY primary" not in result.stderr, result.stderr


def test_a_shell_write_is_judged_by_the_tree_it_writes_into(trees):
    """Bash is a mutation channel: a sanctioned .md/.json write lands in alpha, so alpha's own
    guards judge it, not the launch tree's withdrawn rule."""
    primary, alpha, _beta = trees
    for command in (f'echo "| RC-999 | OPEN |" >> "{alpha / "governance_row.md"}"',
                    f'printf "{{}}" > "{alpha / "artifact.json"}"',
                    f'git -C "{alpha}" commit --allow-empty -m x'):
        result = run_from(primary, bash(command, cwd=primary))
        assert result.returncode == 0, (command, result.stderr)
        assert "BLOCKED BY primary" not in result.stderr, result.stderr


def test_a_shell_write_into_a_blocking_tree_is_blocked_by_that_tree(trees):
    primary, alpha, beta = trees
    set_guard(beta, BLOCKING_GUARD)
    result = run_from(primary, bash(f'echo hi >> "{beta / "notes.md"}"', cwd=primary))
    assert result.returncode != 0 and "BLOCKED BY beta" in result.stderr, result.stderr


def test_a_shell_command_writing_two_trees_is_judged_by_both_and_the_worst_wins(trees):
    primary, alpha, beta = trees
    set_guard(alpha, BLOCKING_GUARD)
    command = f'echo a >> "{alpha / "a.md"}" && echo b >> "{beta / "b.md"}"'
    result = run_from(primary, bash(command, cwd=primary))
    assert result.returncode != 0 and "BLOCKED BY alpha" in result.stderr, result.stderr


def test_a_harmless_shell_read_is_judged_here_and_says_so(trees):
    """Inspection is not work: a read-only command names no target tree, so the launch tree
    judges under its own roster and the banner says which tree spoke."""
    primary, alpha, _beta = trees
    for command in (f'cat "{alpha / "app.py"}"', f'git -C "{alpha}" status --porcelain', f'ls -la "{alpha}"'):
        result = run_from(primary, bash(command, cwd=primary))
        assert result.returncode != 0 and "BLOCKED BY primary" in result.stderr, (command, result.stderr)
        assert "[this tree]" in result.stderr, result.stderr


def test_a_stop_event_is_judged_by_the_launch_tree_from_its_payload_alone(trees, tmp_path):
    """A Stop names no target. It is judged HERE — whatever any transcript says. A transcript
    naming alpha changes nothing, because no transcript is read."""
    primary, alpha, _beta = trees
    t = write_transcript(tmp_path / "s.jsonl", [tool_use("Edit", alpha / "app.py")])
    for payload in (stop_payload(), stop_payload(t), stop_payload(tmp_path / "missing.jsonl")):
        result = run_from(primary, payload)
        assert result.returncode != 0 and "BLOCKED BY primary" in result.stderr, result.stderr
        assert "REFUSED" not in result.stderr, result.stderr


# ============================================================ THE INVARIANT (RC-544)

def test_a_blocked_action_has_zero_authority_state_effect(trees, tmp_path):
    """BLOCKED OR UNEXECUTED ACTION => ZERO MUTATION => ZERO AUTHORITY-STATE EFFECT.

    1. A mutation whose tree cannot be located is REFUSED (blocked) on its own event.
    2. The very next events — a Stop, an edit in alpha, a read — are judged exactly as if the
       blocked event had never happened: no refusal carries over, no tree was added.
    3. A transcript full of blocked/unexecuted tool_use records changes nothing either.
    """
    primary, alpha, _beta = trees
    blocked = run_from(primary, bash("git apply /tmp/some.patch"))      # no cwd: unlocatable
    assert blocked.returncode != 0 and "REFUSED" in blocked.stderr, blocked.stderr
    assert "cannot determine" in blocked.stderr, blocked.stderr

    after_stop = run_from(primary, stop_payload())
    assert "REFUSED" not in after_stop.stderr and "cannot determine" not in after_stop.stderr, after_stop.stderr
    after_edit = run_from(primary, edit(alpha / "app.py"))
    assert after_edit.returncode == 0, after_edit.stderr

    poisoned = write_transcript(tmp_path / "poisoned.jsonl", [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "git apply /tmp/x.patch"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "BLOCKED"}]}},
        tool_use("Edit", tmp_path / "nonexistent-worktree" / "app.py"),
    ])
    result = run_from(primary, stop_payload(poisoned))
    assert "REFUSED" not in result.stderr and "cannot determine" not in result.stderr, result.stderr
    assert "BLOCKED BY primary" in result.stderr, result.stderr      # judged here, as always


def test_the_executor_reads_no_transcript_and_keeps_no_session_state():
    """Structural half of the invariant: the resolver's inputs are the payload's tool_input
    and cwd. No transcript reader, no recovery door, no uncommitted-guard refusal survive."""
    src = REAL_CHAIN.read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for gone in ("session_work_trees", "_transcript_lines", "_mutation_targets_in", "recovery_target",
                 "recovery_files", "_crash_site", "_delegate_crashed", "uncommitted_guard_files",
                 "_ineligible_reason"):
        assert gone not in names, f"{gone} is back"
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    body = code.split('"""', 2)[-1]                     # past the module docstring
    assert "transcript_path" not in body, "the executor reads the transcript again"
    assert "GOVERNANCE RECOVERY" not in body


# ============================================================ choosing an obliging authority

def test_a_path_outside_this_repository_cannot_take_authority(trees, tmp_path):
    """Resolution reads paths the agent influences, so a prepared directory with obliging
    guards is the obvious attack. `repo_worktrees()` is why it is never selected."""
    primary, _alpha, _beta = trees
    outsider = tmp_path / "outsider"
    outsider.mkdir()
    _git(outsider, "init", "-b", "main")
    _git(outsider, "config", "user.email", "t@t.t")
    _git(outsider, "config", "user.name", "t")
    _install_chain(outsider, PASSING_GUARD)
    _commit_all(outsider, "a different repository entirely")

    by_payload = run_from(primary, edit(outsider / "anything.py"))
    assert by_payload.returncode != 0, "governance was delegated OUT of this repository"
    assert "BLOCKED BY primary" in by_payload.stderr, by_payload.stderr
    by_shell = run_from(primary, bash(f'echo x >> "{outsider / "a.md"}"', cwd=primary))
    assert by_shell.returncode != 0 and "BLOCKED BY primary" in by_shell.stderr, by_shell.stderr


def test_delegation_returns_the_authority_tree_s_real_verdict(trees):
    """Not a way to make blocks disappear: when the authority tree blocks, the block stands."""
    primary, alpha, _beta = trees
    set_guard(alpha, BLOCKING_GUARD)
    result = run_from(primary, edit(alpha / "app.py"))
    assert result.returncode != 0, "a real block was lost in transit"
    assert "BLOCKED BY alpha" in result.stderr, result.stderr


def test_an_uncommitted_guard_edit_is_judged_by_the_tree_as_it_is_on_disk(trees):
    """No refusal-and-judge-elsewhere: the target tree's guards as they stand judge the event.
    A neutered uncommitted guard passes (and answers to review and CI at merge); a blocking
    uncommitted guard blocks. Nothing falls back to the launch tree."""
    primary, alpha, _beta = trees
    set_guard(alpha, PASSING_GUARD, commit=False)
    result = run_from(primary, edit(alpha / "app.py"))
    assert result.returncode == 0 and "UNCOMMITTED" not in result.stderr, result.stderr
    set_guard(alpha, BLOCKING_GUARD, commit=False)
    result = run_from(primary, edit(alpha / "app.py"))
    assert result.returncode != 0 and "BLOCKED BY alpha" in result.stderr, result.stderr
    assert "BLOCKED BY primary" not in result.stderr


def test_authority_hops_exactly_once(trees):
    """The delegate must judge, not delegate again."""
    primary, alpha, _beta = trees
    result = run_from(primary, edit(alpha / "f.py"), env_extra={"ED_GOVERNANCE_AUTHORITY_DELEGATED": "1"})
    assert result.returncode != 0, "a delegated run delegated again instead of judging"
    assert "BLOCKED BY primary" in result.stderr, result.stderr


def test_a_delegate_that_cannot_run_blocks_and_opens_no_door(trees):
    """Fail-closed with no recovery mechanism: a broken chain in the target tree blocks every
    hooked mutation into that tree — including an edit of the broken file itself. The repair
    is the operator's or git's, never a hooked mutation judged by another tree."""
    primary, alpha, _beta = trees
    set_guard(primary, PASSING_GUARD)
    chain = alpha / "tools" / "stop_chain.py"
    chain.write_text("this is not valid python(((\n", encoding="utf-8")
    _commit_all(alpha, "alpha: chain is broken")
    for target in (alpha / "app.py", chain, alpha / "tools" / "demo_guard.py"):
        result = run_from(primary, edit(target))
        assert result.returncode != 0, (target, "a delegate that could not run was treated as a pass")
        assert "GOVERNANCE RECOVERY" not in result.stderr, result.stderr
    # and every other event is still judged normally on its own payload
    assert run_from(primary, stop_payload()).returncode == 0


def test_every_block_names_the_tree_that_judged_it(trees):
    """The 2026-09-03 block named a rule but never its tree, so staleness read as a mystery."""
    primary, _alpha, _beta = trees
    result = run_from(primary, stop_payload())
    assert result.returncode != 0
    assert str(primary.resolve()) in result.stderr.replace("\\\\", "\\"), result.stderr
    assert "GOVERNANCE AUTHORITY:" in result.stderr and "[this tree]" in result.stderr


# ============================================================ resolver unit controls

def test_the_bash_resolver_reuses_the_existing_owner_and_reads_no_authority_from_reads():
    """`bash_mutation_targets` composes process_lock_guard; it must parse nothing itself."""
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
    src = REAL_CHAIN.read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "bash_mutation_targets")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert {"_shell_write_targets", "iter_git_invocations", "iter_command_segments",
            "git_segment_mutates_checkout", "_shell_rewrites_tracked_tree"} <= called, called
    assert "re.compile" not in ast.get_source_segment(src, fn)


def test_canonical_authority_is_a_pure_function_of_the_payload(tmp_path):
    from tools.stop_chain import canonical_authority

    trees, source, failure = canonical_authority(json.dumps({
        "tool_name": "Edit", "tool_input": {"file_path": str(REPO / "config" / "decision_path_admissions.json")},
        "transcript_path": str(tmp_path / "irrelevant.jsonl"),
    }))
    assert (trees, source, failure) == ((REPO,), "work target", "")
    trees, source, failure = canonical_authority(json.dumps({
        "tool_name": "Bash", "tool_input": {"command": f'git -C "{REPO}" commit -m x'}, "cwd": str(REPO)}))
    assert (trees, source, failure) == ((REPO,), "shell target", "")
    for quiet in ("", "not json", json.dumps(["a", "list"]), json.dumps({}),
                  json.dumps({"hook_event_name": "Stop", "transcript_path": str(tmp_path / "missing.jsonl")}),
                  json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status"}})):
        assert canonical_authority(quiet) == ((), "this tree", ""), quiet[:40]
    trees, source, failure = canonical_authority(json.dumps({
        "tool_name": "Bash", "tool_input": {"command": "git apply /tmp/x.patch"}}))
    assert trees == () and source == "unresolved" and "cannot determine" in failure


def test_this_repository_is_its_own_authority_for_its_own_files():
    from tools.stop_chain import REPO as CHAIN_REPO, repo_worktrees, resolve_authority

    assert CHAIN_REPO in repo_worktrees()
    delegate_to, run_here, _source, _notes, failure = resolve_authority(
        json.dumps({"tool_input": {"file_path": str(REPO / "server.py")}}), ("tools.stop_guard",))
    assert failure == "" and delegate_to == () and run_here is True


# ============================================================ RC-520 A: Monitor is a shell channel

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


def test_a_monitor_command_is_judged_exactly_like_the_same_bash_command():
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


def test_a_monitor_write_is_judged_by_the_tree_it_writes_into_like_bash(trees):
    primary, alpha, beta = trees
    set_guard(beta, BLOCKING_GUARD)
    for tool in ("Bash", "Monitor", "PowerShell"):
        ok = run_from(primary, bash(f'echo x >> "{alpha / "row.md"}"', cwd=primary, tool=tool))
        assert ok.returncode == 0 and "BLOCKED BY primary" not in ok.stderr, (tool, ok.stderr)
        bad = run_from(primary, bash(f'echo x >> "{beta / "row.md"}"', cwd=primary, tool=tool))
        assert bad.returncode != 0 and "BLOCKED BY beta" in bad.stderr, (tool, bad.stderr)


# ============================================================ RC-522: a delegate runs ITS OWN roster

def test_a_delegate_runs_the_roster_its_own_wiring_registers_not_the_launch_trees(trees):
    """The exact live shape: the launch tree still names a guard the delegate retired."""
    primary, alpha, _beta = trees
    launch_roster = ("tools/demo_guard.py", "tools/retired_guard.py")   # alpha never had it
    result = run_from(primary, edit(alpha / "app.py"), roster=launch_roster)
    assert result.returncode == 0, (
        "the launch tree's argv roster crossed into the delegate and crashed it on a module "
        f"the delegate retired (RC-522 unfixed).\nSTDERR:\n{result.stderr}")
    assert "crashed" not in result.stderr and "retired_guard" not in result.stderr, result.stderr


def test_the_launch_tree_cannot_drop_a_guard_the_delegate_registers(trees):
    primary, alpha, _beta = trees
    set_guard(primary, PASSING_GUARD)
    set_guard(alpha, BLOCKING_GUARD)
    (primary / "tools" / "quiet_guard.py").write_text(PASSING_GUARD, encoding="utf-8")
    _commit_all(primary, "a launch roster that names only a quiet guard")
    result = run_from(primary, edit(alpha / "app.py"), roster=("tools/quiet_guard.py",))
    assert result.returncode != 0, "alpha's own registered guard was dropped by the launch roster"
    assert "BLOCKED BY alpha" in result.stderr, result.stderr


def test_a_tree_without_canonical_wiring_refuses_the_mutation_and_no_tree_judges_instead(trees):
    """No `.claude/settings.json` in the delegate -> the mutation there is refused with the
    reason. It is NOT judged by the launch tree instead (that would be a fallback)."""
    primary, alpha, _beta = trees
    set_guard(primary, PASSING_GUARD)
    (alpha / ".claude" / "settings.json").unlink()
    _commit_all(alpha, "wiring removed")
    result = run_from(primary, edit(alpha / "app.py"))
    assert result.returncode != 0, "a tree with no canonical roster was handed authority"
    assert "no readable hook wiring" in result.stderr, result.stderr
    assert "BLOCKED BY primary" not in result.stderr, "the launch tree judged in the delegate's place"


def test_the_delegate_roster_follows_the_event(trees):
    """Stop and PreToolUse are separately registered; the delegate reads the one the payload
    belongs to. alpha: PreToolUse -> a quiet guard; Bash matcher -> the blocking guard."""
    primary, alpha, _beta = trees
    set_guard(primary, PASSING_GUARD)
    set_guard(alpha, BLOCKING_GUARD, commit=False)
    (alpha / "tools" / "quiet_guard.py").write_text(PASSING_GUARD, encoding="utf-8")
    wire(alpha, stop=("tools/demo_guard.py",), pre=("tools/quiet_guard.py",))
    _commit_all(alpha, "event-specific rosters")
    edited = run_from(primary, edit(alpha / "app.py"))
    assert edited.returncode == 0, edited.stderr
    # a delegated Stop is impossible now (no target) — the roster distinction is proven on
    # the PreToolUse matchers: an Edit and a Bash payload each pick their own entry
    settings = json.loads((alpha / ".claude" / "settings.json").read_text(encoding="utf-8"))
    bash_entry = next(e for e in settings["hooks"]["PreToolUse"] if "Bash" in e.get("matcher", ""))
    bash_entry["hooks"][0]["command"] = "python tools/pretooluse_chain.py tools/demo_guard.py"
    (alpha / ".claude" / "settings.json").write_text(json.dumps(settings, indent=1), encoding="utf-8")
    _commit_all(alpha, "bash entry blocks, edit entry is quiet")
    shell = run_from(primary, bash(f'echo x >> "{alpha / "row.md"}"', cwd=primary))
    assert shell.returncode != 0 and "BLOCKED BY alpha" in shell.stderr, shell.stderr


# ── RC-531: the RECEIVING seam reads its own wiring, whatever the launcher passed ──────────

_DELEGATED = {"ED_GOVERNANCE_AUTHORITY_DELEGATED": "1"}


def test_an_old_launcher_s_argv_cannot_choose_a_delegate_s_roster(trees):
    _primary, alpha, _beta = trees
    result = run_from(alpha, edit(alpha / "app.py"), env_extra=_DELEGATED,
                      roster=("tools/demo_guard.py", "tools/retired_guard.py"))
    assert result.returncode == 0, result.stderr
    assert "crashed" not in result.stderr and "retired_guard" not in result.stderr, result.stderr


def test_an_old_launcher_s_argv_cannot_drop_a_guard_the_delegate_wires(trees):
    _primary, alpha, _beta = trees
    set_guard(alpha, BLOCKING_GUARD, commit=False)
    (alpha / "tools" / "quiet_guard.py").write_text(PASSING_GUARD, encoding="utf-8")
    _commit_all(alpha, "a quiet guard exists but is not wired")
    result = run_from(alpha, edit(alpha / "app.py"), env_extra=_DELEGATED,
                      roster=("tools/quiet_guard.py",))
    assert result.returncode != 0, "the tree's own wired guard was dropped by the launcher's argv"
    assert "BLOCKED BY alpha" in result.stderr, result.stderr


def test_a_delegated_run_in_a_tree_without_wiring_refuses(trees):
    _primary, alpha, _beta = trees
    (alpha / ".claude" / "settings.json").unlink()
    _commit_all(alpha, "wiring removed")
    result = run_from(alpha, edit(alpha / "app.py"), env_extra=_DELEGATED)
    assert result.returncode != 0, "a delegated run with no canonical roster judged anyway"
    assert "no readable hook wiring" in result.stderr and "RC-531" in result.stderr, result.stderr


# ── the SEAM, not the incident's path (Close contract, AGENTS.md) ─────────────────────────
# A recurrence control for a hook-seam invariant drives EVERY entry the tree's wiring
# registers, enumerated by the seam owner (`tools.stop_chain.registered_entrypoints`).


def _run_entry(tree: Path, entry: str, payload: dict, roster: tuple[str, ...]) -> subprocess.CompletedProcess:
    target = tree / entry
    if not target.exists() and (REPO / entry).exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO / entry).read_bytes())
    env = dict(os.environ)
    env.update(_DELEGATED)
    return subprocess.run(
        [sys.executable, str(target), *roster],
        cwd=str(tree), input=json.dumps(payload), text=True, capture_output=True,
        env=env, timeout=600,
    )


def _delegated_roster_violations(tree: Path) -> list[str]:
    from tools.stop_chain import registered_entrypoints

    out: list[str] = []
    for entry in registered_entrypoints(tree):
        stale = _run_entry(tree, entry, edit(tree / "app.py"),
                           ("tools/demo_guard.py", "tools/retired_guard.py"))
        if stale.returncode != 0 or "crashed" in stale.stderr or "retired_guard" in stale.stderr:
            out.append(f"{entry}: the launcher's argv crossed into the delegated run "
                       f"(rc={stale.returncode}): {stale.stderr.strip()[-200:]}")
    return out


def test_every_registered_hook_entry_obeys_the_shared_delegated_roster_invariant(trees):
    from tools.stop_chain import registered_entrypoints

    _primary, alpha, _beta = trees
    entries = registered_entrypoints(alpha)
    assert entries and entries == registered_entrypoints(REPO), (entries, registered_entrypoints(REPO))
    assert _delegated_roster_violations(alpha) == []

    set_guard(alpha, BLOCKING_GUARD, commit=False)
    (alpha / "tools" / "quiet_guard.py").write_text(PASSING_GUARD, encoding="utf-8")
    _commit_all(alpha, "a quiet guard exists but is not wired")
    for entry in entries:
        dropped = _run_entry(alpha, entry, edit(alpha / "app.py"), ("tools/quiet_guard.py",))
        assert dropped.returncode != 0 and "BLOCKED BY alpha" in dropped.stderr, (entry, dropped.stderr)


_LEAKY_ENTRY = '''"""A chain entry that runs whatever argv names — the RC-531 shape, wired as a third entry."""
import importlib, io, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
raw = sys.stdin.read()
worst = 0
for a in sys.argv[1:]:
    mod = importlib.import_module("tools." + a.replace("\\\\", "/").removeprefix("tools/").removesuffix(".py"))
    sys.stdin = io.StringIO(raw)
    worst = max(worst, int(mod.main() or 0))
sys.exit(worst)
'''


def test_a_newly_wired_entry_that_trusts_argv_cannot_escape_the_enumeration(trees):
    from tools.stop_chain import registered_entrypoints

    _primary, alpha, _beta = trees
    (alpha / "tools" / "leaky_chain.py").write_text(_LEAKY_ENTRY, encoding="utf-8")
    wiring = alpha / ".claude" / "settings.json"
    settings = json.loads(wiring.read_text(encoding="utf-8"))
    settings["hooks"]["Stop"].append(
        {"hooks": [{"type": "command", "command": "python tools/leaky_chain.py tools/demo_guard.py"}]})
    wiring.write_text(json.dumps(settings, indent=1), encoding="utf-8")
    _commit_all(alpha, "a third entry, wired")

    assert "tools/leaky_chain.py" in registered_entrypoints(alpha)
    violations = _delegated_roster_violations(alpha)
    assert any(v.startswith("tools/leaky_chain.py:") for v in violations), violations
    assert not any(v.startswith(("tools/stop_chain.py:", "tools/pretooluse_chain.py:")) for v in violations), violations


def test_the_live_wiring_is_the_population_the_controls_drive(trees):
    from tools.stop_chain import registered_entrypoints

    _primary, alpha, _beta = trees
    live = registered_entrypoints(REPO)
    assert live, "the real wiring registers no chain entry"
    for entry in live:
        assert (REPO / entry).is_file(), entry
    assert registered_entrypoints(alpha) == live


def test_both_live_hosts_register_the_same_chain_entries():
    from tools.stop_chain import hook_wiring_divergence, registered_entrypoints

    divergence = hook_wiring_divergence(REPO)
    assert all(entries == () for entries in divergence.values()), divergence
    assert registered_entrypoints(REPO, host="claude") == registered_entrypoints(REPO, host="cursor")


def test_a_cursor_only_entry_that_trusts_argv_cannot_escape_the_enumeration(trees):
    from tools.stop_chain import hook_wiring_divergence, registered_entrypoints

    _primary, alpha, _beta = trees
    (alpha / "tools" / "leaky_chain.py").write_text(_LEAKY_ENTRY, encoding="utf-8")
    wiring = alpha / ".cursor" / "hooks.json"
    cursor = json.loads(wiring.read_text(encoding="utf-8"))
    cursor["hooks"]["stop"].append({"command": "python tools/leaky_chain.py tools/demo_guard.py"})
    wiring.write_text(json.dumps(cursor, indent=1), encoding="utf-8")
    _commit_all(alpha, "a leaky third entry, wired through Cursor only")

    assert "tools/leaky_chain.py" in registered_entrypoints(alpha)
    assert "tools/leaky_chain.py" not in registered_entrypoints(alpha, host="claude")
    assert hook_wiring_divergence(alpha)["cursor"] == ("tools/leaky_chain.py",)
    violations = _delegated_roster_violations(alpha)
    assert any(v.startswith("tools/leaky_chain.py:") for v in violations), violations
    assert not any(v.startswith(("tools/stop_chain.py:", "tools/pretooluse_chain.py:")) for v in violations), violations


def test_a_missing_module_is_a_block(trees):
    """A rostered member that does not exist is a crash, and a crash is a BLOCK (RC-57)."""
    import io

    from tools.stop_chain import run_chain

    captured = io.StringIO()
    real_err = sys.stderr
    sys.stderr = captured
    try:
        rc = run_chain(json.dumps({"hook_event_name": "Stop"}), ("tools.zz_absent_member_rc522",))
    finally:
        sys.stderr = real_err
    assert rc == 2 and "crashed: ModuleNotFoundError" in captured.getvalue(), captured.getvalue()
