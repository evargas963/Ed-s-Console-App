"""tools/operator_yes_guard.py (CLAUDE.md rules 5 and 6): an existing test, a restart, a merge and
a push to main need the operator's yes, a line dated today in `.claude/operator_yes.txt`; the
agent cannot write that file. Judged on real payloads, against this repository's origin/main."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import operator_yes_guard as guard  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 4)
EXISTING = "tests/test_check_end_to_end_v1.py"     # a test that is on origin/main
NEW = "tests/test_never_on_main_zz_v1.py"


def _edit(path: str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": path, "old_string": "a", "new_string": "b"}}


def _shell(cmd: str, tool: str = "Bash") -> dict:
    return {"tool_name": tool, "tool_input": {"command": cmd}, "cwd": str(REPO)}


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
def test_an_existing_test_is_not_changed_without_the_operators_yes(payload):
    assert any(EXISTING in v for v in guard.judge(payload, TODAY, ""))


def test_the_operators_yes_today_unlocks_that_test_and_only_that_test():
    yes = f"{TODAY.isoformat()} test {EXISTING}\n"
    assert guard.judge(_edit(EXISTING), TODAY, yes) == []
    other = "tests/test_data_path_rules_v1.py"
    assert guard.judge(_edit(other), TODAY, yes) != []


def test_a_yes_from_another_day_does_not_count():
    assert guard.judge(_edit(EXISTING), TODAY, f"2026-10-03 test {EXISTING}\n") != []


@pytest.mark.parametrize("payload", [
    _edit(NEW),
    _shell(f"python -m pytest {EXISTING} -q"),
    _shell(f"git diff origin/main -- {EXISTING}"),
    _shell("sed -n 1,20p " + EXISTING),
    _shell("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*streaming.capture*' }",
           "PowerShell"),
    _shell("gh pr view 445 --json state"),
    _shell("git push -q -u origin fix/some-branch"),
])
def test_ordinary_work_passes(payload):
    assert guard.judge(payload, TODAY, "") == []


@pytest.mark.parametrize("payload", [
    _edit(str(REPO / ".claude" / "operator_yes.txt")),
    _shell("echo 2026-10-04 restart >> .claude/operator_yes.txt"),
    _shell("cat .claude/operator_yes.txt"),
])
def test_the_agent_cannot_write_or_read_the_yes_file(payload):
    assert any("operator" in v for v in guard.judge(payload, TODAY, f"{TODAY.isoformat()} restart\n"))


@pytest.mark.parametrize("cmd, yes", [
    ("Stop-Process -Id 123 -Force  # streaming.capture", "restart"),
    ("Start-Process -FilePath C:\\x\\start_capture_daemon.bat", "restart"),
    ("cmd /c start_ed_console.bat", "restart"),
    ("gh pr merge 445 --merge", "merge 445"),
    ("gh api -X PUT repos/o/r/pulls/445/merge", "merge 445"),
    ("git push origin HEAD:main", "push main"),
    ("git push origin main", "push main"),
])
def test_production_actions_need_the_operators_yes_today(cmd, yes):
    assert guard.judge(_shell(cmd), TODAY, "") != []
    assert guard.judge(_shell(cmd), TODAY, f"{TODAY.isoformat()} {yes}\n") == []


def test_a_yes_to_one_merge_is_not_a_yes_to_another():
    assert guard.judge(_shell("gh pr merge 446"), TODAY, f"{TODAY.isoformat()} merge 445\n") != []


def test_the_hook_blocks_through_the_chain_the_settings_run():
    """The real wiring: .claude/settings.json runs hook_chain with this guard, exit 2 refuses."""
    settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert all("tools/operator_yes_guard.py" in c for c in commands)
    r = subprocess.run([sys.executable, "tools/hook_chain.py", "tools/operator_yes_guard.py"], cwd=REPO,
                       input=json.dumps(_shell("gh pr merge 99999")), capture_output=True, text=True)
    assert r.returncode == 2 and "merging pull request 99999" in r.stderr
