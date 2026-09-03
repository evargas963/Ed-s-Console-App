"""ONE Stop process instead of five (SIMPLICITY REHAB, operator full-go 2026-08-24).

MEASURED before this change: the Stop chain spawned five Python interpreters —
stop_guard 632ms + proof_only_guard 459ms + honesty_guard 526ms + operator_law_guard
741ms + process_lock_guard 457ms = 2,815ms per turn end, of which ~2.3s was pure
interpreter startup. This entrypoint imports the SAME five guards and calls their
unmodified main() functions in-process, feeding each the identical payload the harness
would have piped to it. No predicate is weakened, reordered, or skipped: every guard
still runs on every Stop, every guard's stderr still reaches the agent, and a block
from ANY guard still blocks the turn (exit 2), exactly as the five-command chain
behaved. The guards stay independently runnable — this file is wiring, not authority.

Chain members (each file is the lock; this list is the wiring contract the tests pin):
    tools/stop_guard.py
    tools/honesty_guard.py
    tools/operator_law_guard.py
process_lock_guard is deliberately NOT in the Stop chain: its Stop path measured 3.18s
(the bulk of the whole chain) and the dereg landed (PR #187 / RC-471) —
process_lock_guard remains on every PreToolUse, where its process-integrity rails
(cross-checkout protection, destructive/piped git) actually bind.

proof_only_guard was REMOVED from this chain and deleted (RC-504, operator 2026-09-02).
It decided truth and completion by matching words in prose, and that was experimentally
confirmed to false-block: the sentence "rather than tell you again from memory" — a
DISCLAIMER of memory written immediately before running commands — was flagged as citing
memory as evidence, because a substring cannot tell an assertion from a denial. Its
structural half, the transcript readers, moved to tools/operator_law_guard.py, which
already owns turn and session identity. No replacement was built: there is no vocabulary
list, regex escape or successor guard, because the defect was the approach.
"""
from __future__ import annotations

import importlib
import io
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: Order preserved from .claude/settings.json's serial chain (process_lock_guard
#: dereg'd from Stop per the docstring; it stays on PreToolUse).
STOP_CHAIN = (
    "tools.stop_guard",
    "tools.honesty_guard",
    "tools.operator_law_guard",
)


