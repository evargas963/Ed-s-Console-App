"""tools/wiring_rules.py: the operator's three rules reach the agent on every message he sends, run
as `.claude/settings.json` wires it."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_every_message_carries_the_three_rules_and_the_three_questions():
    settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    wired = [h["command"] for e in settings["hooks"]["UserPromptSubmit"] for h in e["hooks"]]
    assert wired == [".venv/Scripts/python.exe tools/wiring_rules.py"]
    done = subprocess.run(
        [sys.executable, "tools/wiring_rules.py"],
        input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "go"}),
        capture_output=True,
        text=True,
        cwd=REPO,
        check=True,
    )
    out = json.loads(done.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "UserPromptSubmit"
    said = out["additionalContext"]
    assert "simple wiring job" in said
    # all code, and every answer, proposal and change: never a list of folders or only edits
    assert "all code in the repository and to every answer, proposal and change" in said
    assert "app/" not in said and "product" not in said and "edit" not in said
    assert "as Schwab sends it" in said
    assert "what a bank would do" in said
    assert "Which Schwab field, or which registered derived value?" in said
    assert "What is the simplest direct wire?" in said
    assert "What would a bank do?" in said
    # operator 2026-11-05: "everything we do is repo wide"; "always end to end repairs"
    assert "Everything is repo wide" in said and "every ticker" in said
    assert "Every repair is end to end" in said and "never a patch" in said
    assert "Is it repo wide? Is every link repaired at its source?" in said
