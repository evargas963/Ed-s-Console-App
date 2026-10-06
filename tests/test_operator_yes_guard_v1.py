"""tools/operator_yes_guard.py (CLAUDE.md rule 6): starting or stopping the daemon or console, a merge,
a push to main and a write to a database under data/ are put to the operator (the hook answers "ask");
ordinary work and any test change (Ed 2026-10-05: tests need no approval) pass. Judged on real
payloads and through the hook chain the settings run."""
from __future__ import annotations

import json
import os
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


def test_test_changes_pass_and_production_and_database_writes_still_ask_through_the_hook_chain():
    """Ed 2026-10-05: writing, changing or deleting a test needs no approval; a merge, a push to
    main, a daemon start and a write to a production database still get the Allow/Deny prompt."""
    for payload in (_edit(EXISTING),
                    {"tool_name": "Write", "tool_input": {"file_path": NEW, "content": "x"}},
                    _shell(f"git rm -q {EXISTING}")):
        r = _chain(payload)
        assert r.returncode == 0 and r.stdout == "", (payload, r.stdout, r.stderr)
    for payload, what in ((_shell("gh pr merge 5"), "merges pull request 5"),
                          (_shell("git push origin main"), "pushes to main"),
                          (_shell("start_capture_daemon.bat"), "daemon or the console"),
                          ({"tool_name": "Write", "tool_input": {"file_path": "data/ed_console.db", "content": ""}},
                           "writes data/ed_console.db, a database under data/")):
        r = _chain(payload)
        out = json.loads(r.stdout)["hookSpecificOutput"]
        assert r.returncode == 0 and out["permissionDecision"] == "ask", (payload, r.stdout)
        assert what in out["permissionDecisionReason"], out


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
def test_writing_changing_or_deleting_a_test_passes(payload):
    assert guard.reasons(payload) == []


@pytest.mark.parametrize("cmd, what", [
    ("Stop-Process -Id 123 -Force  # streaming.capture", "daemon or the console"),
    ("Start-Process -FilePath C:\\x\\start_capture_daemon.bat", "daemon or the console"),
    ("cmd /c start_ed_console.bat", "daemon or the console"),
    ("gh pr merge 445 --merge", "merges pull request 445"),
    ("gh api -X PUT repos/o/r/pulls/445/merge", "merges pull request 445"),
    ("git push origin HEAD:main", "pushes to main"),
    ("git push origin main", "pushes to main"),
    # reviewer 2026-10-06: each of these passed with no prompt on dd35be84 and on main
    ("gh pr merge --squash 477", "merges pull request 477"),
    ("gh pr merge --auto --merge 477", "merges pull request 477"),
    ("gh pr merge", "merges pull request (the one gh picks)"),
    ("gh pr merge https://github.com/o/r/pull/5 --merge", "merges pull request 5"),
    ("gh pr merge fix/some-branch", "merges pull request (the one gh picks)"),
    ("gh -R owner/repo pr merge 477", "merges pull request 477"),
    ("gh.exe pr merge 477", "merges pull request 477"),
    ("C:\\gh\\gh.exe pr merge 477", "merges pull request 477"),
    ("\"C:\\Program Files\\GitHub CLI\\gh.exe\" pr merge 477", "merges pull request 477"),
    ("bash -c \"gh pr merge 5\"", "merges pull request 5"),
    ("gh api graphql -f query='mutation { mergePullRequest(input: {}) { clientMutationId } }'",
     "merges pull request"),
    ("git push origin HEAD:refs/heads/main", "pushes to main"),
    ("git push origin +main", "pushes to main"),
    ("git push --all origin", "pushes to main"),
    ("C:\\Git\\cmd\\git.exe push origin main", "pushes to main"),
    ("Stop-Process -Name python -Force", "daemon or the console"),
    ("taskkill /IM python.exe /F", "daemon or the console"),
    (".venv/Scripts/python.exe -m uvicorn server:app --port 8000", "daemon or the console"),
    (".venv/Scripts/python.exe -m streaming.capture", "daemon or the console"),
])
def test_production_actions_are_put_to_the_operator(cmd, what):
    assert any(what in r for r in guard.reasons(_shell(cmd))), guard.reasons(_shell(cmd))


def test_a_push_of_the_current_branch_asks_only_when_it_is_main(tmp_path):
    """`git push` with no refspec, or `HEAD`, pushes the branch checked out: main asks, another
    branch passes, and a branch that cannot be read asks."""
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path / "r")], check=True)
    on_main = {"tool_name": "Bash", "cwd": str(tmp_path / "r")}
    for cmd in ("git push", "git push origin", "git push origin HEAD", "git push -u origin HEAD"):
        assert "pushes to main (rule 6: production)" in guard.reasons({**on_main, "tool_input": {"command": cmd}}), cmd
    (tmp_path / "r" / ".git" / "HEAD").write_text("ref: refs/heads/feature\n", encoding="utf-8")
    assert guard.reasons({**on_main, "tool_input": {"command": "git push"}}) == []
    nowhere = {"tool_name": "Bash", "cwd": str(tmp_path / "missing"), "tool_input": {"command": "git push"}}
    assert "pushes to main (rule 6: production)" in guard.reasons(nowhere)


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
    _shell("git log --grep push"),
    _shell("python -m pytest tests/test_restart_x.py -q"),
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
    (_shell("cd data && sqlite3 ed_console.db \"VACUUM\""), "data" + os.sep + "ed_console.db"),
    (_shell("cd data && cp /tmp/x.db ed_console.db"), "data" + os.sep + "ed_console.db"),
    ({"tool_name": "Bash", "tool_input": {"command": "sqlite3 ed_console.db 'DELETE FROM t'"},
      "cwd": str(REPO / "data")}, "data" + os.sep + "ed_console.db"),
    (_shell("sqlite3 data/ed_console.db 'DELETE FROM t' # mode=ro"), "data/ed_console.db"),
    (_shell("python -c \"import sqlite3; sqlite3.connect('data/ed_console.db').execute('DELETE FROM t')  # mode=ro\""),
     "data/ed_console.db"),
    (_shell("python -c \"import sqlite3; sqlite3.connect('file:data/ed_console.db?mode=ro', uri=True)\" && "
            "sqlite3 data/stream_capture.db 'DELETE FROM t'"), "data/stream_capture.db"),
])
def test_a_write_to_a_database_under_data_is_put_to_the_operator(payload, db):
    assert any(f"{db}, a database under data/" in r for r in guard.reasons(payload)), guard.reasons(payload)


