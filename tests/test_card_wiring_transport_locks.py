"""Regression locks for the card-wiring transport fixes (commit 3a0d338).

Defect classes locked (runtime-proven in the 2026-07-04 pre-RTH audit):
  1. Analytics-pool self-deadlock — _fetch_state ran its chain/quote futures on the
     same 4-worker analytics executor that runs _fetch_state itself; >=3 concurrent
     Tier C jobs parked every worker at .result() forever (py-spy proof).
  2. Expiry carryover on ticker switch (client) — source lock here; the e2e behavioral
     companion (tests/e2e/ticker-switch-expiry-reset.spec.js) was retired 2026-09-15
     (tested window.*/DOM ids absent from the current static/index.html — see the note
     at Locks 2+3 below).
  3. Ordering-cursor scope (client) — gen-less quote/shell payloads must not advance
     the money-path ordering cursor; its own behavioral lock was retired alongside the
     same e2e spec (see the note at Locks 2+3 below).
  4. SSE completed-fetch mirror parity — payloads broadcast after a completed
     _fetch_state must carry card_freshness_v1 + operator_card_* mirrors, matching
     REST and SSE cache-fanout.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_SRC = (ROOT / "server.py").read_text(encoding="utf-8")
SERVER_TREE = ast.parse(SERVER_SRC)


def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _called_names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


# ── Lock 1 — analytics-pool self-deadlock ────────────────────────────────────




# ── Lane-3 lock — compute-stage instrumentation must stay stamped ────────────




# ── Lane-4 lock — bars persistence must stay off the synchronous hot path ───






# ── Burndown lock — same-tick similarity dedup must stay wired ──────────────

SIGNALS_SRC = (ROOT / "signals.py").read_text(encoding="utf-8")
SIGNALS_TREE = ast.parse(SIGNALS_SRC)






# ── Burndown lock — IV history must stay a narrow projection ────────────────










# ── Audit lock — snapshot minute gate must reserve atomically + durably ─────








# ── Audit lock — accuracy must be computed for the SERVING model version ────




# ── Lock 4 — SSE completed-fetch mirror parity ──────────────────────────────






# ── Locks 2 + 3 — client source guards ────────────────────────────────────
# The behavioral companion (tests/e2e/ticker-switch-expiry-reset.spec.js) was itself
# retired 2026-09-15: every window.*/DOM id it exercised (__edTestHooks, #cv2-hd-ticker,
# window.setActiveTicker, _edMplMonotonicGateReset, acceptMoneyPathPayload) was verified
# absent from the current static/index.html (direct read + git HEAD, not assumed from a
# prior triage's own notes) -- the whole file tested a page structure that no longer
# exists. The ticker-switch/expiry-reset invariant itself stays covered below, against
# the CURRENT ed-core.js.


# test_client_ordering_cursor_commits_gen_bearing_only and
# test_client_render_updates_module_level_render_source_diag were retired here (/console
# cutover, operator directive 2026-09-14): both locked legacy static/index.html's
# _edMplMonotonicGateRecordAccept ordering cursor / _lastFullRenderSource render-source
# diagnostic, neither of which exists in the new console's simpler poll model (grepped
# static/js/*.js, zero matches for either name).


def test_client_ticker_switch_resets_expiry_scope() -> None:
    """The real invariant this protected -- a ticker switch must not carry the prior ticker's
    expiry scope into the new ticker's requests (AAPL wedge, audit 2026-07-04) -- has a live
    equivalent: ed-core.js's setTicker() clears the shared selection and reloads expiries fresh
    for the new ticker on every switch, so there is no stale-select DOM to carry over at all."""
    core = (ROOT / "static" / "js" / "ed-core.js").read_text(encoding="utf-8")
    marker = "function setTicker(sym) {"
    assert marker in core, "setTicker not found in ed-core.js"
    body = core[core.index(marker) : core.index(marker) + 2200]
    assert "state.selStrike = null; state.selExpiry = null;" in body, (
        "ticker switch no longer resets the shared strike/expiry selection — the prior "
        "ticker's scope can carry into the new ticker's requests (AAPL wedge, audit "
        "2026-07-04)."
    )
    assert "loadExpiries(state.ticker);" in body, (
        "ticker switch no longer reloads expiries for the new ticker"
    )
    assert body.index("state.selStrike = null; state.selExpiry = null;") < body.index(
        "loadExpiries(state.ticker);"
    ), "selection reset happens after (not before) the new ticker's expiry reload"
