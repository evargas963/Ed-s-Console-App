"""Guard bypass class — mandatory controls are not subject-disableable (RC-450/RC-454).

Carried forward from the Architecture A battery when the role/authority machinery was
torn down (operator, 2026-08-24): the ROLES are gone, but the property that an acting
agent cannot switch off its own guards is not role machinery — it is what makes the
remaining small guard surface real. These tests attempt the prohibited action and
require the real boundary to reject it; a function-exists assertion is not enough.
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
    out = G.bash_violations("git commit --no-verify -m x", [], payload_cwd=str(ROOT))
    assert any("disables a mechanical lock" in v for v in out), out


def test_hook_entrypoint_rejects_no_verify_with_guard_env_off(monkeypatch):
    """Attempt the real hook process, not a helper-exists check."""
    monkeypatch.setenv("ED_OPERATOR_LAW_GUARD", "off")
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
