"""The tests run on the packages the app runs on.

2026-10-01: `npm run test:all` started `python` from PATH, the computer's system Python 3.13,
whose schwab-py has another layout than the project's .venv: the suite tested packages the
console and the capture daemon never load. Where the project has a .venv (a checkout on the
operator's computer), the tests run on it; CI has none and installs the requirements.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_the_tests_run_on_the_projects_venv_when_it_has_one():
    venv = REPO / ".venv"
    if venv.exists():
        assert Path(sys.prefix).resolve() == venv.resolve(), (
            f"tests ran on {sys.prefix}, not the project's .venv ({venv})")
