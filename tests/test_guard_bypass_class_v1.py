"""Guard bypass class — mandatory controls are not subject-disableable: an acting agent
cannot switch off its own guards. The test runs the real hook process with the prohibited
action and requires it to refuse.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_hook_entrypoint_rejects_no_verify():
    """Attempt the real hook process, not a helper-exists check."""
    payload = json.dumps(
        {
            "session_id": "bypass-class",
            "tool_name": "Bash",
            "tool_input": {"command": "git commit --no-verify -m x"},
            "cwd": str(ROOT),
        }
    )
    p = subprocess.run(
        [sys.executable, "-m", "tools.operator_law_guard"],
        input=payload,
        text=True,
        capture_output=True,
        cwd=str(ROOT),
        check=False,
    )
    assert p.returncode == 2, (p.returncode, p.stdout, p.stderr)
    assert "disables a mechanical lock" in p.stderr
