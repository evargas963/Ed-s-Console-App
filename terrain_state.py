"""Shared terrain state: the wide-chain terrain cache and its lock, the producer's per-ticker
failure channel, the loop's cadence floor / worker count, and the delivered-cycle clock the
loop publishes. A LEAF module (imports nothing from the loop or the producer) so the producer
(terrain_refresh), the freshness authority (terrain_freshness), the scheduler
(terrain_schedule) and the loop (terrain_loop) can all import it at module level without a
cycle. Extracted from server.py (RC-REHAB-1, 2026-09-23, forty-fourth slice).
`_terrain_last_cycle_sec` is REBOUND by terrain_loop; read it as `terrain_state.<name>`.
"""
from __future__ import annotations

import threading


# ── TERRAIN COLLECTION LOOP ──────────────────────────────────────────────────
# 5-whys root cause (2026-07-19): 24 of 31 tickers refreshed only every ~11 minutes
# because `_live_operator_mode_active()` HARD-SKIPS non-SPY/QQQ/IWM background rotation
# whenever a viewer is connected -- a gate that exists because `_fetch_state` runs the
# full model stack and would otherwise compete with the live UI.
#
# Terrain does not run the model stack. Measured: ~5 ms of math per ticker plus one chain
# call each.
#
# RC-570 (2026-09-21, operator directive): the prior 60.0 was throttled against a "~120
# req/min Schwab budget" this comment cited without distinguishing WHICH Schwab budget --
# the operator's explicit correction: that ceiling governs trade/order (two-way) execution
# calls, not read-only market-data polling, and this loop has never placed a trade. Holding
# a live market-data UI to a trading rate limit was the wrong model, not a real constraint.
# Lowered to run the loop back-to-back with only a minimal floor -- ACTUAL fetch latency
# (network + vendor response time), not an artificial policy pause, is now what paces this
# loop. If Schwab's real market-data limit turns out to be lower than assumed here, that
# will surface as observable 429/502s on THIS loop's own chain calls (see
# _persist_universal_complete_chain/_gated_safe_get_chain's existing status handling) --
# a measured fact to revisit, not a reason to keep guessing conservatively today.
TERRAIN_REFRESH_SEC: float = 5.0

# Match the 2-slot Schwab chain gate. 4 workers × 200-strike payloads queued ~51 tickers
# and starved the operator card (gate timeouts, Tier-C partial/STALE) at the open.
TERRAIN_WORKERS: int = 2

_terrain_cache: dict[str, dict] = {}

_terrain_cache_lock = threading.Lock()

#: RC-126: the producer's last failure per ticker, so terrain_not_ready can say WHY instead
#: of shrugging forever (how $SPX stayed dark a full session). Cleared on the next success.
_terrain_refresh_last_error: dict[str, str] = {}

#: RC-165: the DELIVERED cycle time, published by `_terrain_loop` from the duration it already
#: measures. `TERRAIN_REFRESH_SEC` is a sleep FLOOR, not a promise — a full sweep over ~40
#: tickers on 2 workers against a 2-slot chain gate costs more than that, and judging freshness
#: against the floor reports healthy tickers as broken. 0.0 until the first cycle completes, in
#: which case readers fall back to the nominal floor.
_terrain_last_cycle_sec: float = 0.0
