"""
L1 remediation — explicit-expiry L2 scope, l1_stale truth, persisted snapshots, instrumentation, hooks.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def l1_clean_spy(monkeypatch):
    """Isolate SPY rows in server caches for this test."""
    import server as srv

    keys = [k for k in list(srv._state_cache.keys()) if isinstance(k, tuple) and k and k[0] == "SPY"]
    backup = {k: srv._state_cache[k] for k in keys}
    for k in keys:
        srv._state_cache.pop(k, None)
    for k in list(srv._l1_snapshot_cache.keys()):
        if k[0] == "SPY":
            srv._l1_snapshot_cache.pop(k, None)
    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {"spot": 500.0, "bid": 499.0, "ask": 501.0},
    )
    monkeypatch.setattr(srv, "_l2_refresh_in_progress_for_l1", lambda *a, **k: False)
    monkeypatch.setattr(srv._lmp, "apply_l1_live_quote_overlay", lambda *a, **k: None)
    yield srv
    for k in list(srv._state_cache.keys()):
        if isinstance(k, tuple) and k and k[0] == "SPY":
            srv._state_cache.pop(k, None)
    srv._state_cache.update(backup)






























def test_index_html_l1_scope_and_generation_guards():
    """TEST_SYSTEM_REHAB_V2_RESIDUAL_CLOSURE (weak-assertion item 4 of the 17-20 block):
    the last assertion was `"REJECTED stale l1_generation" in html or "stale
    l1_generation" in html` -- degenerate three ways.

      (1) "stale l1_generation" is a PROPER SUBSTRING of "REJECTED stale
          l1_generation", so A implies B and `A or B` is exactly B. The left branch
          could never rescue the right one; it contributed zero power.
      (2) It was already subsumed by the `"l1_generation" in html` line above it.
      (3) Worst: the text it matched is a DIAG-gated console.warn with zero
          production behavior -- ANTI-CORRELATED with the defect. Delete the real
          guard condition but leave the log line and it passed while stale-frame
          flicker shipped; reword the log and it failed with no defect at all.

    The real guard is the monotonic-generation call itself. Asserted structurally
    here; the BEHAVIOR of l1ApplyTierBLightMonotonic (5->7 accept, 7->6 reject,
    same-gen older serverTs reject) is executed against the real shipped JS by
    tests/l1_sse_guards_node.mjs, which stays the authority for it.

    Instant-UI Phase 2 (2026-09-24): the header paints from the plane row, not from
    l1_projection. Stage 1 of the live-UI architecture: that row comes from the capture
    daemon's socket; the console's analytics stream paints no price at all, so a late L1
    frame cannot overwrite the price."""
    core = (ROOT / "static" / "js" / "ed-core.js").read_text(encoding="utf-8")
    assert "msg.rows.forEach(ingestPriceRow)" in core
    assert "addEventListener('l1_quote'" not in core
    assert "addEventListener('quote_tick'" not in core
    analytics = core.split("function openAnalyticsStream(")[1].split("\n  }\n")[0]
    assert "paintQuote" not in analytics


# test_index_html_l1_quote_vs_of_freshness_ui was retired here (/console cutover, operator
# directive 2026-09-14): the dual quote-vs-order-flow freshness chip pair
# (b-l1-label-quote/of, b-l1-dot-quote/of, l1QuoteFreshTier/l1OfFreshTier,
# l1ShouldPaintFreshness/_l1FreshnessPaint) has no equivalent anywhere in the new console
# (grepped static/js/*.js and static/console.html, zero matches). Flagged for the operator as
# a discovered, not-fixed gap; building a replacement chip pair is out of scope for this
# cutover.


# DELETED: test_client_l1_generation_guard_logic_mirror. It defined its own Python
# `accept(prev, g)` and asserted against THAT COPY, never against the shipped client
# rule -- the same "test the re-implementation, not the implementation" defect class
# tests/test_l1_cold_start_transition.py documents as already fixed elsewhere. Its
# three cases (5->3 reject, 5->6 accept, None->1 accept) are strictly subsumed by
# tests/l1_sse_guards_node.mjs, which executes the REAL
# static/js/l1_sse_guards.js::l1ApplyTierBLightMonotonic over 5->7 accept, 7->6
# reject, stale-HTTP-after-newer-SSE reject, same-generation-older-_server_build_ts
# reject, and same/newer-timestamp accept. Deleting the mirror removes no material
# defect detection; not replaced.
