"""The command guards read a command's statements the way a shell does (tools/shell_parse.read): a
statement behind a keyword (`if`, `then`), inside a subshell `( ... )`, behind a wrapper
(`timeout`), in a shell's command string or a heredoc fed to a shell is judged, and text inside
quotes is never read as a statement."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import time_et
from tools import operating_process_lock as OPL
from tools import operator_yes_guard as yes_guard
from tools.operator_law_guard import bash_violations
from tools.sed_edit_guard import edits

#: Split so this file's own text is not read as the actions it names.
D = "d" + "ata"
CLOSED = datetime(2026, 10, 7, 21, 0, tzinfo=time_et.ET)
NO_DB = Path("no-such-stream.db")


def _yes(cmd: str) -> str:
    return yes_guard.decide({"tool_name": "Bash", "tool_input": {"command": cmd}}, CLOSED, NO_DB)[0]


@pytest.mark.parametrize("cmd", ["if gh pr checks 5; then gh pr merge 5; fi", "(gh pr merge 5)",
                                 "timeout 600 gh pr merge 5", "bash -c \"gh pr merge 5\"",
                                 "pwsh -NoProfile -Command \"gh pr merge 5\""])
def test_a_merge_behind_a_keyword_a_subshell_a_wrapper_or_a_shell_asks(cmd):
    assert _yes(cmd) == yes_guard.ASK


@pytest.mark.parametrize("tool, cmd", [
    ("Bash", "cmd //c start_ed_console.bat > boot.log 2>&1"),                       # Git Bash's //c
    ("Bash", "powershell -NoProfile -Command \"\\$p = Start-Process cmd.exe -ArgumentList "
             "'/c','start_capture_daemon.bat' -PassThru\""),                       # a PowerShell assignment
])
def test_a_start_through_cmd_or_a_powershell_assignment_asks_while_the_session_is_unknown(tool, cmd):
    assert yes_guard.decide({"tool_name": tool, "tool_input": {"command": cmd}}, CLOSED, NO_DB)[0] == yes_guard.ASK


@pytest.mark.parametrize("cmd", [f"(rm -rf {D}/x)", f"if true; then rm -rf {D}/x; fi", f"timeout 5 rm -rf {D}/x"])
def test_a_protected_tree_removal_behind_a_keyword_a_subshell_or_a_wrapper_is_refused(cmd):
    assert any(f"under {D}/" in b for b in bash_violations(cmd))


@pytest.mark.parametrize("cmd", ["(sed -i s/a/b/ notes.txt)", "if true; then sed -i s/a/b/ notes.txt; fi",
                                 "timeout 5 sed -i s/a/b/ notes.txt", "bash <<'EOF'\nsed -i s/a/b/ notes.txt\nEOF",
                                 "/c/Program\\ Files/Git/usr/bin/sed.exe -i s/a/b/ notes.txt"])
def test_a_sed_edit_behind_a_keyword_a_subshell_a_wrapper_or_a_heredoc_is_refused(cmd):
    assert edits(cmd)


#: commit commands as agents ran them (session transcripts): a message from a heredoc holding an
#: apostrophe, a PowerShell here-string holding one, a PowerShell backtick escape in a string, a
#: PowerShell script block in the pipe
PIPED_COMMITS = [
    ("Bash", "git commit -m \"$(cat <<'EOF'\nfix: the operator's guard (one reader)\nEOF\n)\" 2>&1 | tail -3"),
    ("PowerShell", "$msg = @'\nTraining's full rebuild is unchanged.\n'@; git commit -m $msg 2>&1 | Select-Object -Last 2"),
    ("PowerShell", "Write-Output \"`n=== commit ===\"\ngit commit -F msg.txt 2>&1 | Select-Object -Last 20\n"
                   "Write-Output \"`n=== HEAD ===\""),
    ("PowerShell", "git commit -m $msg 2>&1 | ForEach-Object { $_ } | Select-Object -First 25"),
]


@pytest.mark.parametrize("tool, cmd", PIPED_COMMITS)
def test_a_piped_commit_is_refused_whatever_its_message_holds(tool, cmd):
    assert OPL.commit_pipe_violations(cmd, tool == "PowerShell")


def test_a_wipe_after_a_heredoc_message_with_an_apostrophe_is_refused():
    assert OPL.reset_guard_violations("git commit -m \"$(cat <<'EOF'\nit's done\nEOF\n)\" && git reset --hard")


@pytest.mark.parametrize("tool, cmd", [
    ("Bash", "git commit -m \"$(cat <<'EOF'\nreplaced taskkill with psutil.Process(pid).kill() in launch.py\nEOF\n)\""),
    ("PowerShell", "$add = @'\n- by method: `(Get-Process).Kill()`, `Stop-Process -Id` of launch.py\n'@; Set-Content -Path f.md -Value $add"),
])
def test_a_kill_named_in_a_message_or_a_here_string_passes(tool, cmd):
    assert yes_guard.decide({"tool_name": tool, "tool_input": {"command": cmd}}, CLOSED, NO_DB)[0] == yes_guard.PASS


@pytest.mark.parametrize("cmd", ['"/c/Program Files/GitHub CLI/gh" pr merge 5', "'/opt/my tools/gh' pr merge 5"])
def test_a_quoted_program_path_with_a_space_runs_in_bash(cmd):
    """In bash a quoted program path runs that program; only PowerShell prints a quoted phrase."""
    assert _yes(cmd) == yes_guard.ASK


@pytest.mark.parametrize("code", ["-" * 100000 + "1", "1" + "+1" * 200000], ids=["deep-unary", "deep-sum"])
def test_python_code_too_deep_to_parse_does_not_crash_a_guard(code):
    cmd = f'python -c "{code}"'
    assert bash_violations(cmd) == [] and _yes(cmd) == yes_guard.PASS


@pytest.mark.parametrize("runner", ["uv run --with requests", "uv run -p 3.12", "uv run --python 3.12 --project .",
                                    "poetry run -C .", "pdm run -p ."])
def test_a_python_behind_a_runner_with_valued_options_is_judged(runner):
    assert any(f"under {D}/" in b for b in bash_violations(
        f"{runner} python -c \"import shutil; shutil.rmtree('{D}/x')\""))


def test_a_heredoc_piped_into_python_is_judged_as_python():
    assert any(f"under {D}/" in b for b in bash_violations(
        f"cat <<'EOF' | python -\nimport shutil; shutil.rmtree('{D}/x')\nEOF"))


@pytest.mark.parametrize("cmd", ["export SKIP=ruff-correctness; git commit -m x",
                                 "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null "
                                 "git commit -m x"])
def test_a_lock_disable_through_the_environment_is_refused(cmd):
    assert any("disables a mechanical lock" in b for b in bash_violations(cmd))


@pytest.mark.parametrize("tool, cmd", [("Bash", "wsl git reset --hard"),
                                       ("Bash", "python -c \"import os; os.system('git reset --hard')\""),
                                       ("Bash", "a=($(git reset --hard))"),
                                       ("PowerShell", "@'\ngit reset --hard\n'@ | iex")])
def test_a_wipe_run_by_another_program_is_refused(tool, cmd):
    assert OPL.reset_guard_violations(cmd, tool == "PowerShell")


def test_a_kill_written_as_an_argument_is_refused_and_an_empty_pipe_input_does_not_crash():
    for kill in ("Write-Output (Get-Process | Where-Object { $_.Path -like '*launch.py*' }).Kill()",
                 "@(Get-Process | Where-Object { $_.Path -like '*launch.py*' }).Kill()"):
        assert yes_guard.decide({"tool_name": "PowerShell", "tool_input": {"command": kill}},
                                CLOSED, NO_DB)[0] == yes_guard.DENY, kill
    assert yes_guard.decide({"tool_name": "Bash", "tool_input": {"command": ">/dev/null | kill 4194300"}},
                            CLOSED, NO_DB)[0] in (yes_guard.PASS, yes_guard.ASK)


def test_a_checkout_naming_no_path_passes_as_on_main():
    """`git checkout -q --` checks out no path; with a path after `--` it is refused."""
    assert not OPL.reset_guard_violations("git checkout -q -- 2>/dev/null")
    assert OPL.reset_guard_violations("git checkout -q -- server.py")


@pytest.mark.parametrize("quoted", ['git commit -m "{}"', 'gh pr create --title x --body "{}"', 'echo "{}"'])
def test_text_inside_quotes_is_not_a_statement(quoted):
    """Quoted text that names an action, with `;` or `(` inside the quotes, runs nothing."""
    assert not any(f"under {D}/" in b for b in bash_violations(quoted.format(f"note; rm -rf {D}/x (eval rm -rf {D}/y)")))
    assert edits(quoted.format("docs; sed -i s/a/b/ f (sed -i x)")) == []
    assert _yes(quoted.format("asks; then gh pr merge 5 (gh pr merge 6)")) == yes_guard.PASS
