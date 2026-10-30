"""The Stop hook (AGENTS.md Authority: work continues until SHAPE is finished): while
ACTIVE_PROGRAM.md's SHAPE row is IN PROGRESS, the agent's attempt to end its turn is refused and it
is sent back to the next step.

The one way through is a stop the rules require: the agent's final message begins
`WAITING ON OPERATOR:` and names why (AGENTS.md Authority's stop list; CLAUDE.md items 3, 5 and 6).
Wired by `.claude/settings.json` (Stop).

    python tools/keep_going.py < payload.json
Prints Claude Code's `{"decision": "block", "reason": ...}` to refuse the stop; prints nothing to
let it end. The SHAPE row is read first, so once SHAPE is finished no session is held. The final
message is the payload's `last_assistant_message` when Claude Code sends one, else the transcript's
last assistant entry (a line that is not a JSON object is skipped, so one damaged line never
decides every later stop). A work list it cannot read, and while SHAPE is open a payload or
transcript it cannot read, exits 2 with the reason, which also refuses the stop: "cannot judge"
never reads as "may stop" (tests/test_hook_chain_v1.py).
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


#: how much of the transcript's end is read first (a long session's transcript runs past 100 MB)
TAIL_BYTES = 4 * 1024 * 1024


def _last_assistant(text: str) -> dict | None:
    last = None
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if (
            isinstance(entry, dict)
            and entry.get("type") == "assistant"
            and not entry.get("isSidechain")  # a subagent's message is not the agent's
        ):
            last = entry
    return last


def last_message(transcript: Path) -> str:
    """The text of the transcript's last assistant entry (JSON lines); "" when that entry carries
    no text (a turn ending on a tool call), so an older message never stands in for it. The end of
    the file is read first; the whole file only when the end holds no assistant entry."""
    with transcript.open("rb") as f:
        size = f.seek(0, 2)
        f.seek(max(0, size - TAIL_BYTES))
        tail = f.read().decode("utf-8", errors="replace")
    last = _last_assistant(tail)
    if last is None and size > TAIL_BYTES:
        last = _last_assistant(transcript.read_text(encoding="utf-8", errors="replace"))
    message = last.get("message") if last is not None else None
    parts = message.get("content") if isinstance(message, dict) else None
    return "\n".join(
        p["text"]
        for p in (parts if isinstance(parts, list) else [])
        if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str)
    )


def decide(work_list: str, last: str) -> str | None:
    """Why the stop is refused, or None when it may end."""
    if not OPEN.search(work_list):
        return None
    if last.lstrip().startswith(WAITING):
        return None
    return (
        "SHAPE in ACTIVE_PROGRAM.md is IN PROGRESS: take its next step now (AGENTS.md Authority: "
        "work continues until SHAPE is finished; merges do not wait on the operator). Stop only "
        "for a stop the rules require (AGENTS.md Authority's stop list; CLAUDE.md items 3, 5 and "
        "6), "
        f"saying why in a message that begins `{WAITING}`."
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        work_list = WORK_LIST.read_text(encoding="utf-8")
        if not OPEN.search(work_list):
            return 0
        said = payload.get("last_assistant_message")
        last = said if isinstance(said, str) else last_message(Path(payload["transcript_path"]))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
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