D = "data/ed_console.db"
DELETE = f"import sqlite3; sqlite3.connect('{D}').execute('DELETE FROM t')"


@pytest.mark.parametrize("cmd, tool", [
    # copies, moves and redirects onto a database
    ("cp /tmp/other.db data/ed_console.db", "Bash"),
    ("Copy-Item C:\\tmp\\x.db data\\ed_console.db -Force", "PowerShell"),
    ("cp /tmp/other.db-wal data/stream_capture.db-wal", "Bash"),
    ("cmd /c \"echo x & copy C:\\tmp\\x.db data\\ed_console.db\"", "Bash"),
    ("grep -c rows data/ed_console.db | cp /tmp/x.db data/ed_console.db", "Bash"),
    ("Copy-Item -Destination data\\ed_console.db -Path C:\\tmp\\x.db", "PowerShell"),
    ("echo x 1> data/ed_console.db", "Bash"),
    ("rsync /tmp/x.db data/ed_console.db", "Bash"),
    ("sqlite3 data/ed_console.db 'DELETE FROM t' # ?mode=ro", "Bash"),
    # the 19 forms the correctness review found passing on dd35be84 (2026-10-06)
    (f'DB={D}; sqlite3 "$DB" "DELETE FROM t"', "Bash"),
    (f"export DB={D} && python tools/some_backfill.py", "Bash"),
    (f"ED_DB={D} python tools/some_backfill.py", "Bash"),
    ("$db = 'data\\ed_console.db'; sqlite3 $db 'DELETE FROM t'", "PowerShell"),
    ("$p = 'data\\ed_console.db'; python -c \"import sqlite3,sys; sqlite3.connect(sys.argv[1]).execute('DELETE FROM t')\" $p",
     "PowerShell"),
    (f"echo \"{DELETE}\" | python", "Bash"),
    ('for f in data/*.db; do sqlite3 "$f" VACUUM; done', "Bash"),
    ("ls data/*.db | xargs -n1 -I{} sqlite3 {} VACUUM", "Bash"),
    (f"bash -c \"sqlite3 {D} 'DELETE FROM t'\"", "Bash"),
    ("cmd /c sqlite3 data\\ed_console.db VACUUM", "Bash"),
    ('powershell -Command "sqlite3 data\\ed_console.db VACUUM"', "PowerShell"),
    (f'python3.13 -c "{DELETE}"', "Bash"),
    (f'uv run python -c "{DELETE}"', "Bash"),
    (f"$py = '.venv\\Scripts\\python.exe'; & $py -c \"{DELETE}\"", "PowerShell"),
    (f"cat > /tmp/fix.py <<'EOF'\n{DELETE}\nEOF\npython /tmp/fix.py", "Bash"),
    (f"python - <<'PY-END'\n{DELETE}\nPY-END", "Bash"),
    (f"git commit -m 'wip\\'; sqlite3 {D} \"DELETE FROM t\"; echo '", "Bash"),
    (f'pythonw -c "{DELETE}"', "Bash"),
    ('Invoke-Expression "sqlite3 data\\ed_console.db VACUUM"', "PowerShell"),
    ("cd data && python -c \"import sqlite3; sqlite3.connect('ed_console.db').execute('DELETE FROM t')\"", "Bash"),
    # not every statement is a known read
    ("cp data/ed_console.db /tmp/ed_console_copy.db", "Bash"),
    ("ls -la data/ed_console.db && python -c \"print(1)\"", "Bash"),
])
def test_a_command_naming_a_database_asks_unless_every_statement_only_reads(cmd, tool):
    """Fails closed: a command that names a database under data/ anywhere (its -c code, heredocs
    and variables included) asks, unless every statement in it is a known read."""
    assert any(", a database under data/ (rule 6: production)" in r for r in guard.reasons(_shell(cmd, tool))), cmd


@pytest.mark.parametrize("cmd", [
    ".venv/Scripts/python.exe -c \"import sqlite3; c = sqlite3.connect('file:data/ed_console.db?mode=ro', uri=True); "
    "print(c.execute('SELECT COUNT(*) FROM level_crosses').fetchone())\"",
    "sqlite3 -readonly data/stream_capture.db \"SELECT COUNT(*) FROM stream_bars_raw\"",
    "ls -la data/ed_console.db data/stream_capture.db",
    "python -m pytest tests/test_chain_history_v1.py -q",
    "grep -n \"sqlite3 data/ed_console.db\" docs/DATA_FLOW.md",
    "cat data/notes.txt && dir data\\ed_console.db",
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
