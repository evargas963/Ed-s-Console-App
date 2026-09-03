"""RC-512 — stale production governance can no longer judge work from the wrong tree.

Every test here drives the REAL `tools/stop_chain.py` in a REAL git repository with a REAL
linked worktree, over a real subprocess boundary. Nothing is mocked, because the defect was
not in anyone's model of the system — it was in which copy of the code actually ran.

THE SHAPE, reproduced rather than described. `.claude/settings.json` registers the hook as a
command relative to the session project directory, so the chain, its guards and their ledgers
all came from whichever checkout the session was launched in. On 2026-09-03 that checkout was
the production desk, 9 commits behind origin/main, and it ran `tools/proof_only_guard.py` — a
guard `main` had already DELETED for false-blocking a denial (RC-504) — against a turn whose
work was in a different worktree entirely.

So `primary` below carries a guard that ALWAYS BLOCKS, standing in for exactly that: a rule
the current tree no longer has. `linked` carries the same guard, passing. If authority
resolves correctly, work in `linked` is never blocked by `primary`'s withdrawn rule; if it
resolves wrongly, these tests fail the way the session did.
"""
from __future__ import annotations

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
    sys.stderr.write("STALE RULE FIRED: this guard exists only in the stale tree\\n")
    return 2
'''

PASSING_GUARD = '''"""The same guard as the current tree carries it: it does not fire."""


def main() -> int:
    return 0
