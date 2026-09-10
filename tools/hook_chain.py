"""The ONE hook executor: runs the rostered guards in-process on one payload; worst exit wins.

Wired by `.claude/settings.json` / `.cursor/hooks.json` as
    python tools/hook_chain.py tools/<guard>.py [tools/<guard>.py ...]
for PreToolUse (operator_law_guard + process_lock_guard) and Stop (stop_guard). One process
instead of one interpreter per guard (SIMPLICITY REHAB, 2026-08-24: ~300ms vs 2.8-6s).

What it does, entirely: read the payload; refuse one that is not a JSON object (RC-541 —
"cannot judge" and "judged clean" must not share an exit code); import each guard and call its
`main()` on the identical stdin; a guard that crashes is a BLOCK (unmeasurable is never
compliant, RC-57); on any block, print which checkout and commit judged the event, so a stale
checkout's rule never reads as a mystery (RC-512).

What it deliberately does NOT do (deleted 2026-09-10, RC-544/RC-546). It keeps no state
between events and it never chooses another tree to judge: the earlier executor resolved
"authority" from the session transcript and delegated to other worktrees' chains, with a
crashed-delegate recovery door and an uncommitted-guard refusal on top. A transcript cannot
tell an executed mutation from one the hook refused, so one BLOCKED command poisoned every
later event; and none of that machinery protected anything the checkout's own guards, the
pre-commit hooks of the target tree and required CI do not already protect. The guards judge
the ACTION in the payload; the checkout that runs the session is the checkout whose guards
run, and the operator launches sessions in the tree they work in (AGENT_OPERATING_PROCESS §6).

INVARIANT: BLOCKED OR UNEXECUTED ACTION => ZERO MUTATION => ZERO EFFECT ON ANY LATER EVENT.
There is no place for an effect to live.
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

#: RC-520: THE roster of tools that carry a shell `command`; both shell guards import it.
BASH_TOOLS = frozenset({"Bash", "PowerShell", "Shell", "Monitor"})

#: THE roster of file-target tools that MODIFY a tree: Claude's Edit/Write/MultiEdit/
#: NotebookEdit and Cursor's StrReplace/Delete (RC-226). Imported by every guard that decides
#: the class; the four private copies that existed until 2026-09-10 were the RC-520 shape.
MUTATING_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit", "StrReplace", "Delete"})

#: Default Stop roster when no argv is given; the hook files pass the roster explicitly.
STOP_CHAIN = ("tools.stop_guard",)


def _git(*args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True,
                           text=True, timeout=15, check=False)
        return (r.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def judge_banner() -> str:
    """Which checkout and commit judged the event — printed on every block."""
    head = _git("rev-parse", "--short", "HEAD") or "unknown"
    branch = _git("symbolic-ref", "--short", "HEAD") or "detached"
    return f"JUDGED BY: {REPO} @ {branch} {head}"


def run_chain(raw_payload: str, members: tuple[str, ...] = STOP_CHAIN) -> int:
    """Run every member on the same payload; the worst exit code wins (2 = block)."""
    try:
        parsed = json.loads(raw_payload)
    except (json.JSONDecodeError, ValueError, TypeError):
        parsed = None
    if not isinstance(parsed, dict):
        sys.stderr.write("HOOK CHAIN: the hook payload is not a readable JSON object; the event "
                         "cannot be judged and is refused. Unreadable is not clean.\n")
        return 2
    worst = 0
    for name in members:
        try:
            mod = importlib.import_module(name)
            sys.stdin = io.StringIO(raw_payload)
            rc = int(mod.main() or 0)
        except SystemExit as exc:          # a guard that sys.exit()s inside main()
            rc = int(exc.code or 0)
        except Exception as exc:  # noqa: BLE001 — a broken guard must scream, not wave through
            sys.stderr.write(f"HOOK CHAIN: {name} crashed: {type(exc).__name__}: {exc}\n")
            rc = 2
        worst = max(worst, rc)
    if worst:
        sys.stderr.write(judge_banner() + "\n")
    return 2 if worst else 0


def _argv_members(argv: list[str]) -> tuple[str, ...]:
    """Roster from the command line: 'tools/stop_guard.py' -> 'tools.stop_guard'."""
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
