"""tools/keep_going.py, the Stop hook (AGENTS.md Authority): while the SHAPE row is IN PROGRESS a
stop is refused unless the agent's final message begins `WAITING ON OPERATOR:`. Run as the settings
wire it, on a session transcript in Claude Code's JSON-lines form."""

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

REPO = Path(__file__).resolve().parent.parent
OPEN_ROW = "| SHAPE | IN PROGRESS | **One program, five parts** ... |\n"
DONE_ROW = "| SHAPE | DONE | **One program, five parts** ... |\n"


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
    "row, last, stops",
    [
        (OPEN_ROW, "Step 1b is merged.", False),
        (
            OPEN_ROW,
            "WAITING ON OPERATOR: a change of a request rate needs his yes.",
            True,
        ),
        (OPEN_ROW, "  WAITING ON OPERATOR: the same, after leading space.", True),
        (OPEN_ROW, "Done. WAITING ON OPERATOR: not at the start, so not the way through.", False),
        (OPEN_ROW, "WAITING ON CI: #757, #759 and #760 run with Auto-fix on.", False),
        (OPEN_ROW, "Merged #758. WAITING ON CI: not at the start, so not the way through.", False),
        (OPEN_ROW, "Waiting on CI for #757.", False),
        (DONE_ROW, "SHAPE is finished.", True),
    ],
)
def test_a_stop_is_refused_while_shape_is_open_unless_only_the_operator_can_act(row, last, stops):
    assert (keep_going.decide(row, last) is None) == stops


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _production(temp: Path, at_main: bool) -> Path:
    """A production checkout of the real hook and this repository's work list, committed, its
    `origin/main` at HEAD; one commit past it when not `at_main`."""
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
    """The script the settings wire for Stop, on `payload` as Claude Code sends it, run from a
    production checkout in `temp` with the console's port pointed at a free port of the test's
    own (listening unless told not to), and `temp` as its temp folder, so the counts and orders it
    keeps stay in the test's own folder."""
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
    """Operator 2026-11-07: Windows Update restarted the machine and Ed Console stayed down 25
    hours with no one told. A stop is refused, whatever SHAPE says, while production's checkout is
    not at main or nothing listens on its port; WAITING ON OPERATOR passes (he may stop it)."""
    said = {"session_id": "p", "last_assistant_message": "SHAPE is finished."}
    run = _run(said, tmp_path, at_main=at_main, listening=listening)
    assert run.returncode == 0 and why in json.loads(run.stdout)["reason"], run.stderr
    waiting = {**said, "last_assistant_message": "WAITING ON OPERATOR: he stopped it."}
    assert _run(waiting, tmp_path, at_main=at_main, listening=listening).stdout == ""


def test_the_settings_run_it_on_stop_and_it_answers_by_this_repositorys_shape_row(tmp_path):
    """The command `.claude/settings.json` wires for Stop, run on a payload in Claude Code's form:
    it refuses the stop with the reason while this repository's SHAPE row is open, and lets it end
    once it is not."""
    settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    (command,) = [h["command"] for e in settings["hooks"]["Stop"] for h in e["hooks"]]
    assert command.endswith("tools/keep_going.py")
    run = _run(
        {
            "session_id": "s",
            "stop_hook_active": False,
            "transcript_path": str(_transcript(tmp_path, "Here is where it stands.")),
        },
        tmp_path,
    )
    open_now = keep_going.OPEN.search((REPO / "ACTIVE_PROGRAM.md").read_text(encoding="utf-8"))
    assert run.returncode == 0
    if open_now:
        answer = json.loads(run.stdout)
        assert answer["decision"] == "block" and "SHAPE" in answer["reason"]
    else:
        assert run.stdout == ""


def _entries(tmp_path: Path, *entries) -> Path:
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(e if isinstance(e, str) else json.dumps(e) for e in entries), "utf-8")
    return path


def _said(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


TOOL_ONLY = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}


def test_the_final_message_is_the_last_assistant_entry_and_a_bad_line_never_decides(tmp_path):
    """A turn that ends on a tool call has no final text, so an earlier WAITING message does not
    stand in for it; a line that is not a JSON object (damaged, or `null`) is skipped, so one bad
    line never refuses every later stop; the payload's own final message wins when it is sent."""
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
    )
    assert run.returncode == 0
    if keep_going.OPEN.search((REPO / "ACTIVE_PROGRAM.md").read_text(encoding="utf-8")):
        assert json.loads(run.stdout)["decision"] == "block"


def test_a_payload_it_cannot_read_refuses_the_stop_with_the_reason(tmp_path):
    """Not JSON refuses always; a payload without a transcript refuses while SHAPE is open (the row
    is read first, so once SHAPE is finished it holds no session)."""
    run = _run("not json", tmp_path)
    assert run.returncode == 2 and "cannot judge the stop" in run.stderr
    open_now = keep_going.OPEN.search((REPO / "ACTIVE_PROGRAM.md").read_text(encoding="utf-8"))
    for payload in ("null", {"session_id": "s"}):
        run = _run(payload, tmp_path)
        if open_now:
            assert run.returncode == 2 and "cannot judge the stop" in run.stderr, payload
        else:
            assert (run.returncode, run.stdout) == (0, ""), payload


