"""Terrain collection loop (RC-80 producer driver): the wide-chain terrain cache and its lock,
the per-ticker failure channel, the delivered-cycle clock, the cadence floor and worker count,
the background loop itself (rotation, deferral, contention guard), the boot prewarm and
strike-geometry seeding, and start/stop. Extracted from server.py (RC-REHAB-1, 2026-09-23,
forty-fourth slice). `_terrain_loop_running` / `_terrain_loop_thread` are REBOUND here; read them as `terrain_loop.<name>`, never copy.
Server-owned runtime (logger roster, quote memo, chain/spot reads, the Schwab client) is
read through a lazy `import server as _srv` at call time.
"""
from __future__ import annotations

import concurrent.futures
import logging
import os
import threading
import time

import gamma_surface_state as _gss
import terrain_quarantine as _tq
import terrain_state
from app.api.routes.terrain import get_terrain_radar

# Imported at MODULE LEVEL deliberately: the loop's morning-window guard depends on the
# clock and the contention constants, and a runtime import inside the loop meant a missing
# module silently removed the guard during the exact 30 minutes it protects. At top level,
# a broken module stops the server AT BOOT -- loud and impossible to trade through (Cursor
# audit 2026-07-20).
from calibration.option_chain_morning_full import et_date_and_mins as gex_et_date_and_mins
from chain_width import _learn_strike_geometry
from instrument_identity import ticker_storage_key
from terrain_freshness import terrain_staleness
import terrain_refresh  # the producer, called through its module so a test patches ONE home
from terrain_schedule import (
    ACCRUAL_MIN_INTERVAL_OTHER_SEC,
    TERRAIN_CONTENTION_END_MINS,
    TERRAIN_CONTENTION_START_MINS,
    terrain_cycle_tickers,
)

log = logging.getLogger(__name__)


_terrain_loop_running: bool = False


_terrain_loop_thread: threading.Thread | None = None


def terrain_cache_get(ticker: str) -> dict | None:
    """Return the cached wide-chain terrain snapshot with staleness merged.

    RC-424: the loop stores computed_ts_utc, not levels_stale. Every consumer that
    gates pin/wall/overlay freshness must derive staleness from terrain_staleness
    (the production authority), never treat a missing levels_stale key as fresh.
    """
    tk = ticker_storage_key(ticker)
    with terrain_state._terrain_cache_lock:
        raw = terrain_state._terrain_cache.get(tk)
    if raw is None:
        return None
    out = dict(raw)
    out.update(terrain_staleness(out.get("computed_ts_utc"), ticker))
    return out


def terrain_cache_size() -> int:
    with terrain_state._terrain_cache_lock:
        return len(terrain_state._terrain_cache)


def _ticker_on_terrain_board(tk: str) -> bool:
    import server as _srv

    # canonical current board membership (the terrain loop's universe = the logger cycle set +
    # core), read under the existing lock — NOT a new registry, and NOT merely "a snapshot exists".
    with _srv._logger_lock:
        return tk in _srv._logger_tickers or tk in _srv.CORE_TICKERS


