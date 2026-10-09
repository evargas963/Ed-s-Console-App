"""tools/operator_yes_guard.py (CLAUDE.md rule 6): starting or stopping the daemon or console, a
merge and a push to main are put to the operator (the hook answers "ask"); every other action,
a change to a test included, passes. Judged on real payloads and through the hook chain the
settings run."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import operator_yes_guard as guard  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EXISTING = "tests/test_check_end_to_end_v1.py"     # a test that is on origin/main


def _edit(path: str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": path, "old_string": "a", "new_string": "b"}}


def _shell(cmd: str, tool: str = "Bash") -> dict:
    return {"tool_name": tool, "tool_input": {"command": cmd}, "cwd": str(REPO)}


def _chain(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "tools/hook_chain.py", "tools/operator_yes_guard.py"], cwd=REPO,
                          input=json.dumps(payload), capture_output=True, text=True)


@pytest.mark.parametrize("cmd, what", [
    ("Stop-Process -Id 123 -Force  # streaming.capture", "daemon or the console"),
    ("Start-Process -FilePath C:\\x\\start_capture_daemon.bat", "daemon or the console"),
    ("cmd /c start_ed_console.bat", "daemon or the console"),
    (".venv\\Scripts\\python.exe launch.py", "daemon or the console"),
    ("gh pr merge 445 --merge", "merges pull request 445"),
    ("gh api -X PUT repos/o/r/pulls/445/merge", "merges pull request 445"),
    ("git push origin HEAD:main", "pushes to main"),
    ("git push origin main", "pushes to main"),
])
def test_production_actions_are_put_to_the_operator(cmd, what):
    assert any(what in r for r in guard.reasons(_shell(cmd)))


def test_the_test_changed_below_is_on_main():
    assert subprocess.run(["git", "cat-file", "-e", f"origin/main:{EXISTING}"], cwd=REPO).returncode == 0


@pytest.mark.parametrize("payload", [
    _edit(str(REPO / EXISTING)),
    {"tool_name": "Write", "tool_input": {"file_path": str(REPO / EXISTING), "content": "x"}},
    _shell(f"rm {EXISTING}"),
    _shell(f"git rm -q {EXISTING}"),
    _shell(f"echo x > {EXISTING}"),
    _shell(f"Remove-Item {EXISTING}", "PowerShell"),
    _edit(str(REPO / "server.py")),
    _shell(f"python -m pytest {EXISTING} -q"),
    _shell("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*streaming.capture*' }",
           "PowerShell"),
    _shell("gh pr view 445 --json state"),
    _shell("git push -q -u origin fix/some-branch"),
    _shell("git add launch.py tests/test_launch_v1.py"),
    _shell("python -m ruff check launch.py"),
])
def test_everything_else_passes_a_change_to_a_test_on_main_included(payload):
    assert guard.reasons(payload) == []


def test_the_hook_chain_answers_ask_with_the_reason_and_passes_ordinary_work():
    """The real wiring: .claude/settings.json runs hook_chain with this guard; an action that
    needs a yes gets Claude Code's "ask" answer on stdout, other actions nothing."""
    settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert all("tools/operator_yes_guard.py" in c for c in commands)
    r = _chain(_shell("gh pr merge 99999"))
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert r.returncode == 0 and out["permissionDecision"] == "ask"
    assert "merges pull request 99999" in out["permissionDecisionReason"]
    quiet = _chain(_edit(str(REPO / EXISTING)))
    assert quiet.returncode == 0 and quiet.stdout == ""
