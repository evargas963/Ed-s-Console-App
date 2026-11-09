"""A tool run as a script (`python tools/x.py`) imports nothing from the root or from `tools`.

A tool the repository says to run as a script imports nothing from the repository root or from
`tools`: run that way, Python puts `tools/` on the import path, not the
root, and the import fails before the tool starts. tools/cpu_load.py and
tools/schwab_field_inventory.py were documented so after both came to import time_et, and the
flaky-test procedure ran its suites with no load at all (2026-11-07). A tool that needs the root
is run with `python -m tools.<name>`.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
#: a command that runs a tool as a script
SCRIPT_RUN = re.compile(r"python(?:\.exe)?\s+tools/(\w+)\.py")
#: text a command can be written in
TEXT = {".md", ".py", ".yml", ".yaml", ".toml", ".json", ".bat", ".ps1", ".mjs", ".js", ".cfg"}


def _tracked() -> list[str]:
    return subprocess.run(
        ["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()


def _imported(tool: str) -> set[str]:
    tree = ast.parse((REPO / "tools" / f"{tool}.py").read_text(encoding="utf-8"))
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module and not n.level
    }
    return {name.split(".")[0] for name in names}


def test_a_tool_run_as_a_script_imports_nothing_from_the_root():
    tracked = _tracked()
    root = {Path(f).stem for f in tracked if "/" not in f and f.endswith(".py")} | {"tools", "app"}
    named = {
        tool
        for f in tracked
        if Path(f).suffix in TEXT and (REPO / f).is_file()
        for tool in SCRIPT_RUN.findall((REPO / f).read_text(encoding="utf-8", errors="replace"))
        if (REPO / "tools" / f"{tool}.py").is_file()
    }
    assert "keep_going" in named, "the scan reads the settings that run the Stop hook as a script"
    broken = {tool: sorted(_imported(tool) & root) for tool in sorted(named)}
    assert {tool: mods for tool, mods in broken.items() if mods} == {}