def _terrain_loop() -> None:
    import server as _srv

    log.info("Terrain loop started (levels only, no model stack)")
    _terrain_cycle_n = 0        # RC-161: drives the morning rotation; monotonic per loop
    # Seed strike geometry BEFORE the first fetch cycle, in THIS thread. The seed
    # previously lived only in the prewarm worker, and _app_lifespan starts the loop
    # first -- so the first cycle raced the seed and could fetch every ticker at the
    # cold-start width (Cursor audit 2026-07-20: "race remains"). With the timeframe-
    # indexed read this is ~2 ms per ticker, so doing it inline is cheap and makes the
    # ordering deterministic instead of a race that usually goes our way.
    try:
        _seed_strike_geometry_from_storage()
    except Exception as e:
        log.warning("strike-geometry seed failed - first cycle uses cold-start width: %s", e)
    while _terrain_loop_running:
        cycle_start = time.monotonic()
        tickers: list[str] = []
        try:
            with _srv._logger_lock:
                tickers = list(_srv._logger_tickers)
        except Exception:
            tickers = list(_srv.CORE_TICKERS)
        # Independent-review finding (2026-09-12, state-authority review), REPRODUCED: a
        # ticker merely PREVIEWED (never enrolled onto _logger_tickers -- see
        # TICKER-PREVIEW-NO-ENROLL below) got exactly ONE on-demand terrain compute (the
        # /api/terrain cache-miss priority path) and then NOTHING -- this loop only ever
        # iterated the enrolled board, so its cache entry sat frozen forever while
        # /api/options/gamma-surface kept serving it "live: True" (meaning "sourced from
        # the live pathway", not "currently fresh") alongside a growing stale age with no
        # honest "never enrolled" reason surfaced. Any ticker with LIVE view demand
        # (gamma_surface_state._gamma_surface_wanted -- the SAME signal /api/options/gamma-surface already
        # records on every request) is folded into this cycle so viewing ANY supported
        # ticker keeps it refreshing for as long as it is actually being viewed, not only
        # the pre-enrolled board. A snapshot of the keys, never the live dict, since
        # another thread's concurrent _note_gamma_surface_demand write must not raise
        # "dictionary changed size during iteration" here.
        _viewed_now = [tk for tk in list(_gss._gamma_surface_demand.keys()) if _gss._gamma_surface_wanted(tk)]
        _previewed = [tk for tk in _viewed_now if tk not in tickers]
        # RC-146: a skip reason is only true for the cycle that recorded it. Cleared at the TOP
        # of every cycle so a pause that has ended cannot keep telling the operator to wait —
        # the branch below re-records it while, and only while, it still applies.
        _tq._clear_terrain_skips()
        # Operator-reproduced defect (2026-09-14, "the collection schedule must not block live
        # viewing"): this whole cycle used to be gated on _is_loggable_session() -- the
        # ARCHIVAL LOGGER's own RTH-only writing policy (RTH_ONLY, "only log during RTH + 30min
        # pre/post buffer") -- so a ticker someone had open and was actively looking at got NO
        # live refresh attempt at all outside that window, not even a try. "should the durable
        # log be written" and "should an operator who is looking at this ticker right now see
        # whatever is currently fetchable" are different questions; this loop answered both with
        # the same switch. The enrolled board's full sweep stays RTH-gated (unchanged -- nobody
        # is necessarily watching all 58 of them, and the morning-contention throttle below is
        # itself an RTH-only concept), but active viewing demand now always gets a live attempt,
        # whether the archival logger is in its window or not.
        if _srv._is_loggable_session():
            # During the morning wide-chain window (09:30-10:00 ET) SPY/QQQ/IWM already
            # take 100-strike gated fetches on the money path. Do not pile a full-universe
            # terrain sweep on top of that — refresh sentinels only until the window ends.
            # No try/except: the imports are module-level, so this path cannot fail at
            # runtime — a missing module stops the server at boot instead.
            _d, _mins = gex_et_date_and_mins()
            _terrain_cycle_n += 1
            _all_this_cycle = list(tickers)
            tickers, _dropped = terrain_cycle_tickers(_all_this_cycle, _mins, _terrain_cycle_n)
            if _dropped:
                # RC-146: SAY SO. This pause is deliberate and budget-justified, but it was a
                # silent list filter — nothing anywhere recorded that these tickers were skipped
                # on purpose. MEASURED 2026-07-30 09:43 ET: MSFT's per-strike panel served a
                # chain read at 09:29:52 (8 s before the bell, so session volume was 0 on all 44
                # strikes) under the message "no option volume yet this session", while
                # terrain_staleness could only offer "inside its window but not producing" — a
                # correct scheduler reported as a malfunction, and a pre-open corpse reported as
                # a market fact. The producer knows why it skipped; now the reader can ask.
                # RC-161: the wording follows the mechanism. This is no longer an exclusion for
                # the whole window — the ticker is DEFERRED to a later cycle inside it, and will
                # be refreshed within the accrual cadence rather than held until 10:00.
                _tq._note_terrain_skip(
                    _dropped,
                    f"deferred to a later cycle inside the "
                    f"{TERRAIN_CONTENTION_START_MINS // 60:02d}:"
                    f"{TERRAIN_CONTENTION_START_MINS % 60:02d}-"
                    f"{TERRAIN_CONTENTION_END_MINS // 60:02d}:"
                    f"{TERRAIN_CONTENTION_END_MINS % 60:02d} ET window, while the morning "
                    f"wide-chain capture holds the chain slots — the enrolled board rotates at "
                    f"the accrual cadence ({ACCRUAL_MIN_INTERVAL_OTHER_SEC:.0f}s) instead of "
                    f"being held out, so this ticker still accrues inside the window",
                )
            if _previewed:
                # Previewed tickers are a deliberate, ad-hoc operator action (someone typed
                # or clicked a ticker outside the enrolled board) -- they bypass
                # terrain_cycle_tickers' morning-contention throttle (built for the
                # enrolled board's own chain-slot budget) rather than being silently
                # dropped by a mechanism that was never about them.
                tickers = tickers + [tk for tk in _previewed if tk not in tickers]
            with concurrent.futures.ThreadPoolExecutor(max_workers=terrain_state.TERRAIN_WORKERS) as pool:
                list(pool.map(terrain_refresh._terrain_refresh_one, tickers))
        elif _viewed_now:
            # Outside the archival logger's window: the enrolled board's passive sweep does
            # not run (unchanged), but every ticker someone actually has open right now still
            # gets a real live attempt -- whatever Schwab is willing to return at this hour is
            # what gets shown, honestly labelled by its own age/source, never withheld because
            # the background WRITER happens to be off duty. The morning-contention throttle
            # above is itself an RTH-only concept (it exists to share chain-fetch slots with
            # the 09:30-10:00 ET wide-chain capture), so it does not apply here.
            _terrain_cycle_n += 1
            tickers = list(_viewed_now)
            with concurrent.futures.ThreadPoolExecutor(max_workers=terrain_state.TERRAIN_WORKERS) as pool:
                list(pool.map(terrain_refresh._terrain_refresh_one, tickers))
        else:
            tickers = []
        elapsed = time.monotonic() - cycle_start
        # RC-165: publish the DELIVERED cycle so freshness is judged against reality, not the
        # sleep floor. This number was already computed and only logged; readers had no access
        # to it, so terrain_staleness was left comparing against a cadence the loop never meets.
        terrain_state._terrain_last_cycle_sec = float(elapsed)
        log.info("Terrain cycle: %d tickers in %.1fs", len(tickers), elapsed)
        sleep_end = time.monotonic() + max(0.0, terrain_state.TERRAIN_REFRESH_SEC - elapsed)
        while _terrain_loop_running and time.monotonic() < sleep_end:
            time.sleep(0.5)
    log.info("Terrain loop stopped")


