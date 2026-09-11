"""
Issue 40 & 46 — Playwright environment is enforced (fail-fast), not silently skipped.

- ensure_playwright_ready() must pass before any Playwright E2E is considered valid.
- Real browser + app tests live under tests/e2e/*.spec.js and run via: npm run test:e2e
"""
from __future__ import annotations

import shutil
from unittest.mock import patch

import pytest

from tests.playwright_ready import ROOT, ensure_playwright_ready


def test_ensure_playwright_ready_passes_when_configured():
    """Fails loudly with AssertionError if Node/npm/Playwright CLI are missing — never skips.

    Browser binaries are enforced by `npm run test:e2e` (install chromium + run tests). This test
    uses install_browsers=False so the full Python suite stays fast; run `python tests/playwright_ready.py`
    for a full check including chromium install.
    """
    assert ensure_playwright_ready(install_browsers=False) is None


def test_ensure_playwright_ready_raises_when_node_missing():
    """Regression: missing node must raise AssertionError, not return or skip."""

    def _which(name: str):
        if name == "node":
            return None
        return shutil.which(name)

    with patch("tests.playwright_ready.shutil.which", side_effect=_which):
        with pytest.raises(AssertionError, match="Node"):
            ensure_playwright_ready(install_browsers=False)


def test_e2e_smoke_spec_present():
    """Contract: browser smoke test file must exist (executed by npm run test:e2e, not pytest)."""
    smoke = ROOT / "tests" / "e2e" / "smoke.spec.js"
    assert smoke.is_file(), f"Missing {smoke} — add Playwright smoke test for real browser check."


def test_playwright_config_exists():
    p = ROOT / "playwright.config.mjs"
    assert p.is_file(), "playwright.config.mjs missing — E2E cannot run."


def test_playwright_server_uses_run_private_runtime() -> None:
    """The E2E server runs in a run-private runtime root and never touches the production DB.

    Lived in tests/test_playwright_must_run.py beside the `.playwright_last_run_success`
    marker tests until RC-542 (UNIVERSAL_QUANTITATIVE_CLOSURE_V1): a tracked, hand-editable
    stamp compared to spec mtimes proved a file, not a run, and required CI runs E2E directly.
    The isolation contract guards a real boundary and survives here; the runner writes no marker."""
    runner = (ROOT / "scripts" / "run-playwright-e2e.mjs").read_text(encoding="utf-8")
    config = (ROOT / "playwright.config.mjs").read_text(encoding="utf-8")
    assert 'fs.mkdtempSync(path.join(os.tmpdir(), "ed-console-e2e-"))' in runner
    assert "ED_RUNTIME_ROOT: e2eRuntime" in runner
    assert "ED_ARTIFACTS_ROOT: e2eRuntime" in runner
    assert "fs.rmSync(e2eRuntime, { recursive: true, force: true })" in runner
    assert "reuseExistingServer: false" in config
    assert "fs.writeFileSync(\n    markerPath" not in runner
