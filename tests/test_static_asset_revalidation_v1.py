"""Static assets must force browser revalidation (Cache-Control: no-cache), not rely on
heuristic caching. MEASURED (2026-09-11): a browser served a stale ed-gamma.js across
three full navigations after a real code change + server restart, with zero requests
reaching the server for that file -- a plain StaticFiles mount sends no Cache-Control at
all. ETag/Last-Modified still make an unchanged file a cheap 304 under no-cache; this
only removes the browser's ability to skip asking entirely."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_static_js_response_forces_revalidation():
    import server as srv
    from starlette.testclient import TestClient

    with TestClient(srv.app) as client:
        r = client.get("/static/js/ed-gamma.js")
        assert r.status_code == 200
        assert r.headers.get("cache-control") == "no-cache", (
            f"static assets must set Cache-Control: no-cache -- got {r.headers.get('cache-control')!r}"
        )
        # revalidation must still work (a cheap 304) -- not a regression to no-store
        etag = r.headers.get("etag")
        assert etag
        r2 = client.get("/static/js/ed-gamma.js", headers={"If-None-Match": etag})
        assert r2.status_code == 304


def test_static_css_response_also_forces_revalidation():
    import server as srv
    from starlette.testclient import TestClient

    with TestClient(srv.app) as client:
        r = client.get("/static/css/ed-tokens.css")
        assert r.status_code == 200
        assert r.headers.get("cache-control") == "no-cache"
