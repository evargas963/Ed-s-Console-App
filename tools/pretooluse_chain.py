"""ONE PreToolUse process instead of two/three (SIMPLICITY REHAB, 2026-08-24).

MEASURED before this change: Edit/Write ran pretooluse_guard 506ms + operator_law_guard
741ms + process_lock_guard 457ms = 1,704ms per edit; Bash/PowerShell ran the latter two
= 1,198ms per command — most of it interpreter startup. This entrypoint imports the
SAME guards and calls their unmodified main() functions in-process on the identical
payload. Membership is selected by the payload's tool_name exactly as the two settings
matchers selected it; no predicate is weakened and a block from ANY member still blocks
(exit 2). The guards stay independently runnable — this file is wiring, not authority.

Chain members (each file is the lock; this list is the wiring contract the tests pin):
    Edit|Write|MultiEdit|NotebookEdit -> tools/operator_law_guard.py, tools/process_lock_guard.py
        (pretooluse_guard left the roster 2026-09-06 — bedrock doctrine; see EDIT_CHAIN)
    Bash|PowerShell|Monitor -> tools/operator_law_guard.py, tools/process_lock_guard.py

RC-520 (2026-09-05): Monitor joined the shell matcher. It runs a shell `command` exactly as
Bash does and was unmatched, so a Monitor call rewrote a tracked guard module with no guard
in the loop. The class itself is `tools.stop_chain.BASH_TOOLS`, imported by both shell guards.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.stop_chain import run_chain  # noqa: E402 — same executor, different roster

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
# BEDROCK 2026-09-06: pretooluse_guard left the roster. Its three content gates (prose
# matchers) and the mutation-side mission latch are removed; what it still owns,
# `classify_path`, is a function the other guards import, not a hook. A rostered guard that
# blocks nothing is an inert instrument wearing a name (agent_error_log E-05/E-07 class).
EDIT_CHAIN = ("tools.operator_law_guard", "tools.process_lock_guard")
BASH_CHAIN = ("tools.operator_law_guard", "tools.process_lock_guard")


def main() -> int:
    from tools.stop_chain import _argv_members
    raw = sys.stdin.read()
    explicit = _argv_members(sys.argv[1:])
    if explicit:                          # hook files pass the roster explicitly
        return run_chain(raw, explicit)
    try:
        tool = str((json.loads(raw) or {}).get("tool_name") or "")
    except (json.JSONDecodeError, ValueError):
        tool = ""
    members = EDIT_CHAIN if tool in EDIT_TOOLS else BASH_CHAIN
    return run_chain(raw, members)


if __name__ == "__main__":
    sys.exit(main())