'''


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if r.returncode != 0 and args[0] not in ("status", "rev-parse"):
        raise AssertionError(f"git {args} in {cwd}: {r.stderr}")
    return r


def _install_chain(tree: Path, guard_body: str) -> None:
    tools = tree / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    (tools / "__init__.py").write_text("", encoding="utf-8")
    (tools / "stop_chain.py").write_bytes(REAL_CHAIN.read_bytes())
    (tools / "demo_guard.py").write_text(guard_body, encoding="utf-8")


@pytest.fixture()
def trees(tmp_path):
    """A primary checkout and a linked worktree of ONE repository.

    The primary stands in for the production desk the session was launched from; the linked
    worktree stands in for where the work is actually happening.
    """
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "init", "-b", "main")
    _git(primary, "config", "user.email", "t@t.t")
    _git(primary, "config", "user.name", "t")
    _git(primary, "config", "core.autocrlf", "false")
    _install_chain(primary, BLOCKING_GUARD)
    _git(primary, "add", "-A")
    _git(primary, "commit", "-m", "primary: carries the stale blocking rule")

    linked = tmp_path / "linked"
    _git(primary, "worktree", "add", "-b", "work", str(linked))
    _install_chain(linked, PASSING_GUARD)
    _git(linked, "add", "-A")
    _git(linked, "commit", "-m", "linked: the rule no longer fires here")
    return primary, linked


def run_from(tree: Path, payload: dict, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke the chain the way the hook does: a roster on argv, the payload on stdin."""
    env = dict(os.environ)
    env.pop("ED_GOVERNANCE_AUTHORITY_DELEGATED", None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(tree / "tools" / "stop_chain.py"), "tools/demo_guard.py"],
        cwd=str(tree), input=json.dumps(payload), text=True, capture_output=True,
        env=env, timeout=300,
    )


def _write_transcript(path: Path, tool_target: Path, *, as_tool_use: bool = True) -> None:
    """A minimal transcript in the real shape: JSONL, tool_use blocks inside a message."""
    block = ({"type": "tool_use", "name": "Edit", "input": {"file_path": str(tool_target)}}
             if as_tool_use else
             {"type": "text", "text": f"I considered editing {tool_target} but did not."})
    lines = [
        json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "go"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [block]}}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- the two resolution shapes

def test_a_file_payload_is_judged_by_the_tree_the_file_is_in(trees):
    """The stale tree runs the hook; the work is elsewhere; the withdrawn rule must not fire."""
    primary, linked = trees
    result = run_from(primary, {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(linked / "some_app_file.py")},
    })
    assert result.returncode == 0, (
        "work in the linked worktree was judged by the stale tree's withdrawn rule — this is "
        f"the 2026-09-03 false block, unfixed.\nSTDERR:\n{result.stderr}")
    assert "STALE RULE FIRED" not in result.stderr, result.stderr


def test_a_stop_event_is_judged_by_the_tree_the_session_worked_in(trees, tmp_path):
    """The half the first cut could not answer.

    A Stop payload names no file. The earlier resolver returned None and the bootstrap tree
    judged by default — which IS the defect, since the bootstrap tree is wherever the session
    was launched. The session's own transcript records where its work went.
    """
    primary, linked = trees
    transcript = tmp_path / "session.jsonl"
    _write_transcript(transcript, linked / "some_app_file.py")

    result = run_from(primary, {
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "transcript_path": str(transcript),
    })
    assert result.returncode == 0, (
        "a Stop event was judged by the tree the session was LAUNCHED in rather than the tree "
        f"it WORKED in.\nSTDERR:\n{result.stderr}")
    assert "STALE RULE FIRED" not in result.stderr, result.stderr


# ------------------------------------------------------------------------ it still blocks

def test_delegation_returns_the_authority_tree_s_real_verdict(trees):
    """Not a way to make blocks disappear: when the authority tree blocks, the block stands."""
    primary, linked = trees
    (linked / "tools" / "demo_guard.py").write_text(BLOCKING_GUARD, encoding="utf-8")
    _git(linked, "add", "-A")
    _git(linked, "commit", "-m", "linked: this tree carries the rule too")

    result = run_from(primary, {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(linked / "some_app_file.py")},
    })
    assert result.returncode != 0, "a real block was lost in transit"
    assert "STALE RULE FIRED" in result.stderr, result.stderr


def test_a_tree_with_uncommitted_guards_is_refused_authority(trees):
    """An agent may not edit a guard and then be judged by the edit.

    The delegation would otherwise hand governance to a working copy the subject just wrote.
    A COMMITTED guard change is fine — that is ordinary development answering to CI at merge —
    so the trigger is uncommitted state, not change.
    """
    primary, linked = trees
    (linked / "tools" / "demo_guard.py").write_text(
        "def main() -> int:\n    return 0  # neutered, uncommitted\n", encoding="utf-8")

    result = run_from(primary, {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(linked / "some_app_file.py")},
    })
    assert result.returncode != 0, (
        "authority was handed to a tree whose guards exist only in its working copy")
    assert "STALE RULE FIRED" in result.stderr, result.stderr
    assert "UNCOMMITTED guard files" in result.stderr, result.stderr


def test_a_path_outside_this_repository_cannot_take_authority(trees, tmp_path):
    """The trust boundary: only worktrees of THIS repo may judge.

    Resolution reads paths the agent influences, so a prepared directory with obliging guards
    is the obvious attack on it. `repo_worktrees()` is why that directory is never selected.
    """
    primary, _linked = trees
    outsider = tmp_path / "outsider"
    _install_chain(outsider, PASSING_GUARD)
    _git(outsider, "init", "-b", "main")
    _git(outsider, "config", "user.email", "t@t.t")
    _git(outsider, "config", "user.name", "t")
    _git(outsider, "add", "-A")
    _git(outsider, "commit", "-m", "a different repository entirely")

    result = run_from(primary, {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(outsider / "anything.py")},
    })
    assert result.returncode != 0, (
        "governance was delegated OUT of this repository to a directory that merely looked "
        "like a checkout")
    assert "STALE RULE FIRED" in result.stderr, result.stderr


def test_authority_hops_exactly_once(trees):
    """The delegate must judge, not delegate again — one hop, enforced by the env marker."""
    primary, linked = trees
    result = run_from(
        primary,
        {"tool_name": "Edit", "tool_input": {"file_path": str(linked / "f.py")}},
        env_extra={"ED_GOVERNANCE_AUTHORITY_DELEGATED": "1"},
    )
    assert result.returncode != 0, "a delegated run delegated again instead of judging"
    assert "STALE RULE FIRED" in result.stderr, result.stderr


def test_prose_that_merely_quotes_a_path_is_not_a_place_work_happened(trees, tmp_path):
    """Transcript resolution reads TOOL TARGETS, not assistant text.

    A transcript carries prose, and prose names paths the session never touched. Matching
    them would let a sentence choose the tree that judges the turn.
    """
    primary, linked = trees
    transcript = tmp_path / "session.jsonl"
    _write_transcript(transcript, linked / "some_app_file.py", as_tool_use=False)

    result = run_from(primary, {
        "hook_event_name": "Stop",
        "transcript_path": str(transcript),
    })
    assert result.returncode != 0, (
        "a path merely MENTIONED in assistant prose was accepted as the session's work tree")
    assert "STALE RULE FIRED" in result.stderr, result.stderr


def test_an_unresolvable_event_is_judged_here_and_says_so(trees):
    """No signal at all: the bootstrap judges, and the banner names it. Never a silent skip."""
    primary, _linked = trees
    result = run_from(primary, {"hook_event_name": "Stop"})
    assert result.returncode != 0
    assert "STALE RULE FIRED" in result.stderr, result.stderr
    assert "GOVERNANCE AUTHORITY:" in result.stderr, result.stderr
    assert "[bootstrap]" in result.stderr, result.stderr


def test_every_block_names_the_tree_that_judged_it(trees):
    """The 2026-09-03 block named a rule but never its tree, so staleness read as a mystery."""
    primary, _linked = trees
    result = run_from(primary, {"hook_event_name": "Stop"})
    assert result.returncode != 0
    assert str(primary.resolve()) in result.stderr.replace("\\\\", "\\"), result.stderr


# ------------------------------------------------------------------ resolver unit controls

def test_canonical_authority_prefers_the_work_target_over_the_session_record(tmp_path):
    """Both signals present: the file being touched NOW wins over where the session has been."""
    from tools.stop_chain import canonical_authority

    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, REPO / "server.py")
    tree, source = canonical_authority(json.dumps({
        "tool_input": {"file_path": str(REPO / "config" / "decision_path_admissions.json")},
        "transcript_path": str(transcript),
    }))
    assert tree == REPO and source == "work target", (tree, source)


def test_canonical_authority_falls_back_to_the_session_record_then_to_this_tree(tmp_path):
    from tools.stop_chain import REPO as CHAIN_REPO, canonical_authority

    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, REPO / "server.py")
    tree, source = canonical_authority(json.dumps({"transcript_path": str(transcript)}))
    assert tree == REPO and source == "session record", (tree, source)

    for junk in ("", "not json", json.dumps(["a", "list"]), json.dumps({}),
                 json.dumps({"transcript_path": str(tmp_path / "missing.jsonl")})):
        tree, source = canonical_authority(junk)
        assert tree == CHAIN_REPO and source == "bootstrap", (junk[:30], tree, source)


def test_this_repository_is_its_own_authority_for_its_own_files():
    """Sanity on the live tree: no delegation loop, no surprise third party."""
    from tools.stop_chain import REPO as CHAIN_REPO, repo_worktrees, resolve_authority

    assert CHAIN_REPO in repo_worktrees()
    root, _source, why = resolve_authority(
        json.dumps({"tool_input": {"file_path": str(REPO / "server.py")}}),
        ("tools.stop_guard",),
    )
    assert root == CHAIN_REPO, (root, why)
