"""Static page-shell routes (root, guides, and the chart/exposure/options/desk tab shells).

RC-REHAB-1 (Phase 3): second extraction slice out of server.py's monolithic route table,
following the same pattern as app/api/routes/desk.py (see that module's docstring for the
full rationale). Every handler here does the same thing: read a static file (HTML or a repo
markdown doc rendered into a tiny HTML wrapper) and return it. None of them touch
server.py's shared mutable state (`_state_cache`, `_terrain_cache`, `_analytics_inflight`,
the candle accumulators, the executor pools) or call into any business logic at all.

`APP_DIR`/`static_dir` (the only things these handlers need from server.py) are imported
lazily inside the function bodies, matching the pre-existing local-import convention already
used in this codebase, so this module has zero module-level dependency back on `server` and
can be imported BY it (`app.include_router(...)`) without a circular import.
"""
from __future__ import annotations

import html
from pathlib import Path

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

router = APIRouter()


def _render_markdown_guide(filename: str, title: str, nav_links: str) -> HTMLResponse:
    """Shared shell for the three /guide/* routes below -- same doc-in-a-<pre> rendering,
    same nav, same escaping. Extracted here (it wasn't a shared function in server.py, three
    near-identical page bodies were) since a real second copy in this new module would be
    exactly the duplicate-authority pattern this whole rehab exists to eliminate, not
    something worth reproducing just to keep this extraction a literal cut-and-paste."""
    from server import APP_DIR

    md_path = Path(APP_DIR) / filename
    if not md_path.exists():
        return HTMLResponse(f"<p>{filename} not found in app directory.</p>", status_code=404)
    body = html.escape(md_path.read_text(encoding="utf-8"))
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — Ed Console</title>
  <style>
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #0a0c0f; color: #e5e7eb;
            margin: 0; padding: 24px; line-height: 1.55; font-size: 14px; }}
    .wrap {{ max-width: 52rem; margin: 0 auto; }}
    a {{ color: #60a5fa; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    pre {{ white-space: pre-wrap; word-break: break-word; font-size: 13px;
           background: #111418; border: 1px solid #252c36; padding: 16px; border-radius: 8px; }}
    .nav {{ margin-bottom: 20px; font-size: 13px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="nav">{nav_links}</div>
    <pre>{body}</pre>
  </div>
</body>
</html>"""
    return HTMLResponse(page)


@router.get("/", response_class=HTMLResponse)  # caps-ok: FastAPI route decorator (path, response_class=...), not a dict.get(key, default) read
def root():
    from server import static_dir

    html_path = static_dir / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>static/index.html not found</h1>", status_code=404)
    # Avoid stale shell JS after edits (browser disk cache of "/" was masking localForce→force fix).
    return HTMLResponse(
        content=html_path.read_text(encoding="utf-8"),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


@router.get("/favicon.ico", include_in_schema=False)  # caps-ok: FastAPI route decorator kwarg, not a dict.get(key, default) read
def favicon():
    """Browsers request this automatically; without a route they log 404 (harmless but noisy)."""
    return Response(status_code=204)


@router.get("/guide/data-stewardship", response_class=HTMLResponse)  # caps-ok: FastAPI route decorator, not a dict.get(key, default) read
def guide_data_stewardship():
    """Serve DATA_STEWARDSHIP.md in the browser (king / jewels / guards + runbook)."""
    return _render_markdown_guide(
        "DATA_STEWARDSHIP.md", "Data stewardship &amp; ops",
        '<a href="/">&larr; Back to console</a>',
    )


@router.get("/guide/training-and-maintenance", response_class=HTMLResponse)  # caps-ok: FastAPI route decorator, not a dict.get(key, default) read
def guide_training_and_maintenance():
    return _render_markdown_guide(
        "TRAINING_AND_MAINTENANCE.md", "Training &amp; maintenance",
        '<a href="/">&larr; Back to console</a>'
        ' · <a href="/guide/data-stewardship">Data stewardship</a>'
        ' · <a href="/guide/pipeline-quality">Pipeline quality (TQM)</a>'
        ' · <a href="/ops">Run tasks</a>',
    )


@router.get("/guide/pipeline-quality", response_class=HTMLResponse)  # caps-ok: FastAPI route decorator, not a dict.get(key, default) read
def guide_pipeline_quality():
    """TQM-style checkpoints: ingest throttles, audits, normalized layer, readiness."""
    return _render_markdown_guide(
        "PIPELINE_QUALITY.md", "Pipeline quality (TQM)",
        '<a href="/">&larr; Back to console</a>'
        ' · <a href="/guide/data-stewardship">Data stewardship</a>'
        ' · <a href="/guide/training-and-maintenance">Training &amp; maintenance</a>'
        ' · <a href="/ops">Run tasks</a>',
    )


@router.get("/chart", response_class=HTMLResponse)  # caps-ok: FastAPI route decorator, not a dict.get(key, default) read
def chart_page():
    """CR-03 screen-1 v0 — chart-first view (candles + terrain bands + coach)."""
    from server import static_dir

    p = static_dir / "chart.html"
    if not p.exists():
        return HTMLResponse("<p>static/chart.html not found</p>", status_code=404)
    return HTMLResponse(p.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


@router.get("/exposure", response_class=HTMLResponse)  # caps-ok: FastAPI route decorator, not a dict.get(key, default) read
def exposure_page():
    """RC-200 (re-landed with RC-210) — the Exposure Overlay tab: dealer positioning on
    price (operator #1 project, LIVE order 2026-08-02)."""
    from server import static_dir

    p = static_dir / "exposure.html"
    if not p.exists():
        return HTMLResponse("<p>static/exposure.html not found</p>", status_code=404)
    return HTMLResponse(p.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


@router.get("/options", response_class=HTMLResponse)  # caps-ok: FastAPI route decorator, not a dict.get(key, default) read
def options_page():
    """OPTIONS_ORDER_FLOW_V1 UI/consumer wiring: chain + contract-selection + live
    order-flow microstructure for one option contract. Reads GET /api/chain (contract
    listing), POST /api/streaming/active-option-contract (subscribe), GET /api/order-flow/
    options-microstructure (live book + freshness/health) — no new endpoints, no client-
    side second producer."""
    from server import static_dir

    p = static_dir / "options.html"
    if not p.exists():
        return HTMLResponse("<p>static/options.html not found</p>", status_code=404)
    return HTMLResponse(p.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


@router.get("/desk", response_class=HTMLResponse)  # caps-ok: FastAPI route decorator, not a dict.get(key, default) read
def desk_page():
    """Desk — research, candidates and book, replayable at an earlier knowledge time."""
    from server import static_dir

    p = static_dir / "desk.html"
    if not p.exists():
        return HTMLResponse("<p>static/desk.html not found</p>", status_code=404)
    return HTMLResponse(p.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate"})
