"""T5 — SSE emission must not starve behind slow _fetch_state / DB lock contention."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _seed_spy_cache(srv, *, gen_id: int = 100) -> tuple:
    ticker, expiry = "SPY", "2099-01-01"
    ck = (ticker, expiry)
    now = time.time()
    srv._state_cache[ck] = {
        "ts": now,
        "generated_at": now,
        "analytics_version": 1,
        "ms_dict": {
            "ticker": ticker,
            "selected_exp": expiry,
            "mhap_rows": [{"horizon": "5c", "call": "WAIT", "confidence": 0.5}],
            "decision_generation_id": gen_id,
            "_server_build_ts": now,
        },
    }
    return ticker, expiry, ck


@pytest.fixture
def srv_module():
    import server as srv

    srv._startup_analytics_executor()
    srv._analytics_bg_shutdown = False
    srv._analytics_inflight.clear()
    srv._analytics_bg_fail_counts.clear()
    srv._analytics_bg_last_error.clear()
    yield srv
    srv._analytics_inflight.clear()












def test_step2_tick_coherent_callback_not_registered_in_lifespan():
    """Single Tier C owner: lifespan must not wire _on_tick_broadcast_sync into the stream."""
    src = (ROOT / "server.py").read_text(encoding="utf-8", errors="replace")
    assert "on_tick_callback=on_tick" not in src
    assert "on_tick = lambda" not in src
    # The unwired callback was deleted as dead code (tick logic stays unit-tested in
    # live_decision_bundle); it must not come back as a second Tier C owner.
    assert "def _on_tick_broadcast_sync" not in src










