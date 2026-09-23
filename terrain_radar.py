"""Terrain radar: the per-ticker ATR pair cache (single-flight, background refresh, vendor
daily-ATR fallback), the radar row / wall-contact classification, the terrain snapshots the
radar ranks (live cache merged with a stale-while-refresh stored-chain fallback), and the
fallback's single-flight recompute. Extracted from server.py (RC-REHAB-1, 2026-09-23,
forty-sixth slice). `_radar_fallback_cache` is REBOUND here; read it as
`terrain_radar._radar_fallback_cache`. Server-owned runtime is read through a lazy
`import server as _srv`.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import terrain_loop as _tl
import terrain_state
from instrument_identity import ticker_storage_key
from terrain_atr import RING_REGIME, AtrPair, atr_distance, compute_atr_pair, ring_for
from terrain_engine import compute_terrain

log = logging.getLogger(__name__)


RADAR_NEAR_PCT: float = 0.0020   # at the wall


RADAR_WATCH_PCT: float = 0.0075  # in the sector, worth watching


_radar_fallback_cache: tuple[float, list[dict]] = (0.0, [])


RADAR_FALLBACK_TTL_SEC: float = 60.0


#: ATR is derived from ~100 sessions of 1-minute bars, so it moves slowly. Recomputing it
#: per radar poll would re-read the bar table for every ticker every 20 seconds.
_radar_atr_cache: dict[str, tuple[float, "AtrPair"]] = {}


RADAR_ATR_TTL_SEC: float = 900.0


#: Tickers whose ATR is being computed right now, so N concurrent requests trigger ONE
#: computation instead of N. Guards the cache fill, not the cache read.
_radar_atr_inflight: set[str] = set()


_radar_atr_lock = threading.Lock()


_radar_atr_refresh_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ed_atr_refresh")


#: RC-484 (2026-08-25): vendor daily-ATR fallback cache — one Schwab daily-candle fetch
#: per (ticker, ET date). Keyed by date so a fresh ticker's radar scale appears today
#: and refreshes tomorrow, without a per-cycle vendor call.
_radar_daily_atr_vendor_cache: dict[str, tuple[str, float | None]] = {}


def _radar_daily_atr_vendor_fallback(tk: str) -> float | None:
    """Daily ATR from Schwab DAILY candles when local 1m history spans <15 sessions
    (RC-484: chain walls exist from minute one but the radar ring stayed blind ~3 weeks
    for a fresh enrollee). Cached per ticker per ET date; fail-closed to None."""
    import server as _srv
    from time_et import now_et as _now_et

    day_key = _now_et().date().isoformat()
    hit = _radar_daily_atr_vendor_cache.get(tk)
    if hit and hit[0] == day_key:
        return hit[1]
    daily = None
    try:
        from schwab_client import safe_get_daily_price_history
        from terrain_atr import compute_atr_from_daily_candles

        resp = safe_get_daily_price_history(_srv.get_client(), tk, period_months=2)
        if resp is not None and getattr(resp, "status_code", None) == 200:
            daily = compute_atr_from_daily_candles((resp.json() or {}).get("candles") or [])
    except Exception as e:
        log.debug("radar daily-ATR vendor fallback failed for %s: %s", tk, e, exc_info=True)
    _radar_daily_atr_vendor_cache[tk] = (day_key, daily)
    return daily


def _radar_atr_compute_into_cache(tk: str) -> "AtrPair":
    """Compute one ticker's ATR and publish it. Always clears the in-flight marker."""
    import server as _srv

    try:
        pair = compute_atr_pair(str(_srv.get_db().db_path), tk)
    except Exception as e:
        log.debug("radar ATR failed for %s: %s", tk, e, exc_info=True)
        pair = AtrPair(None, None)
    if pair.daily is None:
        # RC-484: local bars cannot scale a fresh ticker for ~15 sessions; the vendor
        # daily series can, immediately. m15 stays local-only (it needs today's tape,
        # which the accumulator provides within minutes anyway).
        fallback_daily = _radar_daily_atr_vendor_fallback(tk)
        if fallback_daily is not None:
            pair = AtrPair(daily=fallback_daily, m15=pair.m15)
    with _radar_atr_lock:
        _radar_atr_cache[tk] = (time.time(), pair)
        _radar_atr_inflight.discard(tk)
    return pair