def _terrain_prewarm_worker() -> None:
    """Warm the radar caches off the request path.

    MEASURED: a cold radar sweep costs ~22.5 s -- ~11.5 s computing ATR for 51 tickers and
    the rest reading 51 chain payloads out of a 23 GB snapshots table (RC-6). Paying that
    on the operator's first click leaves the scope empty long enough to look broken. The
    app already prewarms model bundles at boot for the same reason; this is the same move
    for terrain. Failures are logged and ignored: a cold cache is slow, never wrong.
    """
    try:
        _seed_strike_geometry_from_storage()
    except Exception as e:
        log.warning("strike-geometry seed failed (first cycle uses the cold-start width): %s", e)
    try:
        get_terrain_radar(limit=60)
        log.info("terrain radar prewarm complete: %d cached", terrain_cache_size())
    except Exception as e:
        log.warning("terrain radar prewarm failed (cache stays cold): %s", e)


def _seed_strike_geometry_from_storage() -> None:
    """Learn every ticker's strike spacing from its last stored chain, at boot.

    Without this the first cycle after a restart fetches TERRAIN_STRIKE_COUNT_COLD_START
    for every ticker -- too narrow for SPY/QQQ, so they would report
    LOW_CONFIDENCE_NARROW_CHAIN for one cycle on every restart. The geometry is already
    on disk; reading it once off the request path removes that window entirely.
    """
    import server as _srv

    try:
        with _srv._logger_lock:
            tickers = list(_srv._logger_tickers)
    except Exception:
        tickers = list(_srv.CORE_TICKERS)
    seeded = 0
    for tk in tickers:
        try:
            contracts, stored_spot, _stored_ts = _srv._latest_chain_and_spot(tk)
        except Exception:
            continue
        if _learn_strike_geometry(tk, contracts, stored_spot):
            seeded += 1
    log.info("strike geometry seeded for %d/%d tickers", seeded, len(tickers))


def start_terrain_prewarm() -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    threading.Thread(target=_terrain_prewarm_worker, name="terrain-prewarm",
                     daemon=True).start()


def start_terrain_loop() -> None:
    """Start the terrain collection thread.

    Refuses to start under pytest. A production background thread inside the test
    process fetches chains and consumes the shared 2-slot chain gate for the rest of
    the session, which silently breaks any test asserting on gate concurrency -- the
    same shared-mutable-state failure class as RC-5 in governance/root_cause_log.md.
    Tests that need the loop call _terrain_loop / _terrain_refresh_one directly.
    """
    global _terrain_loop_running, _terrain_loop_thread
    if os.environ.get("PYTEST_CURRENT_TEST"):
        log.debug("terrain loop not started: running under pytest")
        return
    if _terrain_loop_running:
        return
    _terrain_loop_running = True
    _terrain_loop_thread = threading.Thread(target=_terrain_loop, name="terrain-loop", daemon=True)
    _terrain_loop_thread.start()


def stop_terrain_loop() -> None:
    global _terrain_loop_running
    _terrain_loop_running = False
