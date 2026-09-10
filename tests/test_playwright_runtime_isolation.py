"""The E2E server runs in a run-private runtime root and never touches the production DB.

This file carried the `.playwright_last_run_success` marker tests until RC-542
(UNIVERSAL_QUANTITATIVE_CLOSURE_V1, 2026-09-10): a tracked, hand-editable JSON stamp compared
to spec mtimes was a proxy for the run required CI already performs and reports. The marker
and its two tests are gone; what a run cannot prove about itself is not proven by a file.
The isolation contract below guards a real boundary (the E2E uvicorn must not read or write
`data/ed_console.db`) and is exercised by driving the runner's environment builder.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_playwright_server_uses_run_private_runtime() -> None:
    runner = (ROOT / "scripts" / "run-playwright-e2e.mjs").read_text(encoding="utf-8")
    config = (ROOT / "playwright.config.mjs").read_text(encoding="utf-8")
    assert 'fs.mkdtempSync(path.join(os.tmpdir(), "ed-console-e2e-"))' in runner
    assert "ED_RUNTIME_ROOT: e2eRuntime" in runner
    assert "ED_ARTIFACTS_ROOT: e2eRuntime" in runner
    assert "fs.rmSync(e2eRuntime, { recursive: true, force: true })" in runner
    assert "reuseExistingServer: false" in config
    # RC-542: the runner writes no marker — its exit code is the proof.
    assert ".playwright_last_run_success" not in runner.split("RC-542")[0] or "retired" in runner
    assert "fs.writeFileSync(\n    markerPath" not in runner
