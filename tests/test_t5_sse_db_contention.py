"""T5 — SSE emission must not starve behind slow _fetch_state / DB lock contention."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_step2_tick_coherent_callback_not_registered_in_lifespan():
    """Single Tier C owner: lifespan must not wire _on_tick_broadcast_sync into the stream."""
    src = (ROOT / "server.py").read_text(encoding="utf-8", errors="replace")
    assert "on_tick_callback=on_tick" not in src
    assert "on_tick = lambda" not in src
    # The unwired callback was deleted as dead code (tick logic stays unit-tested in
    # live_decision_bundle); it must not come back as a second Tier C owner.
    assert "def _on_tick_broadcast_sync" not in src
