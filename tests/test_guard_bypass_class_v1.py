"""Guard bypass class — mandatory controls are not subject-disableable: an acting agent
cannot switch off its own guards. These tests attempt the prohibited action and require the
real boundary to reject it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.operator_law_guard as G  # noqa: E402


def test_git_commit_no_verify_blocks():
    out = G.bash_violations("git commit --no-verify -m x")
    assert any("disables a mechanical lock" in v for v in out), out


def test_hook_entrypoint_rejects_no_verify():
    """Attempt the real hook process, not a helper-exists check."""
    payload = json.dumps({
        "session_id": "bypass-class",
        "tool_name": "Bash",
        "tool_input": {"command": "git commit --no-verify -m x"},
        "cwd": str(ROOT),
    })
    p = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "operator_law_guard.py")],
        input=payload,
        text=True,
        capture_output=True,
        cwd=str(ROOT),
        check=False,
    )
    assert p.returncode == 2, (p.returncode, p.stdout, p.stderr)
    assert "disables a mechanical lock" in p.stderr
