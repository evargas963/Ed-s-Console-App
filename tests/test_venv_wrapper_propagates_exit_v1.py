"""tools/run_with_repo_venv.py, run the way pre-commit runs it, passes its target's exit code
and output to the caller (on Windows os.execv spawns, so the wrapper must wait)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = ROOT / "tools" / "run_with_repo_venv.py"


def _target(tmp_path: Path, code: int) -> Path:
    p = tmp_path / f"exit{code}.py"
    p.write_text(f"import sys\nprint('CHILD-RAN-{code}', flush=True)\nsys.exit({code})\n",
                 encoding="utf-8")
    return p


def test_nonzero_exit_reaches_the_caller(tmp_path: Path) -> None:
    """The property the wrapper exists to provide, and the one nothing asserted."""
    r = subprocess.run([sys.executable, str(WRAPPER), str(_target(tmp_path, 7))],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 7, (
        f"wrapper returned {r.returncode} for a target that exited 7 — a gate routed through "
        f"it cannot block anything"
    )


def test_the_target_actually_runs_and_its_output_is_not_lost(tmp_path: Path) -> None:
    """A detached child's stdout raced the caller and arrived after it had moved on, so
    captured output was empty. Waiting for the child is what makes the output usable."""
    r = subprocess.run([sys.executable, str(WRAPPER), str(_target(tmp_path, 0))],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0
    assert "CHILD-RAN-0" in (r.stdout or ""), (
        "the target's output did not reach the caller — the wrapper did not wait for it"
    )