def _radar_atr(ticker: str | None) -> "AtrPair":
    """Cached ATR pair for a radar row. NEVER blocks on a recomputation. Never raises.

    OBSERVED 2026-07-20 (py-spy dump of the live console, PID 33156): eleven AnyIO worker
    threads were simultaneously inside compute_atr_pair via _radar_atr <- get_terrain_radar.

    `get_terrain_radar` is a SYNC endpoint, so FastAPI runs it in the AnyIO threadpool.
    The old body checked the cache and, on a miss, computed inline with NO single-flight
    guard -- so every concurrent request that missed recomputed ATR for all 51 tickers,
    each a 24,000-row read of price_bars_1m. That is a cache stampede, and because those
    are the SHARED threadpool workers, exhausting them blocks every other sync endpoint in
    the app. The operator saw the whole console hang, not just the terrain tab.

    Two changes make a request incapable of causing it:
      * SINGLE FLIGHT -- one computation per ticker at a time; concurrent callers do not
        queue behind it.
      * STALE WHILE REVALIDATE -- an expired entry is returned IMMEDIATELY and refreshed
        on a small dedicated pool. ATR over ~100 sessions does not change meaningfully in
        the seconds a refresh takes, so serving a slightly old value is correct, and it is
        strictly better than blocking a request thread to avoid it.

    Only a ticker with NO cached value at all can still compute inline; the boot prewarm
    fills those, and the dedicated pool bounds it at 2 threads regardless.
    """
    tk = ticker_storage_key(ticker)  # RC-345/F25: canonical — cache key AND compute_atr_pair DB query hit $-index bars
    if not tk:
        return AtrPair(None, None)
    now = time.time()
    with _radar_atr_lock:
        hit = _radar_atr_cache.get(tk)
        if hit is not None and (now - hit[0]) < RADAR_ATR_TTL_SEC:
            return hit[1]
        already_running = tk in _radar_atr_inflight
        if not already_running:
            _radar_atr_inflight.add(tk)
    if hit is not None:
        # STALE-WHILE-REVALIDATE: hand back the old value now, refresh off the request path.
        if not already_running:
            try:
                _radar_atr_refresh_pool.submit(_radar_atr_compute_into_cache, tk)
            except RuntimeError:  # pool shut down during teardown
                with _radar_atr_lock:
                    _radar_atr_inflight.discard(tk)
        return hit[1]
    if already_running:
        # First-ever value for this ticker and someone else is computing it. Report
        # absence rather than block a shared worker; ring_for() treats None as "no ring"
        # and the contact simply does not appear until the value lands.
        return AtrPair(None, None)
    return _radar_atr_compute_into_cache(tk)


def _radar_row(t: dict, spot: float, atr: "AtrPair", status: str, level_name: str,
               level: float, gap: float | None, gap_atr: float | None,
               sort_key: float | None) -> dict:
    """One radar contact. `_sort` puts regime changes ahead of every wall."""
    return {
        "ticker": t.get("ticker"), "spot": spot, "regime": t.get("regime"),
        "posture": t.get("posture"), "status": status,
        "wall_name": level_name, "wall": level,
        "distance_pct": round(gap / spot * 100, 3) if gap is not None else None,  # caps-ok: distance stays None when there is no gap to a wall -- honest absence
        "distance_atr": round(gap_atr, 3) if gap_atr is not None else None,
        "distance_atr_15m": (round(abs(gap) / atr.m15, 2)
                             if (atr.m15 and gap is not None) else None),
        "atr_daily": round(atr.daily, 3) if atr.daily else None,
        "atr_15m": round(atr.m15, 3) if atr.m15 else None,
        "call_wall": t.get("call_wall"), "put_wall": t.get("put_wall"),
        "gamma_flip": t.get("gamma_flip"), "confidence": t.get("confidence"),
        # RC-82: which producer computed the walls on THIS row. Absent stamp reads as unknown,
        # never as the trusted wide chain.
        "levels_source": t.get("levels_source") or terrain_state.LEVELS_SOURCE_UNKNOWN,
        "_sort": sort_key if sort_key is not None else (gap_atr if gap_atr is not None else 9e9),
    }


