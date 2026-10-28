"""The agent hook: ruff on each edited Python file (tools/ruff_edited_file.py, PostToolUse)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _hook(script: str, event: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "tools" / script)], input=json.dumps(event),
                          capture_output=True, text=True, cwd=ROOT)


def test_an_edited_python_file_with_a_finding_is_reported_and_a_clean_one_passes(tmp_path):
    bad, clean, doc = tmp_path / "bad.py", tmp_path / "clean.py", tmp_path / "notes.md"
    bad.write_text("import os\n", encoding="utf-8")
    clean.write_text("x = 1\n", encoding="utf-8")
    doc.write_text("import os\n", encoding="utf-8")
    found = _hook("ruff_edited_file.py", {"tool_name": "Edit", "tool_input": {"file_path": str(bad)}})
    assert found.returncode == 2 and "F401" in found.stderr
    for path in (clean, doc):
        assert _hook("ruff_edited_file.py", {"tool_name": "Write", "tool_input": {"file_path": str(path)}}).returncode == 0
