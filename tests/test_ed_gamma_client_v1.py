"""RC-UI-1 — run Node assertions for the Options/Gamma heatmap presentation helpers.

The helpers are static/js/ed-gamma.js; also confirm the surface is the page socket's panel.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import server as srv
from app.market_data.schwab.streaming.live_ui import Asked

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


def test_gamma_surface_is_the_sockets_panel_and_no_route():
    paths = [getattr(route, "path", "") for route in srv.app.routes if hasattr(route, "path")]
    assert "/api/options/gamma-surface" not in paths
    asked = Asked("ZZNOSURFACE", 0.0, {"scope": "auto", "centre": None, "shift": 0})
    assert srv.PAGE_PANELS["surface"](asked) == srv.gamma_surface(
        asked.ticker, asked.now, asked.params
    )
    # /console converged into `/` here (/console cutover, operator directive 2026-09-14) --
    # the dev route is gone, not aliased; the new console is served at `/` (see root()).
    assert "/" in paths
