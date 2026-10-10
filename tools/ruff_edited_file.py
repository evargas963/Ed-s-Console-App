"""PostToolUse hook: ruff on the Python file an Edit, Write or MultiEdit just changed.

Reads the hook's JSON on stdin. For a .py file that exists, runs ruff with the commit hook's selection;
its findings go to stderr with exit 2, so Claude sees them at once.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

#: the commit hook's and the hardening job's selection
SELECT = "F401,F821,E9"


def findings(path: Path) -> "str | None":
    """ruff's findings for `path`, or None when it has none."""
    done = subprocess.run([sys.executable, "-m", "ruff", "check", str(path), "--select", SELECT],
                          capture_output=True, text=True)
    return None if done.returncode == 0 else done.stdout + done.stderr


def main() -> int:
    tool_input = json.load(sys.stdin).get("tool_input")
    file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(file_path, str) or not file_path.endswith(".py") or not Path(file_path).is_file():
        return 0
    found = findings(Path(file_path))
    if found is None:
        return 0
    sys.stderr.write(f"ruff ({SELECT}) found problems in {file_path}:\n{found}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
