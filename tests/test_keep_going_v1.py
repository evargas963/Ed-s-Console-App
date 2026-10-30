"""tools/keep_going.py, the Stop hook (AGENTS.md Authority): while the SHAPE row is IN PROGRESS a
stop is refused unless the agent's final message begins `WAITING ON OPERATOR:`. Run as the settings
wire it, on a session transcript in Claude Code's JSON-lines form."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import keep_going  # noqa: E402

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
            "WAITING ON OPERATOR: a console restart during regular hours needs his yes.",
            True,
        ),
        (OPEN_ROW, "  WAITING ON OPERATOR: the same, after leading space.", True),
        (OPEN_ROW, "Done. WAITING ON OPERATOR: not at the start, so not the way through.", False),
        (DONE_ROW, "SHAPE is finished.", True),
    ],
)
def test_a_stop_is_refused_while_shape_is_open_unless_only_the_operator_can_act(row, last, stops):
    assert (keep_going.decide(row, last) is None) == stops


def _run(payload) -> subprocess.CompletedProcess:
    """The script the settings wire for Stop, on `payload` as Claude Code sends it."""
    return subprocess.run(
        [sys.executable, str(REPO / "tools" / "keep_going.py")],
        input=payload if isinstance(payload, str) else json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=REPO,
    )


def test_the_settings_run_it_on_stop_and_it_answers_by_this_repositorys_shape_row(tmp_path):
    """The command `.claude/settings.json` wires for Stop, run on a real payload: it refuses the
    stop with the reason while this repository's SHAPE row is open, and lets it end once it is not."""
    settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    (command,) = [h["command"] for e in settings["hooks"]["Stop"] for h in e["hooks"]]
    assert command.endswith("tools/keep_going.py")
    run = _run(
        {
            "session_id": "s",
            "stop_hook_active": False,
            "transcript_path": str(_transcript(tmp_path, "Here is where it stands.")),
        }
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
    waiting = _said("WAITING ON OPERATOR: his yes to a console restart in regular hours.")
    assert keep_going.last_message(_entries(tmp_path, waiting, TOOL_ONLY)) == ""
    damaged = '{"type": "assistant", "message": {"cont'
    assert keep_going.last_message(_entries(tmp_path, damaged, "null", "[]", waiting)).startswith(
        "WAITING ON OPERATOR:"
    )
    assert keep_going.last_message(_entries(tmp_path, waiting, damaged)).startswith("WAITING")
    run = _run(
        {
            "transcript_path": str(_entries(tmp_path, waiting)),
            "last_assistant_message": "Step 1b is merged.",
        }
    )
    assert run.returncode == 0
    if keep_going.OPEN.search((REPO / "ACTIVE_PROGRAM.md").read_text(encoding="utf-8")):
        assert json.loads(run.stdout)["decision"] == "block"


def test_a_payload_it_cannot_read_refuses_the_stop_with_the_reason():
    for payload in ("not json", "null", {"session_id": "s"}):
        run = _run(payload)
        assert run.returncode == 2 and "cannot judge the stop" in run.stderr, payload