def test_from_the_third_refusal_in_a_row_the_reason_sends_the_agent_to_bedrock(tmp_path):
    """Refused stops in a row mean the work may not be working (AGENTS.md Authority); from the third
    the reason says so and sends the agent to the cause and a different approach, still working. A
    stop the hook did not refuse (`stop_hook_active` false) starts the count again."""
    counts = [
        keep_going.in_a_row({"session_id": "s-1", "stop_hook_active": active}, tmp_path)
        for active in (False, True, True, True, False)
    ]
    assert counts == [1, 2, 3, 4, 1]
    second = keep_going.decide(OPEN_ROW, "Step 1b is merged.", 2)
    third = keep_going.decide(OPEN_ROW, "Step 1b is merged.", 3)
    assert "bedrock" not in second and second in third
    assert third.startswith("This is stop 3 refused in a row since the operator last wrote.")
    assert "Go to bedrock" in third
    assert keep_going.decide(OPEN_ROW, "WAITING ON OPERATOR: his yes.", 3) is None
    rule = " ".join((REPO / "AGENTS.md").read_text(encoding="utf-8").split())
    said = "If you are trying again what already failed, it is not working"
    assert said in third and f'"{said}"' in rule and "since the operator last wrote" in rule


def test_the_hook_as_wired_counts_its_refusals_and_an_allowed_stop_writes_no_count(tmp_path):
    """Run as the settings wire it: three refused stops of one session reach the bedrock reason on
    the third; a stop marked WAITING ON OPERATOR is let through and leaves no count."""
    if not keep_going.OPEN.search((REPO / "ACTIVE_PROGRAM.md").read_text(encoding="utf-8")):
        pytest.skip("SHAPE is finished: the hook refuses no stop")
    count = tmp_path / keep_going.COUNTS.name / "s-1"
    reasons = [
        json.loads(
            _run(
                {
                    "session_id": "s-1",
                    "stop_hook_active": active,
                    "last_assistant_message": "Step 1b is merged.",
                },
                tmp_path,
            ).stdout
        )["reason"]
        for active in (False, True, True)
    ]
    assert "bedrock" not in reasons[1] and reasons[2].startswith("This is stop 3 refused")
    count.unlink()
    run = _run(
        {
            "session_id": "s-1",
            "stop_hook_active": True,
            "last_assistant_message": "WAITING ON OPERATOR: his yes.",
        },
        tmp_path,
    )
    assert (run.returncode, run.stdout, count.exists()) == (0, "", False)


def test_every_order_holds_the_turn_until_it_is_answered(tmp_path):
    """Operator 2026-11-07: "once i tell you do something, you must do it ... you must enforce
    this rule". Each message is an order; a stop is refused until each is answered, SHAPE or not."""
    s = {"session_id": "orders-1"}
    first = keep_going.record_order({**s, "prompt": "fix all 13 now"}, tmp_path)
    second = keep_going.record_order({**s, "prompt": "I NEED A NEW CENSUS TOTAL"}, tmp_path)
    assert (first, second) == (1, 2)
    # an event the app sends as a message is no one's order
    for event in ("<task-notification>done</task-notification>", "<ci-monitor-event>x", "  "):
        assert keep_going.record_order({**s, "prompt": event}, tmp_path) is None
    assert keep_going.unanswered(s, "Merged #775.", tmp_path) == [
        (1, "fix all 13 now"),
        (2, "I NEED A NEW CENSUS TOTAL"),
    ]
    why = keep_going.decide(DONE_ROW, "SHAPE is finished.", open_orders=[(2, "census total")])
    assert why is not None and "ORDER 2: census total" in why
    # an answer with nothing after it, mid-line, or for an order never given answers nothing
    for empty in ("ORDER 1 DONE:", "Note: ORDER 1 DONE: #776", "ORDER 9 DONE: #776"):
        assert [n for n, _ in keep_going.unanswered(s, empty, tmp_path)] == [1, 2]
    left = keep_going.unanswered(s, "ORDER 1 DONE: #776, #777 merged", tmp_path)
    assert left == [(2, "I NEED A NEW CENSUS TOTAL")]
    # an answer is kept: a later message need not repeat it
    assert keep_going.unanswered(s, "", tmp_path) == left
    assert keep_going.unanswered(s, "ORDER 2 PUSHBACK: needs his GitHub setting", tmp_path) == []
    assert keep_going.decide(DONE_ROW, "", open_orders=[]) is None
    # another session's orders are its own
    assert keep_going.unanswered({"session_id": "orders-2"}, "", tmp_path) == []


@pytest.mark.parametrize(
    "payload", [{}, {"session_id": ""}, {"session_id": "../x"}, {"session_id": 5}]
)
def test_a_session_id_missing_or_not_a_plain_name_fails_closed(payload, tmp_path):
    """No session is filed under a name of the hook's own: the stop is judged unreadable."""
    with pytest.raises((KeyError, ValueError)):
        keep_going.record_order({**payload, "prompt": "go"}, tmp_path)
    with pytest.raises((KeyError, ValueError)):
        keep_going.in_a_row(payload, tmp_path)


def test_waiting_on_the_operator_does_not_pass_an_unanswered_order():
    why = keep_going.decide(OPEN_ROW, "WAITING ON OPERATOR: his yes.", open_orders=[(1, "x")])
    assert why is not None and why.startswith("The operator's orders are not answered")


def test_a_subagents_message_is_not_the_agents_final_message(tmp_path):
    waiting = _said("WAITING ON OPERATOR: his yes to a change of a request rate.")
    side = {**_said("Verdict: FAIL."), "isSidechain": True}
    assert keep_going.last_message(_entries(tmp_path, waiting, side)).startswith("WAITING")
