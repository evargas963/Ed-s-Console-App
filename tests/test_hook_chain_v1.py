"""tools/hook_chain.py — the ONE hook executor, and the adversarial proofs of RC-544.

Every proof drives the REAL executor and the REAL wired guards over a subprocess boundary
with the payload on stdin, exactly as the hosts run it. Nothing is mocked.

THE INVARIANT (RC-544): BLOCKED OR UNEXECUTED ACTION => ZERO MUTATION => ZERO EFFECT ON ANY
LATER EVENT. The earlier executor (tools/stop_chain.py, deleted) resolved "authority" from
the session transcript and delegated to other worktrees' chains; a transcript record cannot
tell an executed mutation from one the hook refused, so one BLOCKED command poisoned every
later event of the session. The executor now keeps no state and chooses no other tree: the
checkout running the session judges every event from that event's payload alone.
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.hook_chain import STOP_CHAIN, _argv_members, run_chain  # noqa: E402

_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
PRE_ROSTER = ("tools/operator_law_guard.py", "tools/process_lock_guard.py")


def _chain(payload, roster: tuple[str, ...] = PRE_ROSTER, root: Path = ROOT) -> subprocess.CompletedProcess[str]:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(root / "tools" / "hook_chain.py"), *roster],
                          cwd=str(root), input=raw, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=_ENV, timeout=180)


def bash(command: str, cwd: Path | None = None, tool: str = "Bash") -> dict:
    out = {"tool_name": tool, "tool_input": {"command": command}}
    if cwd is not None:
        out["cwd"] = str(cwd)
    return out


def edit(path: Path) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": str(path)}}


def _wired_commands() -> dict[str, list[str]]:
    """{event: [command, ...]} from BOTH live host wirings — the population the seam registers."""
    out: dict[str, list[str]] = {}
    claude = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    for event, entries in claude["hooks"].items():
        for e in entries:
            out.setdefault(event, []).extend(h["command"] for h in e["hooks"])
    cursor = json.loads((ROOT / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    for event, entries in cursor["hooks"].items():
        out.setdefault(event, []).extend(e["command"] for e in entries)
    return out


# ============================================================ executor contract

def test_argv_roster_maps_hook_spellings_to_modules():
    assert _argv_members(["tools/stop_guard.py", "tools\\operator_law_guard.py", "x.py"]) == (
        "tools.stop_guard", "tools.operator_law_guard", "tools.x")
    assert _argv_members([]) == () and STOP_CHAIN == ("tools.stop_guard",)


def test_both_hosts_wire_the_one_executor_with_the_same_rosters():
    wired = _wired_commands()
    commands = [c for cmds in wired.values() for c in cmds]
    assert commands and all("tools/hook_chain.py" in c for c in commands), commands
    for retired in ("stop_chain.py", "pretooluse_chain.py", "honesty_guard", "proof_only_guard"):
        assert not any(retired in c for c in commands), retired
        assert not (ROOT / "tools" / retired.split(".")[0]).with_suffix(".py").exists() or retired.endswith("guard"), retired
    def roster(c: str) -> set[str]:
        return {t for t in c.split() if t.startswith("tools/") and "chain" not in t}
    assert wired["PreToolUse"] and wired["preToolUse"] and wired["Stop"] and wired["stop"]
    assert all(roster(c) == set(PRE_ROSTER) for c in wired["PreToolUse"] + wired["preToolUse"]), wired
    assert all(roster(c) == {"tools/stop_guard.py"} for c in wired["Stop"] + wired["stop"]), wired


def test_every_wired_executable_refuses_an_unreadable_payload():
    """RC-541: 'cannot judge' and 'judged clean' must not share an exit code — measured for
    every executable the wiring names, not a hand list."""
    members = {t for cmds in _wired_commands().values() for c in cmds for t in c.split() if t.startswith("tools/")}
    assert members >= {"tools/hook_chain.py", "tools/operator_law_guard.py", "tools/process_lock_guard.py", "tools/stop_guard.py"}
    for rel in sorted(members):
        r = subprocess.run([sys.executable, str(ROOT / rel)], cwd=str(ROOT), input="{not json",
                           capture_output=True, text=True, encoding="utf-8", errors="replace", env=_ENV, timeout=120)
        assert r.returncode != 0, f"{rel} exits 0 on an unreadable payload — fails OPEN"


def test_a_crashing_or_missing_member_blocks_and_the_chain_keeps_running(capsys):
    assert run_chain(json.dumps({"tool_name": "Stop"}), ("tools.zz_no_such_guard_zz",)) == 2
    r = _chain(bash("git reset --hard", cwd=ROOT), roster=("tools/process_lock_guard.py", "tools/zz_absent.py"))
    assert r.returncode == 2 and "RESET_GUARD" in r.stderr and "tools.zz_absent crashed" in r.stderr, r.stderr


def test_a_member_block_reaches_the_host_with_the_members_stderr_and_the_judge_banner():
    standalone = subprocess.run([sys.executable, str(ROOT / "tools" / "process_lock_guard.py")], cwd=str(ROOT),
                                input=json.dumps(bash("git reset --hard")), capture_output=True, text=True,
                                encoding="utf-8", errors="replace", env=_ENV, timeout=120)
    chain = _chain(bash("git reset --hard"))
    assert standalone.returncode == chain.returncode == 2
    assert "RESET_GUARD" in standalone.stderr and "RESET_GUARD" in chain.stderr
    assert "JUDGED BY:" in chain.stderr and str(ROOT.resolve()) in chain.stderr.replace("\\\\", "\\"), chain.stderr


# ============================================================ RC-544 adversarial proofs

def test_1_a_blocked_mutation_has_zero_effect_on_the_next_event(tmp_path):
    """Attempt a blocked destructive command, then an ordinary edit and an ordinary read:
    both are judged on their own payload; nothing the block did is visible to them."""
    blocked = _chain(bash("git reset --hard HEAD~1", cwd=ROOT))
    assert blocked.returncode == 2 and "RESET_GUARD" in blocked.stderr
    after_edit = _chain(edit(tmp_path / "scratch.py"))
    after_read = _chain(bash(f'cat "{ROOT / "AGENTS.md"}"', cwd=ROOT))
    assert after_edit.returncode == 0 and after_edit.stderr == "", after_edit.stderr
    assert after_read.returncode == 0 and after_read.stderr == "", after_read.stderr


def test_2_a_nonexistent_worktree_in_a_blocked_command_has_zero_future_effect(tmp_path):
    """The exact poisoning shape: a refused command naming a worktree that does not exist.
    The next events must not mention it, demand it, or refuse anything because of it."""
    ghost = tmp_path / "EdWebConsole-does-not-exist"
    blocked = _chain(bash(f'git -C "{ghost}" reset --hard && git branch -D main', cwd=ROOT))
    assert blocked.returncode == 2, blocked.stderr
    for later in (edit(tmp_path / "later.py"), bash("git status", cwd=ROOT),
                  {"hook_event_name": "Stop", "stop_hook_active": False}):
        r = _chain(later, roster=("tools/stop_guard.py",) if "hook_event_name" in later else PRE_ROSTER)
        assert r.returncode == 0, (later, r.stderr)
        assert ghost.name not in r.stderr and "cannot determine" not in r.stderr and "REFUSED" not in r.stderr


def test_3_read_only_actions_establish_nothing_and_pass():
    for command in (f'cat "{ROOT / "server.py"}"', f'git -C "{ROOT}" status --porcelain',
                    f'ls -la "{ROOT}"', "git log --oneline -3", "python -c \"print(1)\""):
        r = _chain(bash(command, cwd=ROOT))
        assert r.returncode == 0 and r.stderr == "", (command, r.stderr)


def test_4_a_malformed_payload_fails_safely_and_poisons_nothing(tmp_path):
    for junk in ("{not json", "", "[1,2]", "null"):
        r = _chain(junk)
        assert r.returncode == 2 and "cannot be judged" in r.stderr, (junk, r.stderr)
    ok = _chain(edit(tmp_path / "fine.py"))
    assert ok.returncode == 0 and ok.stderr == "", ok.stderr


def test_5_a_legitimate_edit_remains_possible(tmp_path):
    for target in (ROOT / "tests" / "test_hook_chain_v1.py", ROOT / "governance" / "root_cause_log.md",
                   ROOT / "tools" / "operator_law_guard.py", tmp_path / "anything.py"):
        r = _chain(edit(target))
        assert r.returncode == 0, (target, r.stderr)


def test_6_a_legitimate_commit_remains_possible_and_the_masked_forms_do_not():
    for command in ('git commit -m "x"', 'git add tools/x.py && git commit -m "y"',
                    'git -C "%s" commit -m "z"' % ROOT):
        r = _chain(bash(command, cwd=ROOT))
        assert r.returncode == 0, (command, r.stderr)
    for command in ('git commit -m "x" | tail -3', 'git commit --no-verify -m x', 'git add -A && git commit -m x'):
        r = _chain(bash(command, cwd=ROOT))
        assert r.returncode == 2, (command, r.stderr)


def test_7_the_session_checkout_judges_and_says_so_no_other_tree_is_ever_chosen(tmp_path):
    """There is no delegation path: a copy of the chain in another checkout judges its own
    session and names itself; this checkout's run never names another tree."""
    other = tmp_path / "other-checkout"
    (other / "tools").mkdir(parents=True)
    for rel in ("hook_chain.py", "process_lock_guard.py", "operating_process_lock.py", "pretooluse_guard.py",
                "shell_parse.py", "__init__.py"):
        shutil.copy(ROOT / "tools" / rel, other / "tools" / rel)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(other), check=True)
    here = _chain(bash("git reset --hard"))
    there = _chain(bash("git reset --hard"), roster=("tools/process_lock_guard.py",), root=other)
    assert str(ROOT.resolve()) in here.stderr.replace("\\\\", "\\") and str(other.resolve()) not in here.stderr
    assert str(other.resolve()) in there.stderr.replace("\\\\", "\\") and str(ROOT.resolve()) not in there.stderr
    src = (ROOT / "tools" / "hook_chain.py").read_text(encoding="utf-8")
    body = src.split('"""', 2)[-1]
    for gone in ("transcript", "delegat", "worktree list", "recovery", "session record", "ED_GOVERNANCE_AUTHORITY"):
        assert gone not in body.lower() if gone.islower() else gone not in body, gone


def test_the_executor_keeps_no_state_by_construction():
    """Structural half of the invariant: no file writes, no env writes, no transcript reads
    anywhere in the executor — there is no place for a prior event's effect to live."""
    tree = ast.parse((ROOT / "tools" / "hook_chain.py").read_text(encoding="utf-8"))
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert names == {"_git", "judge_banner", "run_chain", "_argv_members", "main"}, names
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = getattr(node.func, "attr", getattr(node.func, "id", ""))
            assert callee not in ("write_text", "write_bytes", "open", "putenv", "environ"), callee
