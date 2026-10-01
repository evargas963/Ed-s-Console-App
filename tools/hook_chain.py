"""The one hook executor: runs the rostered guards in-process on one payload; worst exit wins.

Wired by `.claude/settings.json` / `.cursor/hooks.json` as
    python tools/hook_chain.py tools/<guard>.py [tools/<guard>.py ...]
for PreToolUse (operator_law_guard + process_lock_guard), in one process instead of one
interpreter per guard.

What it does, entirely: read the payload; refuse one that is not a JSON object ("cannot judge"
and "judged clean" do not share an exit code); import each guard and call its `main()` on the
identical stdin; a guard that crashes is a block; on any block, print which checkout and commit
judged the event.

It keeps no state between events and never chooses another tree to judge: the guards judge the
action in the payload, and the checkout that runs the session is the checkout whose guards run.
A blocked or unexecuted action has no effect on any later event. The rules the guards refuse
live in `AGENTS.md` § Authority.
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


def run_chain(raw_payload: str, members: tuple[str, ...]) -> int:
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
    """Roster from the command line: 'tools/operator_law_guard.py' -> 'tools.operator_law_guard'."""
    out = []
    for a in argv:
        a = a.replace("\\", "/").removeprefix("tools/").removesuffix(".py")
        if a:
            out.append(f"tools.{a}")
    return tuple(out)


def main() -> int:
    members = _argv_members(sys.argv[1:])
    if not members:
        sys.stderr.write("HOOK CHAIN: no guard named; the event cannot be judged and is refused.\n")
        return 2
    return run_chain(sys.stdin.read(), members)


if __name__ == "__main__":
    sys.exit(main())
