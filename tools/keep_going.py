"""The Stop hook (AGENTS.md Authority: work continues until SHAPE is finished).

While ACTIVE_PROGRAM.md's SHAPE row is IN PROGRESS, the agent's attempt to end its turn is refused
and it is sent back to the next step.

The way through is a stop the rules allow: the agent's final message begins
`WAITING ON OPERATOR:` and names why (AGENTS.md Authority's stop list; CLAUDE.md items 3 and 5).
A wait on CI is not one: a pull request merges by itself, and the next step starts meanwhile.

Every message is read and every order answered (operator 2026-11-07: "once i tell you do
something, you must do it. you do not get to choose", "you must enforce this rule"; 2026-11-08:
"if i send you a message you must ask if it's an order and if it is an order then you must
immediately tell me if it breaks anything"): each message he sends is recorded as message n in the
session's ledger in ORDERS (`record_message`, run by tools/wiring_rules.py on every message), and
whatever the SHAPE row says, a stop is refused while a message is unread or an order unanswered.
The agent reads message n with a line `MESSAGE n READ: ORDER - <what>; BREAKS: <what it breaks or
conflicts with, or nothing>` or `MESSAGE n READ: NOT AN ORDER - <why>`, put to him to correct; an
order is answered with `ORDER n DONE: <evidence>` or `ORDER n PUSHBACK: <reason>`. A reading and
an answer are kept, so each is given once. The ledger is the session's, outside the repository.

Production runs what main holds (operator 2026-11-07, after Windows Update restarted the machine
on 2026-11-06 at 20:29 and Ed Console stayed down 25 hours with no one told): a stop is refused,
whatever SHAPE's row says, while the production checkout (this file's own, where the hooks run) is
not at its `origin/main` or nothing listens on the console's port, unless the final message begins
`WAITING ON OPERATOR:` (he may stop it himself). `origin/main` is as last fetched.

From the third refusal in a row the reason sends the agent to the cause and a different approach
(AGENTS.md Authority); the count is kept per session in COUNTS. Wired by `.claude/settings.json`
(Stop).

    python tools/keep_going.py < payload.json
Prints Claude Code's `{"decision": "block", "reason": ...}` to refuse the stop; prints nothing to
let it end. Once SHAPE is finished, only an unanswered order holds a session. The final
message is the payload's `last_assistant_message` when Claude Code sends one, else the transcript's
last assistant entry (a line that is not a JSON object is skipped, so one damaged line never
decides every later stop). A work list, payload, transcript or ledger it cannot read exits 2
with the reason, which also refuses the stop: "cannot judge" never reads as "may stop"
(tests/test_hook_chain_v1.py).
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
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
    """Return the text of the transcript's last assistant entry (JSON lines).

    "" when that entry carries no text (a turn ending on a tool call), so an older message never
    stands in for it. The end of the file is read first; the whole file only when the end holds no
    assistant entry.
    """
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


#: one ledger per session: a line per message the operator sent, per reading and per answer
ORDERS = Path(tempfile.gettempdir()) / "ed_orders"
#: the agent's reading of message n: an order with what it breaks, or not an order with why
READ = re.compile(
    r"^MESSAGE (\d+) READ: (?:(ORDER) - [^\n]*?\S[^\n]*?; BREAKS:[ \t]*\S|NOT AN ORDER - [ \t]*\S)",
    re.M,
)
#: the agent's answer to order n, with its evidence or reason
ANSWER = re.compile(r"^ORDER (\d+) (?:DONE|PUSHBACK):[ \t]*\S", re.M)


#: a session id as Claude Code sends it, safe as a file name
SESSION = re.compile(r"[\w-]+")


def session(payload: dict) -> str:
    """Return the payload's session id as sent.

    One that is missing or not a plain name raises, so the hook fails closed instead of filing the
    session under a name of its own.
    """
    sid = payload["session_id"]
    if not isinstance(sid, str) or not SESSION.fullmatch(sid):
        raise ValueError(sid)
    return sid


def _ledger(payload: dict, orders: Path) -> Path:
    return orders / f"{session(payload)}.jsonl"


def _entries(ledger: Path) -> list[dict]:
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line]


def record_message(payload: dict, orders: Path = ORDERS) -> int | None:
    """Record the operator's message as the session's next message and return its number.

    None for an event the app sends as a message (`<task-notification>`, `<ci-monitor-event>`),
    which no one sent.
    """
    said = payload.get("prompt")
    if not isinstance(said, str) or not said.strip() or said.lstrip().startswith("<"):
        return None
    ledger = _ledger(payload, orders)
    n = sum("message" in e for e in _entries(ledger)) + 1
    orders.mkdir(exist_ok=True)
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"n": n, "message": said}) + "\n")
    return n


def standing_orders(payload: dict, orders: Path = ORDERS) -> list[tuple[int, str]]:
    """Return the session's messages read as orders, each with its text.

    They are what a new message is checked against for a conflict.
    """
    entries = _entries(_ledger(payload, orders))
    given = {e["n"]: e["message"] for e in entries if "message" in e}
    return [(e["read"], given[e["read"]]) for e in entries if e.get("order") is True]


def open_messages(payload: dict, last: str, orders: Path = ORDERS) -> list[tuple[int, str, str]]:
    """Return the session's messages not yet read ("read") and orders not yet answered ("answer").

    They are taken after keeping the readings and answers `last` gives.
    """
    ledger = _ledger(payload, orders)
    entries = _entries(ledger)
    given = {e["n"]: e["message"] for e in entries if "message" in e}
    read = {e["read"]: e["order"] for e in entries if "read" in e}
    answered = {e["answered"] for e in entries if "answered" in e}
    new_read = {
        int(n): order == "ORDER" for n, order in READ.findall(last) if int(n) in given.keys() - read
    }
    read |= new_read
    new_answers = {int(n) for n in ANSWER.findall(last)} & {n for n, o in read.items() if o}
    new_answers -= answered
    if new_read or new_answers:
        with ledger.open("a", encoding="utf-8") as f:
            f.writelines(
                json.dumps({"read": n, "order": o}) + "\n" for n, o in sorted(new_read.items())
            )
            f.writelines(json.dumps({"answered": n}) + "\n" for n in sorted(new_answers))
    return [
        (n, text, "read" if n not in read else "answer")
        for n, text in sorted(given.items())
        if n not in read or (read[n] and n not in answered | new_answers)
    ]


#: the console's port, as launch.py reads it
CONSOLE_PORT = int(os.environ.get("ED_CONSOLE_PORT", "8000"))


def production_wrong(repo: Path = REPO, port: int = CONSOLE_PORT) -> str | None:
    """Return why production is not running main, or None when it is.

    The reasons are the checkout at `repo` beside its `origin/main`, or nothing listening on
    127.0.0.1 `port`.
    """
    head, main = (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", ref],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for ref in ("HEAD", "origin/main")
    )
    if head != main:
        return f"production's checkout is at {head}, main at {main}: deploy it (the deploy skill)."
    with socket.socket() as probe:
        probe.settimeout(2.0)
        if probe.connect_ex(("127.0.0.1", port)) != 0:
            return (
                f"nothing listens on 127.0.0.1:{port}: Ed Console is not running. Find why "
                "(its log, the machine's boot time), then start it (the deploy skill)."
            )
    return None


def decide(
    work_list: str,
    last: str,
    in_a_row: int = 1,
    open_orders: list[tuple[int, str, str]] = (),
    production: str | None = None,
) -> str | None:
    """Return why the stop is refused, or None when it may end.

    `in_a_row` is which refusal in a row this would be, and from BEDROCK_AT on the reason sends the
    agent to the cause, not back to the same attempt. An unread message or an unanswered order
    refuses the stop, whatever the SHAPE row says.
    """
    if open_orders:
        return (
            "The operator's messages are not all read and answered. Read each one and put your "
            "reading to him to correct: `MESSAGE n READ: ORDER - <what it orders>; BREAKS: "
            "<what it breaks or which earlier order it conflicts with, or nothing>`, or "
            "`MESSAGE n READ: NOT AN ORDER - <why>`. Once he tells you to do something, you do "
            "it; you do not choose: answer each order with `ORDER n DONE: <evidence>`, or "
            "`ORDER n PUSHBACK: <reason>` only when it is not allowed or not possible.\n"
            + "\n".join(
                f"{'MESSAGE' if need == 'read' else 'ORDER'} {n}: {text[:400]}"
                for n, text, need in open_orders
            )
        )
    if last.lstrip().startswith(WAITING):
        return None
    if production is not None:
        return "Production does not run main: " + production
    if not OPEN.search(work_list):
        return None
    why = (
        "SHAPE in ACTIVE_PROGRAM.md is IN PROGRESS: take its next step now (AGENTS.md Authority: "
        "work continues until SHAPE is finished; merges do not wait on the operator, and a pull "
        "request in CI merges by itself while the next step starts). Stop only for a stop the "
        "rules require (AGENTS.md Authority's stop list; CLAUDE.md items 3 and 5), saying why in "
        f"a message that begins `{WAITING}`."
    )
    if in_a_row < BEDROCK_AT:
        return why
    return (
        f"This is stop {in_a_row} refused in a row since the operator last wrote. "
        "If you are trying "
        "again what already failed, it is not working: do not repeat it. Go to bedrock: write down "
        "why it fails, down to the line of code or data, with "
        "evidence (AGENTS.md First gate 4); then take a different approach, the simplest one that "
        "fits Python's guidelines (PEP 20) and the shape, and keep going. " + why
    )


#: the refusal in a row from which the reason sends the agent to bedrock (AGENTS.md Authority)
BEDROCK_AT = 3
#: one file per session holding its refusals in a row (Claude Code's payload says only whether
#: this stop comes while it is continuing because a Stop hook refused one: `stop_hook_active`,
#: true until the operator next writes, the same run Claude Code's own cap of 8 counts)
COUNTS = Path(tempfile.gettempdir()) / "ed_keep_going"


def in_a_row(payload: dict, counts: Path = COUNTS) -> int:
    """Return which refusal in a row this stop would be.

    1 after a stop the hook did not refuse, else one more than the session's count in `counts`.
    The count is replaced whole, never half-written.
    """
    count = counts / session(payload)
    active = payload.get("stop_hook_active") is True
    previous = int(count.read_text()) if active and count.exists() else 0
    counts.mkdir(exist_ok=True)
    written = count.with_name(count.name + ".new")
    written.write_text(str(previous + 1))
    written.replace(count)
    return previous + 1


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        work_list = WORK_LIST.read_text(encoding="utf-8")
        said = payload.get("last_assistant_message")
        last = said if isinstance(said, str) else last_message(Path(payload["transcript_path"]))
        orders = open_messages(payload, last)
        wrong = production_wrong()
        why = decide(work_list, last, open_orders=orders, production=wrong)
        if why is not None:
            why = decide(work_list, last, in_a_row(payload), orders, wrong)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        subprocess.CalledProcessError,
    ) as e:
        sys.stderr.write(
            f"keep_going cannot judge the stop ({e!r}); keep working and fix the hook\n"
        )
        return 2
    if why is not None:
        print(json.dumps({"decision": "block", "reason": why}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
