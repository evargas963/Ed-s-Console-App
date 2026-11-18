"""tools/keep_going.py, the Stop hook (AGENTS.md Authority).

A stop is refused while a message is unread or an order unanswered, and otherwise unless the
agent's final message begins `WAITING ON OPERATOR:` (production not on main says why). Run as the
settings wire it, on a session transcript in Claude Code's JSON-lines form.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from tools import keep_going

pytestmark = pytest.mark.rail

REPO = Path(__file__).resolve().parent.parent
#: why production does not run main, as production_wrong says it
DOWN = "nothing listens on 127.0.0.1:8000: Ed Console is not running."


def _transcript(tmp_path: Path, *said: str) -> Path:
    path = tmp_path / "session.jsonl"
    lines = [json.dumps({"type": "user", "message": {"role": "user", "content": "continue"}})]
    lines += [
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": s}]}})
        for s in said
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "production, last, stops",
    [
        (DOWN, "Step 1b is merged.", False),
        (
            DOWN,
            "WAITING ON OPERATOR: a change of a request rate needs his yes.",
            True,
        ),
        (DOWN, "  WAITING ON OPERATOR: the same, after leading space.", True),
        (DOWN, "Done. WAITING ON OPERATOR: not at the start, so not the way through.", False),
        (DOWN, "WAITING ON CI: #757, #759 and #760 run with Auto-fix on.", False),
        (DOWN, "Merged #758. WAITING ON CI: not at the start, so not the way through.", False),
        (DOWN, "Waiting on CI for #757.", False),
        # production on main: a report is no stop either (operator 2026-11-18: "fix it so you
        # won't stop"); only what he must decide ends the turn
        (None, "Merged #1128.", False),
        (None, "WAITING ON CI: #1162 runs with Auto-fix on.", False),
        (None, "", False),
        (None, "WAITING ON OPERATOR: the unidiff install needs his yes.", True),
    ],
)
def test_a_stop_is_refused_while_production_is_down_unless_only_the_operator_can_act(
    production, last, stops
):
    assert (keep_going.decide(last, production=production) is None) == stops


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _production(temp: Path, at_main: bool) -> Path:
    """Make a production checkout of the real hook and this repository's work list, committed.

    Its `origin/main` at HEAD; one commit past it when not `at_main`.
    """
    prod = temp / ("production" if at_main else "production-behind")
    if not prod.exists():
        (prod / "tools").mkdir(parents=True)
        shutil.copy(REPO / "tools" / "keep_going.py", prod / "tools")
        shutil.copy(REPO / "ACTIVE_PROGRAM.md", prod)
        _git(prod, "init", "-q")
        _git(prod, "add", "tools/keep_going.py", "ACTIVE_PROGRAM.md")
        _git(prod, "commit", "-q", "-m", "main")
        _git(prod, "update-ref", "refs/remotes/origin/main", "HEAD")
        if not at_main:
            _git(prod, "commit", "-q", "--allow-empty", "-m", "beside main")
    return prod


def _run(
    payload, temp: Path, *, at_main: bool = True, listening: bool = True
) -> subprocess.CompletedProcess:
    """Run the script the settings wire for Stop, on `payload` as Claude Code sends it.

    Run from a production checkout in `temp` with the console's port pointed at a free port of
    the test's own (listening unless told not to), and `temp` as its temp folder, so the counts
    and orders it keeps stay in the test's own folder.
    """
    prod = _production(temp, at_main)
    with socket.socket() as console:
        console.bind(("127.0.0.1", 0))
        if listening:
            console.listen()
        port = str(console.getsockname()[1])
        return subprocess.run(
            [sys.executable, str(prod / "tools" / "keep_going.py")],
            input=payload if isinstance(payload, str) else json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=prod,
            env={
                **os.environ,
                "TEMP": str(temp),
                "TMP": str(temp),
                "TMPDIR": str(temp),
                "ED_CONSOLE_PORT": port,
            },
        )


@pytest.mark.parametrize(
    "at_main, listening, why",
    [
        (False, True, "production's checkout is at"),
        (True, False, "Ed Console is not running"),
    ],
)
def test_a_stop_is_refused_while_production_does_not_run_main(at_main, listening, why, tmp_path):
    """Operator 2026-11-07: Windows Update restarted the machine and Ed Console stayed down.

    It stayed down 25 hours with no one told. A stop is refused while production's checkout is not
    at main or nothing listens on its port; WAITING ON OPERATOR passes (he may stop it).
    """
    said = {"session_id": "p", "last_assistant_message": "Merged #1128."}
    run = _run(said, tmp_path, at_main=at_main, listening=listening)
    assert run.returncode == 0 and why in json.loads(run.stdout)["reason"], run.stderr
    waiting = {**said, "last_assistant_message": "WAITING ON OPERATOR: he stopped it."}
    assert _run(waiting, tmp_path, at_main=at_main, listening=listening).stdout == ""


def test_the_settings_run_it_on_stop_and_it_answers_by_this_repositorys_shape_row(tmp_path):
    """The command `.claude/settings.json` wires for Stop, run on a payload in Claude Code's form.

    With every message answered and production running main, a report refuses the stop (keep
    working) and WAITING ON OPERATOR lets it end; with nothing listening on the console's port, it
    refuses with the reason.
    """
    settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    (command,) = [h["command"] for e in settings["hooks"]["Stop"] for h in e["hooks"]]
    assert command.endswith("tools/keep_going.py")
    payload = {
        "session_id": "s",
        "stop_hook_active": False,
        "transcript_path": str(_transcript(tmp_path, "Here is where it stands.")),
    }
    run = _run(payload, tmp_path)
    assert run.returncode == 0
    assert "Keep working" in json.loads(run.stdout)["reason"]
    own = tmp_path / "waiting"
    own.mkdir()
    waiting = {
        **payload,
        "transcript_path": str(_transcript(own, "WAITING ON OPERATOR: his yes to a rate.")),
    }
    assert _run(waiting, tmp_path).stdout == ""
    answer = json.loads(_run(payload, tmp_path, listening=False).stdout)
    assert answer["decision"] == "block" and "Production" in answer["reason"]


def _entries(tmp_path: Path, *entries) -> Path:
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(e if isinstance(e, str) else json.dumps(e) for e in entries), "utf-8")
    return path


def _said(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


TOOL_ONLY = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}


def test_the_final_message_is_the_last_assistant_entry_and_a_bad_line_never_decides(tmp_path):
    """A turn that ends on a tool call has no final text.

    So an earlier WAITING message does not stand in for it; a line that is not a JSON object
    (damaged, or `null`) is skipped, so one bad line never refuses every later stop; the
    payload's own final message wins when it is sent.
    """
    waiting = _said("WAITING ON OPERATOR: his yes to a change of a request rate.")
    assert keep_going.last_message(_entries(tmp_path, waiting, TOOL_ONLY)) == ""
    damaged = '{"type": "assistant", "message": {"cont'
    assert keep_going.last_message(_entries(tmp_path, damaged, "null", "[]", waiting)).startswith(
        "WAITING ON OPERATOR:"
    )
    assert keep_going.last_message(_entries(tmp_path, waiting, damaged)).startswith("WAITING")
    run = _run(
        {
            "session_id": "s",
            "transcript_path": str(_entries(tmp_path, waiting)),
            "last_assistant_message": "Step 1b is merged.",
        },
        tmp_path,
        listening=False,
    )
    assert run.returncode == 0
    # the payload's own message, not the transcript's WAITING one, is judged: production is down
    assert json.loads(run.stdout)["decision"] == "block"


def test_a_payload_it_cannot_read_refuses_the_stop_with_the_reason(tmp_path):
    """Not JSON, JSON that is not an object, and a payload with no final message all refuse."""
    run = _run("not json", tmp_path)
    assert run.returncode == 2 and "cannot judge the stop" in run.stderr
    for payload in ("null", {"session_id": "s"}):
        run = _run(payload, tmp_path)
        assert run.returncode == 2 and "cannot judge the stop" in run.stderr, payload
    # one it can read, with every order answered, production running main and the operator to
    # decide, ends
    said = "WAITING ON OPERATOR: his yes to a rate."
    run = _run({"session_id": "s", "last_assistant_message": said}, tmp_path)
    assert (run.returncode, run.stdout) == (0, "")


def test_every_message_is_read_and_every_order_answered_before_the_turn_ends(tmp_path):
    """A stop is refused until each message is read and each order answered.

    Operator 2026-11-07: "once i tell you do something, you must do it ... you must enforce
    this rule"; 2026-11-08: "you must ask if it's an order and if it is an order then you must
    immediately tell me if it breaks anything". A stop is refused until each message is read, and
    each read as an order is answered.
    """
    s = {"session_id": "orders-1"}
    first = keep_going.record_message({**s, "prompt": "fix all 13 now"}, tmp_path)
    second = keep_going.record_message({**s, "prompt": "what is a dict?"}, tmp_path)
    assert (first, second) == (1, 2)
    # an event the app sends as a message is no one's message
    for event in ("<task-notification>done</task-notification>", "<ci-monitor-event>x", "  "):
        assert keep_going.record_message({**s, "prompt": event}, tmp_path) is None
    assert keep_going.open_messages(s, "Merged #775.", tmp_path) == [
        (1, "fix all 13 now", "read"),
        (2, "what is a dict?", "read"),
    ]
    why = keep_going.decide("Merged #1128.", open_orders=[(2, "a dict?", "read")])
    assert why is not None and "MESSAGE 2: a dict?" in why and "BREAKS:" in why
    # a reading with nothing after it, mid-line, an order with no BREAKS, or for a message never
    # sent reads nothing; nor does an answer to a message not read as an order
    for empty in (
        "MESSAGE 1 READ: ORDER - fix them",
        "MESSAGE 1 READ: ORDER - fix them; BREAKS:",
        "Note: MESSAGE 1 READ: NOT AN ORDER - a question",
        "MESSAGE 9 READ: NOT AN ORDER - a question",
        "ORDER 1 DONE: #776",
    ):
        assert [n for n, *_ in keep_going.open_messages(s, empty, tmp_path)] == [1, 2]
    left = keep_going.open_messages(
        s,
        "MESSAGE 1 READ: ORDER - fix the 13 items; BREAKS: nothing\n"
        "MESSAGE 2 READ: NOT AN ORDER - a question about dicts",
        tmp_path,
    )
    assert left == [(1, "fix all 13 now", "answer")]
    assert keep_going.standing_orders(s, tmp_path) == [(1, "fix all 13 now")]
    why = keep_going.decide("", open_orders=left)
    assert why is not None and "ORDER 1: fix all 13 now" in why
    # a reading and an answer are kept: a later message need not repeat them
    assert keep_going.open_messages(s, "", tmp_path) == left
    assert keep_going.open_messages(s, "ORDER 1 DONE: #776, #777 merged", tmp_path) == []
    assert keep_going.open_messages(s, "", tmp_path) == []
    assert keep_going.decide("WAITING ON OPERATOR: his yes.", open_orders=[]) is None
    # another session's messages are its own
    assert keep_going.open_messages({"session_id": "orders-2"}, "", tmp_path) == []


@pytest.mark.parametrize(
    "payload", [{}, {"session_id": ""}, {"session_id": "../x"}, {"session_id": 5}]
)
def test_a_session_id_missing_or_not_a_plain_name_fails_closed(payload, tmp_path):
    """No session is filed under a name of the hook's own: the stop is judged unreadable."""
    with pytest.raises((KeyError, ValueError)):
        keep_going.record_message({**payload, "prompt": "go"}, tmp_path)
    with pytest.raises((KeyError, ValueError)):
        keep_going.open_messages(payload, "", tmp_path)


def test_waiting_on_the_operator_does_not_pass_an_unanswered_order():
    why = keep_going.decide("WAITING ON OPERATOR: his yes.", open_orders=[(1, "x", "answer")])
    assert why is not None and why.startswith("The operator's messages are not all read")


def test_a_subagents_message_is_not_the_agents_final_message(tmp_path):
    waiting = _said("WAITING ON OPERATOR: his yes to a change of a request rate.")
    side = {**_said("Verdict: FAIL."), "isSidechain": True}
    assert keep_going.last_message(_entries(tmp_path, waiting, side)).startswith("WAITING")
