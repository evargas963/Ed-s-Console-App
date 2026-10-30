"""tools/keep_going.py, the Stop hook (operator 2026-10-29: "you are allowed to continue until you
finish"): while the SHAPE row is IN PROGRESS a stop is refused unless the agent's last message
begins `WAITING ON OPERATOR:`. Run as the settings wire it, on a session transcript in Claude
Code's JSON-lines form."""

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


def test_the_settings_run_it_on_stop_and_it_answers_block_on_a_real_payload(tmp_path):
    """The command `.claude/settings.json` wires for Stop, run on a payload as Claude Code sends
    it, while this repository's SHAPE row is open: it refuses the stop with the reason."""
    settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    (command,) = [h["command"] for e in settings["hooks"]["Stop"] for h in e["hooks"]]
    assert command.endswith("tools/keep_going.py")
    assert keep_going.OPEN.search((REPO / "ACTIVE_PROGRAM.md").read_text(encoding="utf-8"))
    payload = {
        "session_id": "s",
        "stop_hook_active": False,
        "transcript_path": str(_transcript(tmp_path, "Here is where it stands.")),
    }
    run = subprocess.run(
        [sys.executable, str(REPO / "tools" / "keep_going.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    answer = json.loads(run.stdout)
    assert run.returncode == 0 and answer["decision"] == "block" and "SHAPE" in answer["reason"]


def test_a_payload_it_cannot_read_refuses_the_stop_with_the_reason():
    run = subprocess.run(
        [sys.executable, str(REPO / "tools" / "keep_going.py")],
        input="not json",
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert run.returncode == 2 and "cannot judge the stop" in run.stderr
