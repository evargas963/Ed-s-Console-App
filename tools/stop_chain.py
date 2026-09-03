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


def authority_banner() -> str:
    """Which tree just judged this event, and where that tree stands.

    RC-512. A wrong-tree judgement used to be SILENT. `.claude/settings.json` registers the
    hook command as a path relative to the session project directory, so the guards and every
    ledger they read come from whichever checkout the session was launched in — in practice
    the production APP RUNTIME tree, because that is where the desk lives. OBSERVED
    2026-09-03: a Stop chain sourced from a production checkout 9 commits behind origin/main
    ran `tools/proof_only_guard.py`, a guard main had already DELETED for false-blocking a
    denial (RC-504), and it false-blocked the turn. The block named a rule but never the tree
    the rule came from, so it read as a mystery instead of as staleness.

    This adds no verdict and can block nothing — it only says who spoke.
    """
    def git(*args: str) -> str:
        try:
            r = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True,
                               text=True, timeout=10, check=False)
            return (r.stdout or "").strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    head = git("rev-parse", "--short", "HEAD") or "unknown"
    branch = git("symbolic-ref", "--short", "HEAD") or "detached"
    return f"GOVERNANCE AUTHORITY: {REPO} @ {branch} {head}"


def _enclosing_worktree(target: Path) -> Path | None:
    """The nearest ancestor of `target` holding a `.git` entry — a directory OR a file.

    A linked worktree's `.git` is a FILE, the primary's is a directory; both count, because
    the question is "which checkout is this path in", not "which is primary".
    """
    try:
        p = target if target.is_absolute() else (Path.cwd() / target)
        p = p.resolve()
    except OSError:
        return None
    for cand in (p, *p.parents):
        try:
            if (cand / ".git").exists():
                return cand
        except OSError:
            return None
    return None


def payload_work_tree(raw_payload: str) -> Path | None:
    """The worktree this tool call TARGETS, or None when the payload names no path.

    RC-512: the tree being changed is the tree whose rules apply. Editing a file in worktree
    X was judged by the guards and the root_cause_log of whatever tree the session started
    in, which is a different question from the one the guards mean to ask.

    Returns None for Stop events on purpose: a turn-end names no file, so there is no
    work-tree signal, and inventing one would be a guess. `authority_banner` is the answer
    there — provenance, not delegation.
    """
    try:
        payload = json.loads(raw_payload) or {}
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return None
    if not isinstance(payload, dict):
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "notebook_path", "path"):
        raw = tool_input.get(key)
        if isinstance(raw, str) and raw.strip():
            return _enclosing_worktree(Path(raw))
    return None


# RC-512, STATED PLAINLY: the three helpers above are NOT WIRED into the chain.
#
# They are the resolved, testable halves of the agent-side fix — "which tree is this work
# in" and "which tree just judged this event". The two edits that would consume them, a
# delegation step and a provenance line on every block, were REFUSED by this environment's
# permission classifier, which declines any change to the guard executor. That is a correct
# refusal for that class of edit: changing where guards are sourced from, or what a block
# prints, is a bypass-shaped capability and should need explicit authorization.
#
# So the coupling they address is still LIVE: `.claude/settings.json` registers its hook
# command as a path relative to the session project directory, and REPO above is derived
# from this file's own location, so a session started in the production checkout is judged
# by the production checkout's guard code and ledgers. Nothing here changes that yet.


def run_chain(raw_payload: str, members: tuple[str, ...] = STOP_CHAIN) -> int:
    """Run every member on the same payload; the worst exit code wins.

    A guard that crashes is a BLOCK, not a pass (unmeasurable is never compliant —
    RC-57): its traceback goes to stderr and the chain reports exit 2.
    """
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
