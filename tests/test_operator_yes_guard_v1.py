"""tools/operator_yes_guard.py (CLAUDE.md rule 6). A start or a clean stop of the daemon or the
console is put to the operator (Allow/Deny) during regular market hours and while the session is
unknown, and passes in Pre-Market, After-Hours and Closed; killing the daemon, the console or launch.py is refused, whatever its flags; a
stop of any other process passes; a stop of the machine and a merge ask; a push to main is
refused; every other action, a change to a test included, passes. Judged on real payloads and
through the hook chain the settings run.

Real data: Schwab's /markets answer for 2026-10-07 (tests/fixtures/real_schwab_markets_2026_10_07.json)
recorded as the daemon records it. STAND-INS: python processes whose command lines carry the
daemon's module, the console's app and launch.py (the guard reads command lines, as of production).
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import runtime_layout  # noqa: E402
import time_et  # noqa: E402
from stream_spine import CaptureWriter  # noqa: E402
from tools import operator_yes_guard as guard  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EXISTING = "tests/test_check_end_to_end_v1.py"     # a test that is on origin/main
MARKETS = json.loads((REPO / "tests" / "fixtures" / "real_schwab_markets_2026_10_07.json").read_text(encoding="utf-8"))
#: 2026-10-07 in ET: inside Schwab's pre-market, regular and post-market windows, after them, and a
#: date whose answer is not held
PRE, RTH, AFTER, CLOSED = (datetime(2026, 10, 7, h, m, tzinfo=time_et.ET) for h, m in ((7, 30), (10, 0), (17, 0), (21, 0)))
NOT_HELD = datetime(2026, 10, 20, 21, 0, tzinfo=time_et.ET)


def _edit(path: str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": path, "old_string": "a", "new_string": "b"}}


def _shell(cmd: str, tool: str = "Bash") -> dict:
    return {"tool_name": tool, "tool_input": {"command": cmd}, "cwd": str(REPO)}


def _chain(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "tools/hook_chain.py", "tools/operator_yes_guard.py"], cwd=REPO,
                          input=json.dumps(payload), capture_output=True, text=True)


@pytest.fixture(scope="module")
def markets(tmp_path_factory) -> Path:
    """A stream database holding Schwab's 2026-10-07 /markets answer, as the daemon records it."""
    db = tmp_path_factory.mktemp("stream") / "stream_capture.db"
    CaptureWriter(db)
    answer = MARKETS["answers"]["2026-10-07"]
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO stream_markets_raw(ts_recv,date,status,native_json,src) VALUES(?,?,?,?,?)",
                     (1791367200.0, "2026-10-07", answer["status"], answer["body"], "schwab_rest"))
    return db


def _stand_in(*marks: str, exe: str = sys.executable, cwd: Path = runtime_layout.RUNTIME_ROOT) -> subprocess.Popen:
    """A sleeping process whose command line carries `marks`, running in `cwd` (production's
    checkout by default, as the daemon and the console run)."""
    return subprocess.Popen([exe, "-c", "import time; time.sleep(600)", *marks], cwd=cwd)


@pytest.fixture(scope="module")
def procs(tmp_path_factory):
    """Running stand-ins: the daemon, the console, launch.py, a process of no production, and a
    test console in another checkout (as Playwright's in a worktree)."""
    running = {"daemon": _stand_in("-m", "app.market_data.schwab.streaming.capture"),
               "console": _stand_in("-m", "uvicorn", "server:app"),
               "launch": _stand_in("launch.py"),
               "other": _stand_in("some_research_job"),
               "worktree_console": _stand_in("-m", "uvicorn", "server:app", cwd=tmp_path_factory.mktemp("worktree"))}
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if pythonw.exists():
        running["daemon_w"] = _stand_in("-m", "app.market_data.schwab.streaming.capture", exe=str(pythonw))
    yield {name: p.pid for name, p in running.items()}
    for p in running.values():
        p.kill()
        p.wait()


def _decide(cmd: str, now: datetime, db: Path, tool: str = "Bash") -> str:
    return guard.decide(_shell(cmd, tool), now, db)[0]


