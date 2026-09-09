"""RC-UI-1 — run Node assertions for the Options/Gamma heatmap presentation helpers
(static/js/ed-gamma.js), and confirm the canonical surface route is registered."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_ed_gamma_node_script():
    node = shutil.which("node")
    if not node:
        pytest.fail(
            "Node.js is required on PATH for this test (runs tests/ed_gamma_node.mjs). "
            "Install Node.js LTS — same prerequisite as Playwright E2E (see docs/playwright.md)."
        )
    script = ROOT / "tests" / "ed_gamma_node.mjs"
    r = subprocess.run(
        [node, str(script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + "\n" + r.stderr


def test_gamma_surface_route_registered():
    import server as srv

    paths = [getattr(route, "path", "") for route in srv.app.routes if hasattr(route, "path")]
    assert "/api/options/gamma-surface" in paths
    assert "/console" in paths
