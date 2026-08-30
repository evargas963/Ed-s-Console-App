"""OPTIONS_ORDER_FLOW_V1 — UI/consumer wiring: static/options.html contracts.

Binds the shipped surface to its real producers (GET /api/chain, POST /api/streaming/
active-option-contract, GET /api/order-flow/options-microstructure) — no client-side
second producer, no fabricated endpoint, real nav wiring from every existing tab.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _src() -> str:
    return (REPO / "static" / "options.html").read_text(encoding="utf-8")


def test_page_exists_with_static_surfaces():
    src = _src()
    for vid in ("tk", "chain-tbl", "chain-body", "m-spot", "m-expiry", "m-count",
                "sel-symbol", "health-dot", "health-label", "depth-body", "theme-btn"):
        assert f'id="{vid}"' in src, f"#{vid} missing from static/options.html"


def test_reads_real_producers_only():
    src = _src()
    for ep in ("/api/chain", "/api/streaming/active-option-contract",
               "/api/order-flow/options-microstructure"):
        assert ep in src, f"page does not read/call {ep}"


def test_server_route_serves_the_page():
    ssrc = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    assert '"/options"' in ssrc and "options.html" in ssrc, "no /options route"


def test_every_existing_nav_links_the_new_tab():
    for rel in ("static/index.html", "static/chart.html", "static/exposure.html",
                "static/options.html"):
        src = (REPO / rel).read_text(encoding="utf-8")
        assert 'href="/options"' in src or 'aria-selected="true">Options' in src, (
            f"{rel} nav does not link/mark the Options tab")


def test_no_client_side_book_imbalance_math():
    """order_flow_engine.compute_book_microstructure is the ONE producer of depth/imbalance/
    microprice — this page must only DISPLAY those served fields, never recompute them."""
    src = _src()
    for banned in ("bidSize", "askSize", "function imbalance", "function microprice",
                   "bid_total / (bid_total"):
        assert banned not in src, f"page appears to recompute book math client-side: {banned!r}"
    assert "d.imbalance" in src, "page does not read the served imbalance field"
    assert "m.microprice" in src, "page does not read the served microprice field"


def test_chain_scope_limitation_stated_honestly():
    """The stored chain is one-expiry-at-a-time (server.py:get_chain docstring) — the UI
    must say so, not imply a live multi-expiry picker that does not exist."""
    src = _src()
    assert "last-captured expiry only" in src


def test_fail_closed_no_chain_state_is_labeled():
    src = _src()
    assert "no_chain" in src
    assert "No chain captured yet" in src


def test_streaming_health_reads_the_real_diagnostics_fields():
    src = _src()
    for field in ("streaming_healthy", "streaming_staleness_ms", "streaming_connected"):
        assert field in src, f"page does not read the real diagnostics field {field}"
