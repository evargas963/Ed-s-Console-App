"""tools/operator_yes_guard.py (CLAUDE.md rules 5 and 6): changing a test that exists on main,
starting or stopping the daemon or console, a merge, a push to main and a write to a database under
data/ are put to the operator (the hook answers "ask"); ordinary work and read-only database reads pass. Judged on real payloads, against this
repository's origin/main, and through the hook chain the settings run."""
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
NEW = "tests/test_never_on_main_zz_v1.py"


def _edit(path: str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": path, "old_string": "a", "new_string": "b"}}


def _shell(cmd: str, tool: str = "Bash") -> dict:
    return {"tool_name": tool, "tool_input": {"command": cmd}, "cwd": str(REPO)}


def _chain(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "tools/hook_chain.py", "tools/operator_yes_guard.py"], cwd=REPO,
                          input=json.dumps(payload), capture_output=True, text=True)


def test_the_existing_test_is_on_main_and_the_new_one_is_not():
    on_main = lambda p: subprocess.run(["git", "cat-file", "-e", f"origin/main:{p}"], cwd=REPO).returncode == 0
    assert on_main(EXISTING) and not on_main(NEW)


@pytest.mark.parametrize("payload", [
    _edit(str(REPO / EXISTING)),
    _edit(EXISTING),
    {"tool_name": "Write", "tool_input": {"file_path": str(REPO / EXISTING), "content": "x"}},
    _shell(f"rm {EXISTING}"),
    _shell(f"git rm -q {EXISTING}"),
    _shell(f"sed -i 's/a/b/' {EXISTING}"),
    _shell(f"echo x > {EXISTING}"),
    _shell(f"Remove-Item {EXISTING}", "PowerShell"),
])
def test_changing_an_existing_test_is_put_to_the_operator(payload):
    assert any(EXISTING in r for r in guard.reasons(payload))


@pytest.mark.parametrize("cmd, what", [
    ("Stop-Process -Id 123 -Force  # streaming.capture", "daemon or the console"),
    ("Start-Process -FilePath C:\\x\\start_capture_daemon.bat", "daemon or the console"),
    ("cmd /c start_ed_console.bat", "daemon or the console"),
    ("gh pr merge 445 --merge", "merges pull request 445"),
    ("gh api -X PUT repos/o/r/pulls/445/merge", "merges pull request 445"),
    ("git push origin HEAD:main", "pushes to main"),
    ("git push origin main", "pushes to main"),
])
def test_production_actions_are_put_to_the_operator(cmd, what):
    assert any(what in r for r in guard.reasons(_shell(cmd)))


@pytest.mark.parametrize("payload", [
    _edit(NEW),
    _edit(str(REPO / "server.py")),
    _shell(f"python -m pytest {EXISTING} -q"),
    _shell(f"git diff origin/main -- {EXISTING}"),
    _shell("sed -n 1,20p " + EXISTING),
    _shell("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*streaming.capture*' }",
           "PowerShell"),
    _shell("gh pr view 445 --json state"),
    _shell("git push -q -u origin fix/some-branch"),
])
def test_ordinary_work_passes(payload):
    assert guard.reasons(payload) == []


@pytest.mark.parametrize("payload, db", [
    (_shell("python -c \"import sqlite3; c = sqlite3.connect('data/ed_console.db'); "
            "c.execute('DELETE FROM price_bars_1m WHERE source LIKE \\'synthetic%\\''); c.commit()\""),
     "data/ed_console.db"),
    (_shell("sqlite3 data/stream_capture.db \"VACUUM\""), "data/stream_capture.db"),
    (_shell(".venv/Scripts/python.exe - <<'EOF'\nimport sqlite3\n"
            "sqlite3.connect(r'..\\EdWebConsole\\data\\ed_console.db').execute('DROP TABLE model_accuracy')\nEOF"),
     "data\\ed_console.db"),
    (_shell("& .venv\\Scripts\\python.exe tools\\some_backfill.py --db data\\ed_console.db", "PowerShell"),
     "data\\ed_console.db"),
    ({"tool_name": "Write", "tool_input": {"file_path": "data/ed_console.db", "content": ""}}, "data/ed_console.db"),
])
def test_a_write_to_a_database_under_data_is_put_to_the_operator(payload, db):
    assert any(f"{db}, a database under data/" in r for r in guard.reasons(payload)), guard.reasons(payload)


@pytest.mark.parametrize("cmd, tool, db", [
    ("cp /tmp/other.db data/ed_console.db", "Bash", "data/ed_console.db"),
    ("Copy-Item C:\\tmp\\x.db data\\ed_console.db -Force", "PowerShell", "data\\ed_console.db"),
    ("cp /tmp/other.db-wal data/stream_capture.db-wal", "Bash", "data/stream_capture.db-wal"),
])
def test_a_copy_over_a_database_under_data_is_put_to_the_operator(cmd, tool, db):
    """A copy replaces the whole record without opening it (re-review 2026-10-05: these passed silently)."""
    assert f"writes {db}, a database under data/ (Records stand)" in guard.reasons(_shell(cmd, tool))


@pytest.mark.parametrize("cmd, tool", [
    ("cp data/ed_console.db /tmp/ed_console_copy.db", "Bash"),
    ("Copy-Item data\\stream_capture.db C:\\tmp\\copy.db", "PowerShell"),
])
def test_copying_a_database_out_of_data_passes(cmd, tool):
    assert guard.reasons(_shell(cmd, tool)) == []


@pytest.mark.parametrize("cmd", [
    ".venv/Scripts/python.exe -c \"import sqlite3; c = sqlite3.connect('file:data/ed_console.db?mode=ro', uri=True); "
    "print(c.execute('SELECT COUNT(*) FROM level_crosses').fetchone())\"",
    "sqlite3 -readonly data/stream_capture.db \"SELECT COUNT(*) FROM stream_bars_raw\"",
    "ls -la data/ed_console.db data/stream_capture.db",
    "python -m pytest tests/test_chain_history_v1.py -q",
])
def test_reading_a_database_and_ordinary_work_pass(cmd):
    assert guard.reasons(_shell(cmd)) == []


def test_the_hook_chain_answers_ask_with_the_reason_and_passes_ordinary_work():
    """The real wiring: .claude/settings.json and .cursor/hooks.json run hook_chain with this guard;
    an action that needs a yes gets Claude Code's "ask" answer on stdout, other actions nothing."""
    settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert all("tools/operator_yes_guard.py" in c for c in commands)
    r = _chain(_shell("gh pr merge 99999"))
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert r.returncode == 0 and out["permissionDecision"] == "ask"
    assert "merges pull request 99999" in out["permissionDecisionReason"]
    quiet = _chain(_shell("gh pr view 1"))
    assert quiet.returncode == 0 and quiet.stdout == ""
