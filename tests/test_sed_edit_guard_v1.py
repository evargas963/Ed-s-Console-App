"""The sed edit guard (tools/sed_edit_guard.py), run as Claude Code runs it: the wired hook chain
on a hook payload, its exit code (2 refuses the command) and its message. On 2026-10-03 an agent
changed a line of calibration/complete_chain_capture.py with `sed -i` against AGENTS.md
("never edit source through a script")."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _hook(tool: str, tool_input: dict) -> subprocess.CompletedProcess[str]:
    payload = {"tool_name": tool, "tool_input": tool_input, "cwd": str(ROOT)}
    return subprocess.run([sys.executable, str(ROOT / "tools" / "hook_chain.py"), "tools/sed_edit_guard.py"],
                          cwd=str(ROOT), input=json.dumps(payload), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=_ENV, timeout=120)


@pytest.mark.parametrize("command", [
    "sed -i 's/-> None:/-> bool:/' calibration/complete_chain_capture.py",   # 2026-10-03
    "sed -i.bak 's/a/b/' f.txt",
    "sed -ni 's/a/b/p' f.txt",
    "sed --in-place 's/a/b/' f.txt",
    "sed --in-place=.orig 's/a/b/' f.txt",
    "cd /c/Users/evarg/Documents/Trading/EdWebConsole && sed -i 's/a/b/' f.txt",
    "git status\nsed -i 's/a/b/' f.txt",
    "find . -name '*.py' -exec sed -i 's/a/b/' {} +",
    "ls *.py | xargs sed -i 's/a/b/'",
    "sed 's/a/b/' f.txt > f.new && mv f.new f.txt",
    "sed 's/a/b/' f.txt >> g.txt",
    "\"C:/Program Files/Git/usr/bin/sed.exe\" -i 's/a/b/' f.txt",
    "sed.exe -i 's/a/b/' f.txt",
    "bash -c \"sed -i 's/a/b/' f.txt\"",
])
def test_a_sed_that_writes_a_file_is_refused_with_what_to_use_instead(command):
    r = _hook("Bash", {"command": command})
    assert r.returncode == 2, (command, r.stderr)
    assert "edits a file with sed" in r.stderr and "Edit tool" in r.stderr, r.stderr


def test_powershell_running_sed_is_judged_the_same():
    r = _hook("PowerShell", {"command": "sed -i 's/a/b/' f.txt"})
    assert r.returncode == 2 and "edits a file with sed" in r.stderr, r.stderr


@pytest.mark.parametrize("command", [
    "sed -n '1,5p' calibration/complete_chain_capture.py",
    "sed 's/a/b/' f.txt",
    "sed -n '5p' f.txt 2>/dev/null",
    "sed -E 's/x+/y/' f.txt > /dev/null",
    "git log --oneline | sed -n '1,3p'",
    "grep -i sed f.txt",
    "git commit -m 'never sed -i a file'",
    "git commit -F - <<'EOF'\nsed -i was used here\nEOF",
    "cat f.txt",
])
def test_a_sed_that_only_prints_and_commands_that_merely_mention_sed_pass(command):
    r = _hook("Bash", {"command": command})
    assert r.returncode == 0, (command, r.stderr)


def test_the_edit_and_write_tools_pass():
    for tool, tool_input in (("Edit", {"file_path": "f.txt", "old_string": "a", "new_string": "b"}),
                             ("Write", {"file_path": "f.txt", "content": "b"})):
        r = _hook(tool, tool_input)
        assert r.returncode == 0, (tool, r.stderr)
