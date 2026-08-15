"""Run Node assertions for client L1 SSE guard helpers (static/js/l1_sse_guards.js)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_l1_sse_guards_node_script():
    node = shutil.which("node")
    if not node:
        pytest.fail(
            "Node.js is required on PATH for this test (runs tests/l1_sse_guards_node.mjs). "
            "Install Node.js LTS — same prerequisite as Playwright E2E (see docs/playwright.md)."
        )
    script = ROOT / "tests" / "l1_sse_guards_node.mjs"
    r = subprocess.run(
        [node, str(script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + "\n" + r.stderr


def test_l1_light_stream_still_registered():
    import server as srv

    paths = [getattr(route, "path", "") for route in srv.app.routes if hasattr(route, "path")]
    assert "/api/analytics/light/stream" in paths