def _radar_contact(t: dict, spot: float, atr: "AtrPair") -> dict | None:
    """The one contact this ticker earns on the scope, or None if it stays invisible.

    A ticker about to cross its FLIP outranks every wall: a regime change alters what all
    the other levels mean, so it sorts first regardless of wall distance.
    """
    flip_raw = t.get("gamma_flip")
    if flip_raw is not None:
        flip = float(flip_raw)
        flip_atr = atr_distance(flip - spot, atr.daily)
        if flip_atr is not None and flip_atr <= RING_REGIME:
            return _radar_row(t, spot, atr, "REGIME CHANGE", "gamma flip", flip,
                              flip - spot, flip_atr, sort_key=-1.0)

    # RC-83 — a strike that is BOTH walls is not a directional level. When call_wall and put_wall
    # land on the same strike the market has put gamma on both sides of it: that is a magnet, not
    # a barrier. This used to resolve by tuple order — `abs(v - spot) < abs(...)` is a STRICT
    # less-than, so on an exact tie the put never displaced the call and every such row rendered
    # "CALL WALL". MEASURED 2026-07-27: 7 of 22 tracked rows, including NVDA 200/200 with spot at
    # 196.49. "Call wall" reads resistance above and "put wall" reads support below, so choosing
    # one by position in a tuple states a direction the data does not support.
    cw, pw = t.get("call_wall"), t.get("put_wall")
    if cw is not None and pw is not None and float(cw) == float(pw):
        best = ("gamma wall", float(cw))
    else:
        best = None
        for name, v in (("call wall", cw), ("put wall", pw)):
            if v is not None and (best is None or abs(v - spot) < abs(best[1] - spot)):
                best = (name, v)
    if best is None:
        return None
    name, level = best[0], float(best[1])
    gap = level - spot
    ring = ring_for(gap, atr.daily)
    if ring is None:
        return None                       # beyond the scope — deliberately invisible
    status = {"CONTACT": "AT WALL", "CLOSING": "APPROACHING", "SECTOR": "IN SECTOR"}[ring]
    return _radar_row(t, spot, atr, status, name, level, gap,
                      atr_distance(gap, atr.daily), sort_key=None)


def _terrain_snapshots_for_radar() -> list[dict]:
    """Terrain for every tracked ticker: live cache first, stored chains as fallback.

    Without the fallback the radar is blank until the first loop cycle completes, so a
    freshly started console shows an empty scope and looks broken. The fallback reads the
    most recent stored chain per ticker (read-only, no Schwab call) and is superseded the
    moment the loop caches a fresher one.
    """
    with terrain_state._terrain_cache_lock:
        live_tickers = [t.get("ticker") for t in terrain_state._terrain_cache.values() if t.get("ticker")]
    cached: dict[str, dict] = {}
    for tkr in live_tickers:
        snap = _tl.terrain_cache_get(tkr)
        if snap is not None and snap.get("ticker"):
            cached[snap["ticker"]] = snap

    # MERGE, never choose. Returning only the cache meant that as soon as the loop had
    # cached its first ticker the stored-chain fallback was skipped entirely, so a warming
    # console showed an almost-empty scope. Live cache wins per ticker; everything not yet
    # refreshed still appears from its most recent stored chain.
    # NEVER BLOCKS (2026-07-23 open, measured): the inline recompute cost 21.7 s while
    # the sentinel-only morning window kept ~48 tickers on the fallback, and the terrain
    # view polls every 20 s — the sweep monopolised the sync threadpool and the operator
    # felt the whole app slow (favicon no-op measured 1.4 s). Same stampede class as
    # _radar_atr, same cure: serve the LAST memo immediately and refresh it on a
    # single-flight background thread. A stale memo beats a 21 s stall — the live cache
    # wins per ticker, so staleness only touches tickers the loop has not refreshed.
    ts, memo = _radar_fallback_cache
    # Kick on never-initialized (ts<=0) or TTL expiry — NOT on empty memo.
    # A successful recompute can legitimately land [] (live cache covers all
    # tickers); treating that as uninitialized re-stampeded the 21s DB sweep.
    if ts <= 0 or (time.time() - ts) >= RADAR_FALLBACK_TTL_SEC:
        _kick_radar_fallback_refresh()
    return list(cached.values()) + [m for m in (memo or [])
                                    if m.get("ticker") not in cached]


_radar_fallback_flight_lock = threading.Lock()


_radar_fallback_inflight = False


def _kick_radar_fallback_refresh() -> None:
    """Start ONE background fallback recompute; concurrent callers never queue."""
    global _radar_fallback_inflight
    with _radar_fallback_flight_lock:
        if _radar_fallback_inflight:
            return
        _radar_fallback_inflight = True
    threading.Thread(target=_radar_fallback_refresh_worker,
                     name="radar-fallback-refresh", daemon=True).start()