STARTS_AND_CLEAN_STOPS = [
    "start_ed_console.bat", ".\\start_capture_daemon.bat", "& \"C:\\x\\start_ed_console.bat\"",
    "cmd /c start_ed_console.bat", ".venv\\Scripts\\python.exe launch.py", "python launch.py stop",
    "py launch.py", "py -m uvicorn server:app", "python -m uvicorn server:app --port 8000",
    "pythonw -m app.market_data.schwab.streaming.capture",
    "Start-Process -FilePath \"cmd.exe\" -ArgumentList '/c','start','\"Ed Console\"','\"C:\\x\\start_ed_console.bat\"'",
    "powershell -NoProfile -Command \"cmd /c start_ed_console.bat\"", "Invoke-Item .\\start_ed_console.bat",
    "ii launch.py", "explorer.exe start_ed_console.bat", "iex \"cmd /c start_capture_daemon.bat\"",
    "Start-Job { & .\\start_ed_console.bat }", "wmic process call create \"cmd /c C:\\x\\start_ed_console.bat\"",
    "[System.Diagnostics.Process]::Start('C:\\x\\start_ed_console.bat')", "schtasks /run /tn EdConsole",
]


@pytest.mark.parametrize("cmd", STARTS_AND_CLEAN_STOPS)
def test_a_start_or_clean_stop_asks_only_in_regular_hours_or_an_unknown_session(cmd, markets, tmp_path):
    for now in (PRE, AFTER, CLOSED):
        assert _decide(cmd, now, markets) == guard.PASS, now
    for now in (RTH, NOT_HELD):
        assert _decide(cmd, now, markets) == guard.ASK, now
    assert _decide(cmd, CLOSED, tmp_path / "no_database.db") == guard.ASK, "an unreadable session did not ask"


def test_regular_hours_are_schwabs_window_0830_to_1500_central(markets):
    """Schwab's regular window for 2026-10-07 is 09:30-16:00 ET (08:30-15:00 CT): a restart asks
    from its first minute to its last and passes the minute before and the minute it ends."""
    ct = time_et.ZoneInfo("America/Chicago")
    for (h, m), answer in (((8, 29), guard.PASS), ((8, 30), guard.ASK), ((14, 59), guard.ASK), ((15, 0), guard.PASS)):
        assert _decide("python launch.py stop", datetime(2026, 10, 7, h, m, tzinfo=ct), markets) == answer, (h, m)


KILLS = ["Stop-Process -Id {pid}", "Stop-Process -Id {pid} -Force", "Stop-Process {pid}", "spps -Id {pid}",
         "kill {pid}", "kill -9 {pid}", "taskkill /PID {pid}", "taskkill /PID {pid} /F", "tskill {pid}", "pskill {pid}",
         "(Get-Process -Id {pid}).Kill()", "wmic process where processid={pid} delete",
         "wmic process where processid={pid} call terminate",
         "Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\" | Invoke-CimMethod -MethodName Terminate",
         "Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\" | Remove-CimInstance",
         "Stop-Process -Id 4194300,{pid} -Force"]


@pytest.mark.parametrize("target", ["daemon", "console", "launch"])
@pytest.mark.parametrize("kill", KILLS)
def test_killing_the_daemon_the_console_or_launch_py_is_refused_at_any_hour(kill, target, procs, markets):
    for now in (RTH, CLOSED):
        assert _decide(kill.format(pid=procs[target]), now, markets) == guard.DENY


@pytest.mark.parametrize("kill", KILLS)
def test_killing_a_process_of_no_production_passes(kill, procs, markets):
    assert _decide(kill.format(pid=procs["other"]), RTH, markets) == guard.PASS
    assert _decide(kill.format(pid=procs["worktree_console"]), RTH, markets) == guard.PASS
    assert _decide(kill.format(pid=4194300), RTH, markets) == guard.PASS      # no such process


@pytest.mark.parametrize("cmd", ["taskkill /IM python.exe /F", "taskkill /IM python.exe", "Stop-Process -Name python",
                                 "Stop-Process -Name python -Force", "Get-Process python* | Stop-Process",
                                 "Get-Process python* | Stop-Process -Force", "tskill python",
                                 "wmic process where name='python.exe' delete",
                                 "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Remove-CimInstance",
                                 "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "
                                 "'*streaming.capture*' } | Stop-Process",
                                 # a target held in a variable, or a stop inside a script block
                                 "$ids = Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | Where-Object "
                                 "{ $_.CommandLine -like '*streaming.capture*' } | Select-Object -ExpandProperty "
                                 "ProcessId; Stop-Process -Id $ids -Force",
                                 "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn' } | "
                                 "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }",
                                 "$p = Get-CimInstance Win32_Process -Filter \"Name like 'python%'\"; "
                                 "Stop-Process -Id $p.ProcessId -Force"])
def test_killing_the_python_image_with_production_in_it_is_refused(cmd, procs, markets):
    assert _decide(cmd, CLOSED, markets) == guard.DENY


@pytest.mark.parametrize("cmd", ["taskkill /F /PID $pid",
                                 "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'pytest' } | "
                                 "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"])
