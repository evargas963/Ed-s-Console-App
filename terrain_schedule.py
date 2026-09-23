"""Terrain loop scheduling: the RC-159 accrual cadence (sentinels every minute, the rest of
the board every five), the per-ticker accrual banker `_accrue_chain_observation`, and the
RC-161 morning-contention rotation `terrain_cycle_tickers`. Extracted from server.py
(RC-REHAB-1, 2026-09-23, forty-first slice). The loop's delivered cycle time
(`_terrain_last_cycle_sec`) stays in server.py because `_terrain_loop` rebinds it.
"""
from __future__ import annotations

import logging
import threading
import time

from calibration.option_chain_morning_full import (
    accrual_window as gex_accrual_window,
    et_date_and_mins as gex_et_date_and_mins,
    persist_chain_accrual,
)
from time_et import RTH_OPEN_MINS

log = logging.getLogger(__name__)


#: RC-159 accrual cadence, stated rather than implied. Sentinels every minute (they ARE the
#: money path); the rest of the enrolled board every five. These are FLOORS between writes, not
#: a schedule — the terrain loop's own cadence still governs when a chain exists to bank.
ACCRUAL_MIN_INTERVAL_SENTINEL_SEC: float = 60.0
ACCRUAL_MIN_INTERVAL_OTHER_SEC: float = 300.0
ACCRUAL_SENTINELS: tuple[str, ...] = ("SPY", "QQQ", "IWM")
_accrual_last_write: dict[str, float] = {}
_accrual_lock = threading.Lock()


def _accrue_chain_observation(tk: str, snap) -> None:
    """Bank one wide-chain per-strike observation. Never raises into the producer.

    A failure to ARCHIVE must never take down the loop that FEEDS the screen: collection is
    downstream of display, and losing a row is recoverable while losing the refresh is not.
    """
    try:
        import server as _srv                  # runtime: get_db (monkeypatched by tests)

        _d, mins = gex_et_date_and_mins()
        if not gex_accrual_window(mins):
            return
        floor = (ACCRUAL_MIN_INTERVAL_SENTINEL_SEC if tk in ACCRUAL_SENTINELS
                 else ACCRUAL_MIN_INTERVAL_OTHER_SEC)
        now = time.time()
        with _accrual_lock:
            if now - _accrual_last_write.get(tk, 0.0) < floor:
                return
            _accrual_last_write[tk] = now
        rows = (getattr(snap, "per_strike", None) or {}).get("all") or []
        if not rows:
            return                      # absence stays absence; never bank an empty observation
        res = persist_chain_accrual(
            _srv.get_db().db_path, ticker=tk, per_strike_rows=rows,
            spot=getattr(snap, "spot", None), ts_utc=now)
        if res.get("status") != "written":
            log.debug("chain accrual %s: %s", tk, res)
    except Exception as e:
        log.warning("chain accrual failed for %s: %s", tk, e)


#: RC-161 — the morning contention guard's OWN start, decoupled from the archive write gate.
#: RC-159 widened `MORNING_START_MINS` 570 -> 555 so the once-daily archive could open at the
#: mandated 09:15 ET. That constant was ALSO the scheduler's sentinel-only filter, so the same
#: edit lengthened non-sentinel starvation by 15 minutes at precisely the moment the accrual
#: mandate begins. One constant was answering two different questions: "when may the archive
#: accept a first write" and "when is the chain gate too busy for a full sweep".

TERRAIN_CONTENTION_START_MINS: int = RTH_OPEN_MINS  # F09: cash open = time_et.RTH_OPEN_MINS
TERRAIN_CONTENTION_END_MINS: int = 600     # 10:00 ET


def terrain_cycle_tickers(
    all_tickers: list[str], mins: int, cycle_n: int
) -> tuple[list[str], list[str]]:
    """Which tickers this cycle refreshes, and which are DEFERRED to a later cycle.

    RC-161. The morning guard used to DROP every non-sentinel for a full half hour, which made
    the accrual mandate sentinel-only in [555, 600) — a universal claim that three tickers were
    meeting. Exclusion is now ROTATION: no enrolled ticker is ever removed from the board, it is
    scheduled later within the window.

    The rotation depth is derived from the accrual cadence, not guessed: a non-sentinel needs one
    refresh per ACCRUAL_MIN_INTERVAL_OTHER_SEC, so with a TERRAIN_REFRESH_SEC cycle it needs to
    appear once every `depth` cycles. Refreshing it more often would spend vendor budget on a
    write the accrual floor would throw away, so this rotation costs nothing the mandate does not
    already require — and it keeps the original budget intent (RC-146: do not pile a 54-ticker
    sweep on top of the money-path wide fetches at the open) by spreading, not by starving.

    Returns (refresh_now, deferred_this_cycle). Outside the contention window every ticker
    refreshes, exactly as before.
    """
    sentinels = [t for t in all_tickers if str(t).upper() in ACCRUAL_SENTINELS]
    others = [t for t in all_tickers if str(t).upper() not in ACCRUAL_SENTINELS]
    if not (TERRAIN_CONTENTION_START_MINS <= int(mins) <= TERRAIN_CONTENTION_END_MINS):
        return list(all_tickers), []
    # integer ceiling division
    import server as _srv                      # runtime: the loop's cadence floor

    _cyc = max(1, int(_srv.TERRAIN_REFRESH_SEC))
    depth = max(1, -(-int(ACCRUAL_MIN_INTERVAL_OTHER_SEC) // _cyc))
    idx = int(cycle_n) % depth
    slice_now = others[idx::depth]
    deferred = [t for t in others if t not in set(slice_now)]
    return sentinels + slice_now, deferred
