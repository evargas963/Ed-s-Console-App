"""The Stop hook (operator 2026-10-29: "do not stop until you are finished"; "you are allowed to
continue until you finish"): while ACTIVE_PROGRAM.md's SHAPE row is IN PROGRESS, the agent's
attempt to end its turn is refused and it is sent back to the next step.

The one way through is the operator's own: the agent's last message begins with
`WAITING ON OPERATOR:` and names what only he can do (CLAUDE.md item 5: a production start or stop
during regular hours or an unknown session). Wired by `.claude/settings.json` (Stop).

    python tools/keep_going.py < payload.json
Prints Claude Code's `{"decision": "block", "reason": ...}` to refuse the stop; prints nothing to
let it end. A payload, transcript or work list it cannot read exits 2 with the reason, which also
refuses the stop: "cannot judge" never reads as "may stop" (tests/test_hook_chain_v1.py).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORK_LIST = REPO / "ACTIVE_PROGRAM.md"
WAITING = "WAITING ON OPERATOR:"
#: the SHAPE row while any of its steps is left
OPEN = re.compile(r"^\| SHAPE \| IN PROGRESS \|", re.M)


def last_message(transcript: Path) -> str:
    """The text of the agent's last message in the session transcript (JSON lines)."""
    text = ""
    for line in transcript.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        message = entry.get("message") if entry.get("type") == "assistant" else None
        parts = message.get("content") if isinstance(message, dict) else None
        said = [
            p.get("text", "")
            for p in parts or []
            if isinstance(p, dict) and p.get("type") == "text"
        ]
        if any(said):
            text = "\n".join(s for s in said if s)
    return text


def decide(work_list: str, last: str) -> str | None:
    """Why the stop is refused, or None when it may end."""
    if not OPEN.search(work_list):
        return None
    if last.lstrip().startswith(WAITING):
        return None
    return (
        "SHAPE in ACTIVE_PROGRAM.md is IN PROGRESS: take its next step now (the operator, "
        "2026-10-29: continue until finished; merges do not wait on his yes). Stop only when what "
        f"is left is his alone, saying so in a message that begins `{WAITING}`."
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        work_list = WORK_LIST.read_text(encoding="utf-8")
        last = last_message(Path(payload["transcript_path"]))
    except (OSError, ValueError, KeyError, TypeError) as e:
        sys.stderr.write(
            f"keep_going cannot judge the stop ({e!r}); keep working and fix the hook\n"
        )
        return 2
    why = decide(work_list, last)
    if why is not None:
        print(json.dumps({"decision": "block", "reason": why}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
