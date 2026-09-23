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
    from starlette.testclient import TestClient

    # RC-REHAB-1 (Phase 3, fifth extraction slice): /api/options/gamma-surface moved into
    # app/api/routes/options.py, mounted via app.include_router(options_router). Same
    # _IncludedRouter blind spot as the `/` check below (this FastAPI version gives an
    # included router's routes no `.path` attribute on app.routes) -- a live request is what
    # this assertion actually needs to prove, not a specific app.routes representation detail.
    r = TestClient(srv.app).get("/api/options/gamma-surface?ticker=SPY")
    assert r.status_code == 200 and r.json().get("ticker") == "SPY"

    # /console converged into `/` here (/console cutover, operator directive 2026-09-14) --
    # the dev route is gone, not aliased; the new console is served at `/` (see root()).
    #
    # RC-REHAB-1 (Phase 3): `/` moved into app/api/routes/pages.py, mounted via
    # app.include_router(pages_router). This FastAPI version does not flatten an included
    # router's routes into plain Route objects on app.routes -- it wraps them in a
    # fastapi.routing._IncludedRouter with no `.path` attribute -- so the naive `"/" in
    # paths` check above can no longer see it (true for EVERY included router, including
    # options_order_flow_router and desk_router mounted before this route moved; nothing
    # previously checked one of their routes this same way). A live request is what this
    # assertion actually needs to prove -- "the console is served at /", not "/ appears in
    # a specific internal list shape" -- so it now asks the app directly instead of
    # depending on an app.routes representation detail.
    r = TestClient(srv.app).get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
