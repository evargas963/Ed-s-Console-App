"""E2E must not write the live capture-adjacent option-contract signal.

The one signal file sits beside STREAM_CAPTURE_DB_PATH. Playwright inherits the
parent environment; if that env points at the production stream DB, E2E writes
the live owner's subscription (expired OSI / empty clear). Isolation is the
same resolver aimed at a disposable DB — not a second authority.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = "ed-console-e2e-stream-capture.db"


def test_playwright_webserver_overrides_stream_capture_db_path():
    text = (ROOT / "playwright.config.mjs").read_text(encoding="utf-8")
    assert "STREAM_CAPTURE_DB_PATH" in text
    assert PIN in text
    assert "reuseExistingServer: false" in text


def test_e2e_runner_overrides_stream_capture_db_path():
    text = (ROOT / "scripts" / "run-playwright-e2e.mjs").read_text(encoding="utf-8")
    assert "STREAM_CAPTURE_DB_PATH" in text
    assert PIN in text
