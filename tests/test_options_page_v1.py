"""OPTIONS_ORDER_FLOW_V1 — UI/consumer wiring: static/options.html contracts.

Binds the shipped surface to its real producers (GET /api/chain, GET /api/expiries, POST
/api/streaming/active-option-contract, GET /api/order-flow/options-microstructure) — no
client-side second producer, no fabricated endpoint, real nav wiring from every existing
tab.

Round-2 completeness/honesty repair (2026-08-30): the operator-facing expiry universe must
be reachable (not just the nearest expiry), and the scope/health labels must never present
a bounded or fallback state as if it were the same thing as a proven-complete live chain or
a fully-healthy upstream connection.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _src() -> str:
    return (REPO / "static" / "options.html").read_text(encoding="utf-8")


def test_page_exists_with_static_surfaces():
    src = _src()
    for vid in ("tk", "exp-select", "chain-tbl", "chain-body", "m-spot", "m-expiry",
               "m-count", "m-scope", "sel-symbol", "health-dot", "health-summary",
               "health-replay", "health-l1", "health-book", "depth-body", "theme-btn"):
        assert f'id="{vid}"' in src, f"#{vid} missing from static/options.html"


def test_reads_real_producers_only():
    src = _src()
    for ep in ("/api/chain", "/api/expiries", "/api/streaming/active-option-contract",
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


def test_expiry_universe_is_operator_accessible():
    """Round-2 requirement #5: the operator must be able to select among the ticker's
    actual available expirations, not just receive the default/nearest one silently."""
    src = _src()
    assert 'id="exp-select"' in src
    assert "loadExpiries" in src, "no function populates the expiry selector"
    assert "/api/expiries" in src
    # Selecting a different expiry must actually re-fetch the chain for it.
    assert "expSelect.addEventListener('change', loadChain)" in src
    # The chosen expiry must be sent to the chain API, not silently ignored.
    assert "expiry=" in src and "expSelect.value" in src


def test_stale_last_captured_expiry_claim_is_gone():
    """The old static claim ('chain scope: last-captured expiry only') described the
    PRIOR bounded-analytical-only design and is no longer true now that a live complete
    fetch is the primary path — it must not survive as a blanket, always-shown claim."""
    src = _src()
    assert "last-captured expiry only" not in src


def test_scope_honesty_all_four_tiers_are_distinctly_labeled():
    """Round-2 requirement: a response may be labeled complete only when completeness is
    actually established; every other tier must read as visibly different, never as if it
    were the same thing as a complete live chain."""
    src = _src()
    assert "complete_single_expiry" in src
    assert "expiry_scope_mismatch" in src
    assert "persisted_complete_capture_fallback" in src
    assert "stored_analytical_snapshot_fallback" in src
    # Each non-complete tier's rendered text must say so honestly (not proven complete /
    # a visible warning), not merely be distinguishable by an internal string match.
    assert "not proven complete" in src.lower() or "NOT proven complete" in src
    assert "complete chain" in src   # the ONE tier's positive label


def test_fail_closed_no_chain_state_is_labeled():
    src = _src()
    assert "no_chain" in src
    assert "No chain available" in src


def test_upstream_health_reads_the_real_per_service_fields():
    """Round-2 requirement #6: L1 and BOOK upstream health must be read and rendered as
    TWO SEPARATE fields, distinct from the local-replay proxy — never collapsed into one
    generic flag."""
    src = _src()
    for field in ("streaming_healthy", "streaming_connected", "daemon_upstream_health",
                 "LEVELONE_OPTIONS", "OPTIONS_BOOK"):
        assert field in src, f"page does not read the real diagnostics field {field}"
    assert "health-l1" in src and "health-book" in src and "health-replay" in src


def test_health_summary_never_reports_full_green_from_local_replay_alone():
    """NEGATIVE CONTROL (round-2 item #6): local replay healthy + upstream unknown/absent
    must not render the same summary text as all-three-healthy — read the actual
    renderHealth() branch structure to confirm the 'healthy' dot class is gated on ALL
    THREE dimensions agreeing, not just the local one."""
    src = _src()
    # The all-healthy branch must require localHealthy AND l1Healthy AND bookHealthy —
    # not localHealthy alone.
    assert "localHealthy && l1Healthy && bookHealthy" in src, (
        "the 'healthy' (green) state is not gated on all three health dimensions — a "
        "stale upstream service could render as if everything were fine")
    assert "haveUpstream" in src, (
        "no explicit branch for 'upstream health unknown' — local-only data must not "
        "silently masquerade as a fully-known-healthy state")
