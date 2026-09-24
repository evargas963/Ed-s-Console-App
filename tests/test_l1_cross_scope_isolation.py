"""
Issue 51 — Tier B / L1 cross-scope isolation (ticker|expiry).

The scope-matching contract (normL1ExpiryKey, l1PayloadMatchesActiveScope) is proven
against the REAL shipped static/js/l1_sse_guards.js by tests/l1_sse_guards_node.mjs (run
via test_l1_sse_guards_client.py) — including wrong-ticker, wrong-expiry, pinned-expiry,
and auto-mode cases. A hand-copied Python mirror of those functions plus two tests that
exercised only bare Python dict semantics (no function call at all) used to live here and
were removed 2026-09-15: they proved nothing about the shipped client rule that the Node
harness doesn't already prove against the real code. What remains below are the two
source-level static invariants that have no Node-harness equivalent.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# --- Regression: no global Tier B gen in client source --------------------------------------


def test_no_global_l1_generation_mutable_in_ed_core():
    """Repointed to static/js/ed-core.js (/console cutover, operator directive 2026-09-14):
    the real invariant (no single global mutable generation counter shared across every
    ticker/scope) survives via ed-core.js's own scope-keyed dicts, just under different names
    than legacy's _l1GenByScope (_l1Gen/_l1Ts here, passed per-ticker into
    l1ApplyTierBLightMonotonic rather than suffixed -ByScope)."""
    text = (ROOT / "static" / "js" / "ed-core.js").read_text(encoding="utf-8")
    assert "_l1Gen = {}, _l1Ts = {}" in text
    assert "window._l1Gen =" not in text
    assert "window._l1Generation =" not in text


def test_authority_and_identity_stores_keyed_by_scope_in_source():
    """Header paint is quote_tick scoped to state.ticker. A tick for another symbol
    must not write #hPx. Watchlist rows key off the event ticker against loadWL()."""
    text = (ROOT / "static" / "js" / "ed-core.js").read_text(encoding="utf-8")
    assert "addEventListener('quote_tick'" in text
    # identity through the storage form: "$SPX" (server) and "SPX" (typed) are one symbol --
    # the raw compare never matched an index ticker (audit of #280)
    assert "bare === String(state.ticker || '').toUpperCase().replace(/^\\$/, '')" in text
    assert "loadWL().indexOf(sym)" in text