def test_a_kill_whose_targets_are_chosen_when_it_runs_asks_while_production_runs(cmd, procs, markets):
    """Its targets cannot be read before it runs: it may reach the daemon or the console."""
    assert _decide(cmd, CLOSED, markets) == guard.ASK


def test_killing_the_pythonw_image_with_the_daemon_in_it_is_refused(procs, markets):
    if "daemon_w" not in procs:
        pytest.skip("no pythonw beside this Python (pythonw exists on Windows only)")
    for cmd in ("taskkill /IM pythonw.exe /F", "Stop-Process -Name pythonw", "Get-Process pythonw | Stop-Process"):
        assert _decide(cmd, CLOSED, markets) == guard.DENY, cmd


@pytest.mark.parametrize("cmd, answer", [
    ("Stop-Computer", guard.ASK), ("Restart-Computer -Force", guard.ASK), ("shutdown /r /t 0", guard.ASK),
    ("gh pr merge 445 --merge", guard.ASK), ("gh api -X PUT repos/o/r/pulls/445/merge", guard.ASK),
    ("git push origin main", guard.DENY), ("git push origin HEAD:main", guard.DENY),
    ("git push -q -u origin fix/some-branch", guard.PASS),
])
def test_the_machine_a_merge_and_a_push(cmd, answer, markets):
    assert _decide(cmd, CLOSED, markets) == answer


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
    _shell("git add launch.py tests/test_launch_v1.py"),
    _shell("python -m ruff check launch.py"),
    # commands that only name a launcher or a process, as reads, diffs and searches do
    _shell("Get-Content start_capture_daemon.bat, start_ed_console.bat", "PowerShell"),
    _shell("git -C ..\\wt diff origin/main...HEAD -- app start_capture_daemon.bat stream_spine.py"),
    _shell("git grep -n -E \"start_capture_daemon|uvicorn server:app|restart\" -- ."),
    _shell("Select-String -Path logs\\ed_server.log -Pattern 'uvicorn restart'", "PowerShell"),
    _shell("powershell -NoProfile -Command \"Get-CimInstance Win32_Process | Where-Object { $_.CommandLine "
           "-like '*streaming.capture*' }\""),
    _shell("file start_capture_daemon.bat && grep -c x start_capture_daemon.bat"),
    _shell("\"--- any python/uvicorn\"; Get-Process | Where-Object { $_.ProcessName -match 'python' }", "PowerShell"),
    _shell("grep -rn \"stop.set()\\|\\\"op\\\"\\|taskkill\" start_capture_daemon.bat launch.py"),
    _shell("git commit -q -F - @'\nstart_ed_console.bat runs it again after a fast-forward\n'@", "PowerShell"),
    # looking at processes, and stopping or opening something that is not production
    _shell("Get-Process python* | Select-Object Id, CPU", "PowerShell"),
    _shell("Get-Process -Id 18692", "PowerShell"),
    _shell("Stop-Process -Name node", "PowerShell"),
    _shell("taskkill /IM chrome.exe"),
    _shell("wmic process where name='python.exe' get processid,commandline"),
    _shell("ii .\\docs\\DATA_FLOW.md", "PowerShell"),
    _shell("explorer.exe .", "PowerShell"),
    _shell("schtasks /query /fo LIST"),
    _shell("git log --oneline --grep kill"),
    # a merge or a push to main named only as data: loop strings, a heredoc body
    _shell("for c in \"git push origin HEAD:main\" \"gh pr merge 427 --merge\"; do echo \"$c\"; done"),
    _shell("python - <<'EOF'\nprint('git push origin main; gh pr merge 1')\nEOF"),
])
def test_everything_else_passes_at_any_hour(payload, procs, markets):
    for now in (RTH, NOT_HELD):
        assert guard.decide(payload, now, markets) == (guard.PASS, [])


def test_the_hook_chain_answers_ask_refuses_and_passes_ordinary_work():
    """The real wiring: .claude/settings.json runs hook_chain with this guard; an action that
    needs a yes gets Claude Code's "ask" on stdout, a refused one exit 2 with the reason, other
    actions nothing."""
    settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert all("tools/operator_yes_guard.py" in c for c in commands)
    r = _chain(_shell("gh pr merge 99999"))
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert r.returncode == 0 and out["permissionDecision"] == "ask"
    assert "merges pull request 99999" in out["permissionDecisionReason"]
    refused = _chain(_shell("git push origin main"))
    assert refused.returncode == 2 and "pushes to main" in refused.stderr
    quiet = _chain(_edit(str(REPO / EXISTING)))
    assert quiet.returncode == 0 and quiet.stdout == ""
