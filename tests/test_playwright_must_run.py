"""
Issue 40/46 — full pytest cannot pass unless Playwright E2E has succeeded (marker file).

Run `make test-all` (E2E first, then pytest) or `npm run test:e2e` before `python -m pytest`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MARKER = ROOT / ".playwright_last_run_success"


def _parse_iso_utc(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def test_playwright_was_executed():
    assert MARKER.is_file(), (
        "Playwright E2E has not completed successfully since the last clean checkout. "
        "Pytest alone is not sufficient. Run: make test-all   (or: npm run test:e2e && python -m pytest)"
    )
    raw = MARKER.read_text(encoding="utf-8").strip()
    assert raw, f"{MARKER} is empty — re-run: npm run test:e2e"
    data = json.loads(raw)
    assert data.get("ok") is True, f"{MARKER} missing ok:true — re-run: npm run test:e2e"
    assert "finishedAt" in data, f"{MARKER} missing finishedAt — re-run: npm run test:e2e"
    _parse_iso_utc(str(data["finishedAt"]))  # valid ISO timestamp


def test_playwright_marker_newer_than_e2e_sources():
    """Fail if E2E specs changed after the last successful Playwright run (stale marker)."""
    if not MARKER.is_file():
        pytest.fail("Missing .playwright_last_run_success - run make test-all")
    data = json.loads(MARKER.read_text(encoding="utf-8"))
    finished = _parse_iso_utc(str(data["finishedAt"]))
    finished_ts = finished.timestamp()

    e2e_dir = ROOT / "tests" / "e2e"
    newest = 0.0
    for pat in ("*.js", "*.mjs", "*.ts"):
        for p in e2e_dir.glob(pat):
            if p.is_file():
                newest = max(newest, p.stat().st_mtime)
    for p in (ROOT / "playwright.config.mjs", ROOT / "scripts" / "run-playwright-e2e.mjs"):
        if p.is_file():
            newest = max(newest, p.stat().st_mtime)

    assert newest <= finished_ts + 1.0, (
        "Playwright E2E sources or config are newer than the last successful E2E run. "
        f"last_run_utc={data.get('finishedAt')!r}. Re-run: make test-all"
    )
