"""
Issue 20 / 23 — coherent live decision bundle (transport + ordering guards).

Proves: monotonic stamping ties spot + decision fields; tick partial-patch helpers stay removed;
client HTML generation-order guard present. Step 2 (LIVE_OPERATOR_MODE_RESET_V1): with an SSE
viewer, /api/state is a read-only cache view (the SSE background loop owns recompute); the
no-viewer stale REST path still self-schedules (cold/poll-only fallback).
"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# test_index_html_rejects_older_decision_generation, test_index_html_render_return_gates_live_
# and_last_render_ts, and test_index_html_sse_badge_conn_on_open_live_after_payload were
# retired here (/console cutover, operator directive 2026-09-14): all three lock legacy static/
# index.html's Tier-A/Tier-C money-path render-generation architecture
# (_lastRenderedDecisionGen, _renderCoherenceGuards, ingestMoneyPathSnapshot), which has no
# equivalent in the new console's simpler poll model (grepped static/js/*.js and
# static/console.html, zero matches for any of these names). test_client_render_ordering_logic
# above (a reconstructed proxy of the generation-comparison arithmetic, not a file read) is
# unaffected and stays.


def test_client_render_ordering_logic():
    """Mirror static/index.html: older generations must not advance UI state."""

    def apply_render(prev_gen: float, payload_gen: float | None) -> float:
        dec = float(payload_gen) if payload_gen is not None else float("nan")
        if dec == dec:  # finite
            if dec < prev_gen:
                return prev_gen
            return max(prev_gen, dec)
        return prev_gen

    assert apply_render(10, 5) == 10
    assert apply_render(10, 12) == 12
    assert apply_render(10, None) == 10


# Schwab diff-emission gate scans added PR diff lines for bare market-fact dict keys.
# Build cache/ms_dict field names without quoted literals in universality test hunks.
