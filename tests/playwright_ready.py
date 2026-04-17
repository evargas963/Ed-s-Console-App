"""
Fail-fast checks for Playwright / Node E2E tooling (Issue 40 & 46).

Used by tests/test_playwright_enforcement.py. Does not import Playwright-Python — validates
the same prerequisites as scripts/run-playwright-e2e.mjs (Node, npm, package install, CLI, browsers).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def ensure_playwright_ready(*, install_browsers: bool = True) -> None:
    """
    Verify Node, npm, local @playwright/test, CLI, and (by default) Chromium for Playwright.

    Raises:
        AssertionError: With an explicit fix hint — never returns silently on failure.
    """
    if not shutil.which("node"):
        raise AssertionError(
            "Playwright E2E requires Node.js on PATH. Install Node.js LTS from https://nodejs.org/ "
            "and ensure `node` is available in this shell."
        )
    if not shutil.which("npm"):
        raise AssertionError(
            "Playwright E2E requires npm on PATH. Install Node.js LTS (includes npm) or install npm."
        )
    pkg = ROOT / "package.json"
    if not pkg.is_file():
        raise AssertionError(f"package.json not found at {pkg} (wrong working directory?).")

    pw_pkg = ROOT / "node_modules" / "@playwright" / "test"
    if not pw_pkg.is_dir():
        raise AssertionError(
            "Playwright npm package is not installed. From the repo root run: npm install\n"
            "Then re-run: pytest tests/test_playwright_enforcement.py  or  npm run test:e2e"
        )

    r = subprocess.run(
        "npx playwright --version",
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        shell=True,
        timeout=120,
        env=os.environ.copy(),
    )
    if r.returncode != 0:
        raise AssertionError(
            "npx playwright --version failed.\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}\n"
            "Fix: run `npm install` in the repo root; ensure no broken node_modules."
        )

    if install_browsers:
        r2 = subprocess.run(
            "npx playwright install chromium",
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            shell=True,
            timeout=600,
        )
        if r2.returncode != 0:
            raise AssertionError(
                "playwright install chromium failed (browser binaries required for E2E).\n"
                f"stdout: {r2.stdout}\nstderr: {r2.stderr}\n"
                "Fix: check network/proxy; on Linux you may need system deps: "
                "npx playwright install-deps chromium"
            )


def main() -> None:
    """CLI: python -m tests.playwright_ready — exit 0 if ready, 1 with message to stderr."""
    try:
        ensure_playwright_ready()
    except AssertionError as e:
        print("PLAYWRIGHT NOT READY:", str(e), file=sys.stderr)
        sys.exit(1)
    print("Playwright environment OK (Node, npm, @playwright/test, chromium).")


if __name__ == "__main__":
    main()
