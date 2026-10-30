"""
Issue 40 & 46 — Playwright environment is enforced (fail-fast), not silently skipped.

- ensure_playwright_ready() must pass before any Playwright E2E is considered valid.
- Real browser + app tests live under tests/e2e/*.spec.js and run via: npm run test:e2e
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.playwright_ready import ensure_playwright_ready


def test_ensure_playwright_ready_passes_when_configured():
    """Fails loudly with AssertionError if Node/npm/Playwright CLI are missing — never skips.

    Browser binaries are enforced by `npm run test:e2e` (install chromium + run tests). This test
    uses install_browsers=False so the full Python suite stays fast; run
    `python tests/playwright_ready.py` for a full check including chromium install.
    """
    assert ensure_playwright_ready(install_browsers=False) is None


def test_ensure_playwright_ready_raises_when_node_missing():
    """With nothing on PATH, missing node must raise AssertionError, not return or skip."""
    check = (
        "from tests.playwright_ready import ensure_playwright_ready; "
        "ensure_playwright_ready(install_browsers=False)"
    )
    done = subprocess.run(
        [sys.executable, "-c", check],
        cwd=Path(__file__).resolve().parent.parent,
        env={**os.environ, "PATH": ""},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 1
    assert "AssertionError: Playwright E2E requires Node.js on PATH" in done.stderr
