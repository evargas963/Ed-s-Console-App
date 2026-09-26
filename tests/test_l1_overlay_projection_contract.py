"""
Issue 28 — Tier B overlay vs projection: explicit full_overlay contract (HTTP + SSE).

Proves: single server assembly (_l1_http_get_projection), no projection-only SSE path,
client does not re-document a conflicting mode.
"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_server_contract_constant_full_overlay():
    import server as srv

    assert getattr(srv, "L1_TIER_B_CHANNEL_PAYLOAD_MODE", None) == "full_overlay"








# test_index_html_declares_full_overlay_client_mode was retired here (/console cutover,
# operator directive 2026-09-14): it checked for a documentation marker + renderTierBLight in
# legacy static/index.html, neither of which exists in the new console (grepped, zero
# matches). The real contract this protected -- the server must never regress to ambiguous
# projection-only SSE -- is enforced server-side, unaffected by the rename, by
# test_not_projection_only_mode below.


