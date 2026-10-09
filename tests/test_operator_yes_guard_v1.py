"""tools/operator_yes_guard.py (CLAUDE.md rule 6), judged on the program each statement runs: a
start, stop or restart of the daemon or the console asks (Allow/Deny) during regular market hours
and while the session is unknown, and passes otherwise; a merge and a machine restart ask; a push
to main is refused; everything else, a command that only names a launcher included, passes.

Real data: Schwab's /markets answer for 2026-10-07 (tests/fixtures/real_schwab_markets_2026_10_07.json)
recorded as the daemon records it.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stream_spine import CaptureWriter  # noqa: E402
from tools import operator_yes_guard as guard  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
MARKETS = json.loads((REPO / "tests" / "fixtures" / "real_schwab_markets_2026_10_07.json").read_text(encoding="utf-8"))
CT = ZoneInfo("America/Chicago")
#: 2026-10-07 in Central Time: Schwab's pre-market, regular and post-market windows, after them
PRE, RTH, AFTER, CLOSED = (datetime(2026, 10, 7, h, m, tzinfo=CT) for h, m in ((7, 0), (9, 0), (16, 0), (20, 0)))
NOT_HELD = datetime(2026, 10, 20, 9, 0, tzinfo=CT)     # a date whose answer is not recorded


@pytest.fixture(scope="module")
def markets(tmp_path_factory) -> Path:
    db = tmp_path_factory.mktemp("stream") / "stream_capture.db"
    CaptureWriter(db)
    answer = MARKETS["answers"]["2026-10-07"]
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO stream_markets_raw(ts_recv,date,status,native_json,src) VALUES(?,?,?,?,?)",
                     (1791367200.0, "2026-10-07", answer["status"], answer["body"], "schwab_rest"))
    return db


def _decide(cmd: str, now: datetime, db: Path) -> str:
    return guard.decide({"tool_name": "PowerShell", "tool_input": {"command": cmd}}, now, db)[0]


STARTS_AND_STOPS = [
    "start_ed_console.bat", ".\\start_capture_daemon.bat", "& \"C:\\x\\start_ed_console.bat\"",
    "cmd /c start_ed_console.bat", ".venv\\Scripts\\python.exe launch.py", "py -m uvicorn server:app",
    "pythonw -m app.market_data.schwab.streaming.capture", "Invoke-Item .\\start_ed_console.bat",
    "Start-Process -FilePath \"cmd.exe\" -ArgumentList '/c','start','\"Ed Console\"','\"C:\\x\\start_ed_console.bat\"'",
    "powershell -NoProfile -Command \"cmd /c start_ed_console.bat\"",
    "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*streaming.capture*' } | Stop-Process -Force",
    "taskkill /F /FI \"WINDOWTITLE eq Ed Console\"; .\\start_ed_console.bat",
]


@pytest.mark.parametrize("cmd", STARTS_AND_STOPS)
def test_a_start_or_stop_asks_only_in_regular_hours_or_an_unknown_session(cmd, markets, tmp_path):
    for now in (PRE, AFTER, CLOSED):
        assert _decide(cmd, now, markets) == guard.PASS, now
    for now in (RTH, NOT_HELD):
        assert _decide(cmd, now, markets) == guard.ASK, now
    assert _decide(cmd, CLOSED, tmp_path / "none.db") == guard.ASK, "an unreadable session did not ask"


def test_regular_hours_are_schwabs_window_0830_to_1500_central(markets):
    for (h, m), answer in (((8, 29), guard.PASS), ((8, 30), guard.ASK), ((14, 59), guard.ASK), ((15, 0), guard.PASS)):
        assert _decide("start_ed_console.bat", datetime(2026, 10, 7, h, m, tzinfo=CT), markets) == answer, (h, m)


@pytest.mark.parametrize("cmd, answer", [
    ("Stop-Computer", guard.ASK), ("Restart-Computer -Force", guard.ASK), ("shutdown /r /t 0", guard.ASK),
    ("gh pr merge 445 --merge", guard.ASK), ("gh api -X PUT repos/o/r/pulls/445/merge", guard.ASK),
    ("for n in 1 2; do gh pr merge $n --merge; done", guard.ASK),
    ("git push origin main", guard.DENY), ("git push origin HEAD:main", guard.DENY),
    ("git push -q -u origin fix/some-branch", guard.PASS),
])
def test_the_machine_a_merge_and_a_push(cmd, answer, markets):
    assert _decide(cmd, CLOSED, markets) == answer


@pytest.mark.parametrize("cmd", [
    "Get-Content start_capture_daemon.bat, start_ed_console.bat",
    "git -C ..\\wt diff origin/main...HEAD -- start_capture_daemon.bat",
    "git grep -n -E \"start_capture_daemon|uvicorn server:app|restart\" -- .",
    "Select-String -Path logs\\ed_server.log -Pattern 'uvicorn restart'",
    "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*streaming.capture*' }",
    "\"--- any python/uvicorn\"; Get-Process | Where-Object { $_.ProcessName -match 'python' }",
    "git add launch.py tests/test_launch_v1.py", "python -m pytest tests/test_launch_v1.py -q",
    "git commit -q -F - @'\nstart_ed_console.bat runs it again\n'@",
    "for c in \"git push origin main\" \"gh pr merge 1\"; do echo \"$c\"; done",
    "python - <<'EOF'\nprint('git push origin main')\nEOF",
    "Stop-Process -Name node", "gh pr view 445 --json state",
])
def test_a_command_that_only_names_a_launcher_or_a_push_passes_in_regular_hours(cmd, markets):
    assert _decide(cmd, RTH, markets) == guard.PASS


def test_an_edit_passes_and_the_hook_chain_asks_and_refuses():
    """The real wiring (.claude/settings.json runs hook_chain with this guard)."""
    def chain(payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "tools/hook_chain.py", "tools/operator_yes_guard.py"], cwd=REPO,
                              input=json.dumps(payload), capture_output=True, text=True)
    settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert all("tools/operator_yes_guard.py" in h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"])
    asked = chain({"tool_name": "Bash", "tool_input": {"command": "gh pr merge 99999"}})
    assert asked.returncode == 0 and json.loads(asked.stdout)["hookSpecificOutput"]["permissionDecision"] == "ask"
    refused = chain({"tool_name": "Bash", "tool_input": {"command": "git push origin main"}})
    assert refused.returncode == 2 and "pushes to main" in refused.stderr
    edit = chain({"tool_name": "Edit", "tool_input": {"file_path": str(REPO / "server.py"), "old_string": "a",
                                                      "new_string": "b"}})
    assert edit.returncode == 0 and edit.stdout == ""
