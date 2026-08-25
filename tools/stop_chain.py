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
    tools/proof_only_guard.py
    tools/honesty_guard.py
    tools/operator_law_guard.py
process_lock_guard is deliberately NOT in the Stop chain: its Stop path measured 3.18s
(the bulk of the whole chain) and the dereg landed (PR #187 / RC-471) —
process_lock_guard remains on every PreToolUse, where its process-integrity rails
(cross-checkout protection, destructive/piped git) actually bind.
"""
from __future__ import annotations

import importlib
import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: Order preserved from .claude/settings.json's serial chain (process_lock_guard
#: dereg'd from Stop per the docstring; it stays on PreToolUse).
STOP_CHAIN = (
    "tools.stop_guard",
    "tools.proof_only_guard",
    "tools.honesty_guard",
    "tools.operator_law_guard",
)


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