def _radar_fallback_refresh_worker() -> None:
    global _radar_fallback_cache, _radar_fallback_inflight
    try:
        out = _radar_fallback_recompute()
        if out is not None:
            _radar_fallback_cache = (time.time(), out)
    except Exception as e:
        log.warning("radar fallback refresh failed: %s", e)
    finally:
        with _radar_fallback_flight_lock:
            _radar_fallback_inflight = False


def _radar_fallback_recompute() -> list[dict] | None:
    """The heavy sweep (runs OFF the request path). None = keep the previous memo —
    a DB hiccup must degrade to stale data, never wipe the scope."""
    import server as _srv

    with terrain_state._terrain_cache_lock:
        cached = {t.get("ticker"): t for t in terrain_state._terrain_cache.values() if t.get("ticker")}
    out: list[dict] = []
    try:
        db = _srv.get_db()
    except Exception as e:
        # Degrading to live-cache-only is correct, but doing it SILENTLY made a DB outage
        # indistinguishable from a quiet market on the radar (Cursor audit 2026-07-20:
        # empty return with no note). The scope keeps the stale memo; say so.
        log.warning("radar fallback: DB unavailable (%s: %s) — keeping previous memo",
                    type(e).__name__, e)
        return None
    import sqlite3 as _sq
    try:
        con = _sq.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=30.0)
    except Exception as e:
        log.warning("radar fallback: DB open failed (%s: %s) — keeping previous memo",
                    type(e).__name__, e)
        return None
    try:
        con.row_factory = _sq.Row
        # Ticker LIST only — index-only aggregate, no blob touched. The per-ticker chain
        # read goes through _latest_chain_and_spot, NOT hand-rolled SQL here: the old
        # inline query took MAX(ts_utc) across BOTH timeframes, so a legacy 5m row could
        # shadow a newer-in-kind canonical 1m row (Bugbot 2026-07-20, confirmed).
        # _latest_chain_and_spot already encodes canonical-then-legacy, index-served.
        # timeframe-scope-ok (reality-reconciliation audit, 2026-09-18): this DISTINCT
        # enumerates ticker NAMES only, across both timeframes, never a timeframe-sensitive
        # VALUE — a ticker whose only chain snapshot currently sits on a legacy 5m row must
        # still surface here. Scoping to timeframe='1m' would silently drop it. Safe per
        # docs/repo_wide_canonical_enforcement_v2.md's own "documented multi-timeframe-safe
        # pattern" exception, since the real read is deferred to _latest_chain_and_spot above.
        tickers = [r["ticker"] for r in con.execute(
            "SELECT DISTINCT ticker FROM snapshots "
            "WHERE option_chain_json IS NOT NULL AND spot IS NOT NULL"
        )]
    finally:
        con.close()
    for tk in tickers:
        if tk in cached:
            continue
        try:
            contracts, spot, _stored_ts = _srv._latest_chain_and_spot(tk)
            if not contracts or not spot:
                continue
            # NO live quote per ticker here. The radar sweeps ~51 symbols; calling
            # resolve_spot on each made 51 Schwab round-trips and the cold sweep
            # measured 40.5 s, so the first render always timed out and the scope
            # came up empty. `snapshots.spot` is itself persisted from
            # quote.lastPrice, i.e. a real trade, just older. Any ticker the terrain
            # loop has refreshed already wins via the cache above, so the live value
            # reaches the scope through the loop rather than through 51 fetches.
            snap = compute_terrain(tk, contracts, spot)
        except (ValueError, TypeError):
            continue
        # RC-82: a stored-chain row is PROVISIONAL — narrower than the loop's chain, so its
        # walls sit systematically inward. Labelled, not hidden: it cannot be removed (per-symbol
        # vendor calls measured a 40.5s cold sweep) and it must not masquerade as a loop row.
        # snapshots.spot is an as-of lastPrice print, not current live spot.
        out.append(snap.to_dict() | {
            "spot_source": _srv.SPOT_SOURCE_SNAPSHOT,
            "spot_state": "historical",
            "spot_role": "as_of_snapshot_last_price",
            "levels_source": terrain_state.LEVELS_SOURCE_STORED_CHAIN,
        })
    return out