def _git(cwd: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                           text=True, timeout=15, check=False)
        return (r.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def repo_worktrees() -> set[Path]:
    """Every checkout of THIS repository — the only paths that may hold authority.

    RC-512 trust boundary. Authority is resolved from paths that appear in a hook payload or
    a session transcript, both of which the agent influences. Confining the answer to real
    worktrees of this repo means the worst that can be selected is a different legitimate
    checkout, never a directory prepared with guards of its own.
    """
    out: set[Path] = set()
    for line in _git(REPO, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            try:
                out.add(Path(line[len("worktree "):].strip()).resolve())
            except OSError:
                continue
    out.add(REPO)
    return out


def _member_files(members: tuple[str, ...]) -> list[str]:
    """Repo-relative paths of the rostered guards plus the executor that runs them."""
    out = ["tools/stop_chain.py", "tools/pretooluse_chain.py"]
    for name in members:
        out.append(name.replace(".", "/") + ".py")
    return sorted(set(out))


def uncommitted_guard_files(root: Path, members: tuple[str, ...]) -> list[str]:
    """Rostered guard files with uncommitted changes in `root` — empty means clean.

    Authority may not be handed to a tree whose guards exist only in its working copy. An
    agent that edits a guard would otherwise be judged by that edit on its very next action,
    and a control the subject can rewrite mid-session is not a control (RC-450: subject-
    controlled state cannot authorize around a mandatory one). A COMMITTED guard change is
    fine — that is ordinary development, and it answers to required CI at merge.
    """
    status = _git(root, "status", "--porcelain", "--", *_member_files(members))
    return sorted(line[3:].strip().strip('"') for line in status.splitlines() if len(line) > 3)


def authority_banner(root: Path, source: str, note: str = "") -> str:
    """Which tree judged this event, how it was chosen, and where that tree stands.

    RC-512. A wrong-tree judgement used to be SILENT: the block named a rule but never the
    tree the rule came from, so a stale checkout enforcing a withdrawn rule read as a mystery
    instead of as staleness. This adds no verdict and can block nothing — it only says who
    spoke, and why they were the one asked.
    """
    head = _git(root, "rev-parse", "--short", "HEAD") or "unknown"
    branch = _git(root, "symbolic-ref", "--short", "HEAD") or "detached"
    tail = f" - {note}" if note else ""
    return f"GOVERNANCE AUTHORITY: {root} @ {branch} {head} [{source}]{tail}"


def _enclosing_worktree(target: Path) -> Path | None:
    """The nearest ancestor of `target` that is a worktree of THIS repository.

    A `.git` probe alone would also accept an unrelated repository — a linked worktree's
    `.git` is a FILE and the primary's is a directory, and both shapes exist everywhere — so
    membership is confirmed against `repo_worktrees()` rather than inferred from layout.
    """
    try:
        p = target if target.is_absolute() else (Path.cwd() / target)
        p = p.resolve()
    except OSError:
        return None
    known = repo_worktrees()
    for cand in (p, *p.parents):
        if cand in known:
            return cand
    return None


def _payload(raw_payload: str) -> dict:
    try:
        data = json.loads(raw_payload)
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return {}
    return data if isinstance(data, dict) else {}


def payload_work_tree(raw_payload: str) -> Path | None:
    """The worktree this tool call TARGETS, or None when the payload names no path.

    RC-512: the tree being changed is the tree whose rules apply. Editing a file in worktree
    X was judged by the guards and the root_cause_log of whatever tree the session started
    in, which is a different question from the one the guards mean to ask.
    """
    tool_input = _payload(raw_payload).get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "notebook_path", "path"):
        raw = tool_input.get(key)
        if isinstance(raw, str) and raw.strip():
            return _enclosing_worktree(Path(raw))
    return None


#: How much of a transcript's tail to read when resolving a no-file event. The most recent
#: file target is near the end by construction, and a long session's transcript is far more
#: than a hook is allowed to spend time on.
_TRANSCRIPT_TAIL_BYTES = 2_000_000


def _transcript_tail(path: Path) -> list[str]:
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > _TRANSCRIPT_TAIL_BYTES:
                fh.seek(size - _TRANSCRIPT_TAIL_BYTES)
                fh.readline()               # drop the partial line the seek landed inside
            return fh.read().decode("utf-8", errors="replace").splitlines()
    except (OSError, ValueError):
        return []


def _file_paths_in(node) -> list[str]:
    """Every file path a transcript record names as a TOOL TARGET, however nested.

    Walked structurally rather than pattern-matched over the raw line, because a transcript
    also carries assistant prose that can quote a path the session never touched, and a
    quoted path is not a place where work happened.
    """
    found: list[str] = []
    if isinstance(node, dict):
        if node.get("type") == "tool_use" and isinstance(node.get("input"), dict):
            for key in ("file_path", "notebook_path", "path"):
                val = node["input"].get(key)
                if isinstance(val, str) and val.strip():
                    found.append(val)
        for value in node.values():
            found.extend(_file_paths_in(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_file_paths_in(item))
    return found


def transcript_work_tree(raw_payload: str) -> Path | None:
    """Where this session's work actually went, read from its own transcript.

    This is the half a no-file event needs, and the half the first cut could not answer. A
    turn-end names no file, so the earlier resolver returned None and the bootstrap tree
    judged by default — which is precisely the defect, since the bootstrap tree is wherever
    the session was launched. But the session RECORDED every file it edited, so the most
    recent one establishes which checkout the work is in. That is evidence, not a guess.

    Scanned newest-first and stopped at the first hit: an older entry says where the session
    used to be working, which is a different question.
    """
    raw = _payload(raw_payload).get("transcript_path")
    if not isinstance(raw, str) or not raw.strip():
        return None
    for line in reversed(_transcript_tail(Path(raw))):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        for candidate in reversed(_file_paths_in(record)):
            tree = _enclosing_worktree(Path(candidate))
            if tree is not None:
                return tree
    return None


def canonical_authority(raw_payload: str) -> tuple[Path, str]:
    """THE governance authority for this event, and how it was established.

    ONE resolver for both shapes, so there is a single answer to "who judges this" instead of
    a rule for edits and a shrug for everything else:

        payload names a path -> the worktree containing it        (work target)
        payload names none   -> the worktree of the most recent file this session edited,
                                read from its own transcript      (session record)
        neither resolvable   -> this tree, said out loud          (bootstrap)
    """
    tree = payload_work_tree(raw_payload)
    if tree is not None:
        return tree, "work target"
    tree = transcript_work_tree(raw_payload)
    if tree is not None:
        return tree, "session record"
    return REPO, "bootstrap"


# RC-512 — GOVERNANCE AUTHORITY, and why the resolvers above exist.
#
# THE DEFECT. `.claude/settings.json` registers the hook as a command RELATIVE to the session
# project directory, and REPO above is derived from this file's own location. So the guards
# that judged an event, and every ledger they read, came from whichever checkout the session
# happened to be launched in — in practice the production APP RUNTIME tree, because that is
# where the desk lives. Being launched somewhere is not a reason to be governed by it.
#
# OBSERVED 2026-09-03: a chain sourced from a production checkout 9 commits behind origin/main
# ran `tools/proof_only_guard.py` — a guard main had already DELETED for false-blocking a
# denial (RC-504) — and it false-blocked a turn whose work was in a different worktree
# entirely. Stale code enforcing a withdrawn rule, and the block never said which tree it came
# from, so it read as a mystery rather than as staleness.
#
# THE RULE, resolved from evidence in BOTH shapes (`canonical_authority`):
#     payload names a path -> the worktree containing it                    work target
#     payload names none   -> the worktree of the most recent file this session edited,
#                             read from its own transcript                  session record
#     neither resolvable   -> this tree, said out loud                      bootstrap
#
# The middle line is what makes Stop and every other no-file event answerable. The first cut
# returned None there and the bootstrap judged by default, which is the defect itself.
#
# WHAT IT DOES NOT DO. It never decides to skip guards: every path either delegates to a real
# worktree that runs the IDENTICAL roster, or runs that roster here. Authority is confined to
# `repo_worktrees()`, so a prepared directory can never be selected. A tree with UNCOMMITTED
# guard files is refused, so an agent cannot edit a guard and be judged by the edit. And a
# delegate that crashes or times out BLOCKS.


#: Set on a delegated run so authority hops exactly ONCE and can never loop.
DELEGATED_ENV = "ED_GOVERNANCE_AUTHORITY_DELEGATED"


def _delegate(root: Path, raw_payload: str, members: tuple[str, ...]) -> int:
    """Run the IDENTICAL roster under `root`'s governance and return its verdict.

    The roster travels as argv, so the member list cannot be shortened on the way across and
    `.claude/settings.json` stays the reviewable authority over which guards run. Fail-closed:
    a delegate that crashes, times out, or cannot be spawned returns non-zero, because an
    unmeasurable guard run is not a passing one (RC-57).
    """
    import os

    entry = root / "tools" / "stop_chain.py"
    argv = [f"tools/{name.split('.')[-1]}.py" for name in members]
    env = dict(os.environ)
    env[DELEGATED_ENV] = "1"
    try:
        proc = subprocess.run(
            [sys.executable, str(entry), *argv], cwd=str(root), env=env,
            input=raw_payload, text=True, capture_output=True, timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        sys.stderr.write(
            f"GOVERNANCE AUTHORITY: delegation to {root} failed "
            f"({type(exc).__name__}: {exc}); blocking, because a guard run that did not "
            f"happen is not a guard run that passed.\n")
        return 2
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.returncode


def resolve_authority(raw_payload: str, members: tuple[str, ...]) -> tuple[Path, str, str]:
    """Who judges this event: (tree, how it was chosen, why not the resolved one).

    Separated from the acting so the decision is testable on its own, and so the reason a
    delegation did NOT happen is a value rather than a silence.
    """
    import os

    if os.environ.get(DELEGATED_ENV) == "1":
        return REPO, "delegated run", "already delegated; this IS the authority"
    root, source = canonical_authority(raw_payload)
    if root == REPO:
        return REPO, source, ""
    if not (root / "tools" / "stop_chain.py").is_file():
        return REPO, "bootstrap", f"{root} carries no chain to delegate to"
    dirty = uncommitted_guard_files(root, members)
    if dirty:
        return REPO, "bootstrap", (
            f"{root} has UNCOMMITTED guard files ({', '.join(dirty)}); a tree cannot be "
            f"handed authority over its own unreviewed guard edits")
    return root, source, ""


def run_chain(raw_payload: str, members: tuple[str, ...] = STOP_CHAIN) -> int:
    """Run every member on the same payload; the worst exit code wins.

    A guard that crashes is a BLOCK, not a pass (unmeasurable is never compliant —
    RC-57): its traceback goes to stderr and the chain reports exit 2.

    RC-512: before running anything, ask WHO should be running it. When the authority is a
    different worktree of this repository, the identical roster runs there and its verdict is
    returned unchanged. When it is this tree, the roster runs here and every BLOCK says so.
    No path skips the roster; the only question this settles is which checkout's copy of it
    answers, and no verdict is ever softened on the way back.
    """
    root, source, why_here = resolve_authority(raw_payload, members)
    if root != REPO:
        return _delegate(root, raw_payload, members)
    worst = 0
    for name in members:
        try:
            mod = importlib.import_module(name)
            sys.stdin = io.StringIO(raw_payload)
            rc = int(mod.main() or 0)
        except SystemExit as exc:          # a guard that sys.exit()s inside main()
            rc = int(exc.code or 0)
        except Exception as exc:  # noqa: BLE001 — a broken guard must scream, not wave through
            sys.stderr.write(f"STOP CHAIN: {name} crashed: {type(exc).__name__}: {exc}\n")
            rc = 2
        worst = max(worst, rc)
    if worst:
        sys.stderr.write(authority_banner(REPO, source, why_here) + "\n")
    return 2 if worst else 0


def _argv_members(argv: list[str]) -> tuple[str, ...]:
    """Roster from the command line: 'tools/stop_guard.py' -> 'tools.stop_guard'.

    The hook files pass the roster EXPLICITLY, so the wiring stays reviewable in
    .claude/settings.json / .cursor/hooks.json and the existing name-pin tests keep
    binding the real thing. No argv -> the default STOP_CHAIN."""
    out = []
    for a in argv:
        a = a.replace("\\", "/").removeprefix("tools/").removesuffix(".py")
        if a:
            out.append(f"tools.{a}")
    return tuple(out)


def main() -> int:
    members = _argv_members(sys.argv[1:]) or STOP_CHAIN
    return run_chain(sys.stdin.read(), members)


if __name__ == "__main__":
    sys.exit(main())
