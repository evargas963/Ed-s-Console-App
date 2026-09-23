"""Terrain refresh cycle (RC-80: THE SINGLE PRODUCER OF LEVELS), extracted out of
server.py (RC-REHAB-1, 2026-09-23), twenty-fifth real module-level slice of the
server.py decomposition.

_terrain_refresh_one moves here verbatim, its own early-return/exception-handling
shape UNCHANGED, but its 291-line body is genuinely decomposed (not just relocated)
into 4 newly-named private helpers, each independently reviewable:

  - _terrain_chain_fetch_ladder: the vendor timeout/HTTP-error-budget fallback ladder
    (full chain -> dte<=120 -> dte<=45), returns (resp, chain_basis) and lets the
    caller decide the "error:chain_http" early return -- this function itself never
    triggers it, so _terrain_refresh_one's own control-flow shape is untouched.
  - _apply_gamma_surface_projection: the stream-overlaid strike x expiry GEX surface
    application (project + overlay + per-cell stream-state stamp + backfill),
    mutates `payload` in place, returns whether a surface_seq stamp is owed.
  - _bank_daily_atm_iv_from_payload / _bank_daily_strike_oi_and_walls: the two
    independent accrual side-effect blocks (IV banking, OI banking + delta-OI walls),
    each self-contained and fail-closed exactly as they were inline.

_gamma_surface_contracts_with_stream_overlay (confirmed sole caller, inside the
gamma-surface-projection block) moves with the group. _accrue_chain_observation
deliberately STAYS in server.py despite having only one call site here: its own
internals touch several accrual-state names (gex_et_date_and_mins, ACCRUAL_SENTINELS,
_accrual_last_write, etc.) with MORE than one real reader elsewhere in server.py,
not fully traced in this slice -- reached via the established lazy `import server`
pattern instead of risking a mis-traced move in money-path code.

MONKEYPATCH/RUNTIME-STATE NOTE: every other name this module touches (get_client,
_universal_capture_wanted, _terrain_strike_count,
_persist_universal_capture, _persist_universal_complete_chain, _learn_strike_geometry,
_radar_atr, flatten_chain_contracts, resolve_spot, _gated_safe_get_chain,
_terrain_refresh_last_error, _terrain_cache, _terrain_cache_lock,
_terrain_profile_cache, _gamma_surface_wanted, _desired_stream_greeks_for_ticker,
_desired_option_symbols_for_ticker, _stamp_gamma_surface_cell_stream_state,
_backfill_gex_cells_from_last_valid, _per_strike_view_from_contracts,
_next_gamma_surface_seq, _accrue_chain_observation, _log_flip_drift, get_db,
LEVELS_SOURCE_WIDE_CHAIN, GAMMA_SURFACE_STREAM_STALENESS_SEC, _overlaid_symbols) has
a confirmed OTHER caller/reader elsewhere in server.py -- checked individually before
this slice, not assumed -- so all stay in server.py, reached via the established
lazy `import server` pattern.

compute_terrain (terrain_engine.py), ticker_storage_key (instrument_identity.py), and
GEX_FULL_CHAIN_STRIKE_COUNT (calibration.option_chain_morning_full, sole reader) are
re-imported here directly from their own modules -- none of this is server.py-specific
logic.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import flip_drift_log as _fdl  # RC-REHAB-1 forty-first slice
import terrain_capture as _tcap  # RC-REHAB-1 forty-first slice
import terrain_schedule as _tsch  # RC-REHAB-1 forty-first slice
import terrain_quarantine as _tq  # RC-REHAB-1 fortieth slice: the quarantine book's own home

import gamma_surface_state as _gss  # RC-REHAB-1 forty-second slice
import per_strike_view as _psv  # RC-REHAB-1 forty-second slice
log = logging.getLogger(__name__)

from calibration.option_chain_morning_full import GEX_FULL_CHAIN_STRIKE_COUNT
from instrument_identity import ticker_storage_key
from terrain_engine import compute_terrain
import chain_width
import terrain_state


def _gamma_surface_contracts_with_stream_overlay(
        tk: str, contracts: list, *, newer_than_ts: float | None = None) -> tuple[list, int, list[str]]:
    """Overlay EVERY currently-streaming option contract's freshest known GAMMA/DELTA/
    OPEN_INTEREST/VOLUME onto `contracts` before projection, for whichever of them
    belong to `tk` (RC-UI-3: primary AND every additional contract — see
    _desired_stream_greeks_for_ticker).

    Still the ONE canonical faucet (project_gamma_surface -> compute_exposures_by_strike,
    RC-UI-1): this changes no formula and adds no second producer, it only lets those
    fields be fresher than the REST chain snapshot they arrived in.

    `newer_than_ts`, when given, is passed straight through as the REST-baseline precedence
    bound (see overlay_streamed_contract_fields) — independent-review finding (2026-09-12):
    "being received within ten seconds does not establish that a stream value is newer than
    the REST input it replaces."

    Fails closed to the unmodified `contracts` on any error or when nothing applies — this is
    a best-effort freshening, never a precondition for the projection to run at all."""

    try:
        from math_exposure_core import overlay_streamed_contract_fields

        streamed = _gss._desired_stream_greeks_for_ticker(tk)
        if not streamed:
            return contracts, 0, []
        overlaid, n = overlay_streamed_contract_fields(
            contracts, streamed,
            newer_than_ts=newer_than_ts, max_staleness_sec=_gss.GAMMA_SURFACE_STREAM_STALENESS_SEC)
        return overlaid, n, _gss._overlaid_symbols(contracts, overlaid)
    except Exception as e:  # institutional-swallow-ok: best-effort freshening, never load-bearing
        log.debug("gamma-surface stream overlay skipped for %s: %s", tk, e)
        return contracts, 0, []


def _terrain_chain_fetch_ladder(client, tk: str, width: int, priority: bool) -> tuple:
    """The vendor timeout/HTTP-error-budget fallback ladder (RC-127/RC-149): the full
    multi-year index book can exceed the vendor read timeout OR the vendor's own
    per-request budget under live load, so this narrows the DATE WINDOW one rung at a
    time (full -> dte<=120 -> dte<=45) on either failure mode, and stamps which rung
    produced the answer -- degraded is visible, never silent.

    Returns (resp, chain_basis). `resp` is None when every rung failed (timeout or an
    over-budget HTTP code); the caller decides what "no usable response" means for its
    own control flow (this function never returns early on the caller's behalf, exactly
    preserving _terrain_refresh_one's original inline shape). A non-timeout exception on
    any rung is NOT swallowed here -- it propagates to the caller's own outer
    except-and-classify block, unchanged from the original inline code."""
    import server as _srv

    chain_basis = "full"
    resp = None
    # RC-149: the ladder narrowed on a TIMEOUT EXCEPTION only. An over-budget index chain does
    # not time out — the vendor answers, with HTTP 502 — so `break` fired on the first rung and
    # the narrower rungs it exists to reach were never tried. MEASURED 2026-07-30: $SPX
    # returned HTTP 502 on every cycle for 2h10m while a ladder built for exactly this case
    # sat unused, because RC-127 was written from a day when the same over-width request
    # happened to die in ReadTimeout instead. One failure, two vendor expressions; the rung
    # must advance on the CONDITION (this window is too big), never on the expression of it.
    _OVER_BUDGET_CODES = (502, 413, 500, 504)
    for _basis, _to_days in (("full", None), ("dte<=120", 120), ("dte<=45", 45)):
        try:
            _to = ((datetime.now(timezone.utc) + timedelta(days=_to_days)).date()
                   if _to_days else None)
            resp, _gate_wait, _fetch_sec = _srv._gated_safe_get_chain(
                client, tk, strike_count=width, priority=priority, to_date=_to,
            )
            _code = getattr(resp, "status_code", None)
            if _code in _OVER_BUDGET_CODES and _to_days != 45:
                terrain_state._terrain_refresh_last_error[tk] = (
                    f"chain fetch HTTP {_code} at basis {_basis!r} — trying a narrower window")
                resp = None          # do NOT keep a failed response as the answer
                continue
            chain_basis = _basis
            break
        except Exception as _fe:
            if type(_fe).__name__ not in ("ReadTimeout", "ConnectTimeout", "TimeoutException"):
                raise
            terrain_state._terrain_refresh_last_error[tk] = (
                f"chain fetch timeout at basis {_basis!r} — trying a narrower window")
            continue
    return resp, chain_basis


def _apply_gamma_surface_projection(tk, payload, contracts, spot, spot_source, spot_ts, rest_fetch_ts) -> bool:
    """RC-UI-1: apply the LIVE strike × expiry GEX surface, projected from the SAME live
    wide chain and live spot this cycle already holds, through the ONE canonical faucet
    (project_gamma_surface -> compute_exposures_by_strike). Zero extra vendor calls, one
    producer, current Greeks/spot — so /api/options/gamma-surface is temporally coherent
    with terrain instead of a morning snapshot. Fail-closed: a projection error leaves
    the field absent (endpoint falls back to the LABELLED banked-morning reference); it
    must never take down the terrain refresh that feeds the live desk.

    RC-UI-1 #1 (perf): the per-expiry projection is measurable — SYNTHETIC SCALE BASELINE
    ~86 ms (equity, 3.6k contracts) / ~1.36 s (full SPXW book, 42k), median over repeats —
    the SPXW figure is material at the low end of this cycle's vendor fetch. Gate it to
    tickers whose gamma surface was requested recently so an unviewed ticker pays ZERO
    cost; a viewed ticker gets the live surface each cycle. Live RTH end-to-end
    terrain-cycle impact is proven in F.

    Mutates `payload` in place. Returns whether the caller owes a surface_seq stamp
    (deferred to the caller's own cache-write lock, exactly like the original inline
    code: the DECISION to stamp a seq is made here; the seq itself is assigned, and the
    SSE notify fired, atomically with the cache write, never here)."""
    import server as _srv
    from gamma_surface_projection import project_gamma_surface

    stamp_surface_seq = False
    try:
        if spot and _gss._gamma_surface_wanted(tk):
            _overlaid_contracts, _overlay_n, _overlay_syms = _gamma_surface_contracts_with_stream_overlay(
                tk, contracts, newer_than_ts=rest_fetch_ts)
            payload["_gamma_surface"] = project_gamma_surface(_overlaid_contracts, float(spot))
            if payload["_gamma_surface"] is not None:
                # ONE spot faucet (operator directive, 2026-09-15): stamp the EXACT spot
                # value/source/as-of this cycle's `resolve_spot` call above already
                # resolved, onto the surface object itself -- so a reader of THIS surface
                # (this exact surface_seq generation) never has to separately ask "what
                # spot produced these numbers"; it travels with the generation, identical
                # to what every other resolve_spot consumer in this same cycle saw.
                payload["_gamma_surface"]["spot"] = float(spot)
                payload["_gamma_surface"]["spot_source"] = spot_source
                payload["_gamma_surface"]["spot_as_of_ts_utc"] = spot_ts
                # Always-live heatmap mandate (2026-09-15): stamp per-cell stream state on
                # EVERY cycle, even when _overlay_n == 0 -- a cell must still be told apart
                # as 'stale' (desired but not fresh) vs 'unavailable' (never desired) even
                # when nothing was fresh enough to overlay this particular cycle.
                from app.options.order_flow.streaming import (
                    read_producer_rejected_option_contracts, is_option_producer_daemon_available)
                _gss._stamp_gamma_surface_cell_stream_state(
                    payload["_gamma_surface"], _gss._desired_stream_greeks_for_ticker(tk),
                    set(_overlay_syms), read_producer_rejected_option_contracts(),
                    set(_gss._desired_option_symbols_for_ticker(tk)),
                    daemon_available=is_option_producer_daemon_available())
                try:
                    # Best-effort enhancement, like the overlay above -- a bug here must
                    # never take down an otherwise-freshly-computed, valid surface.
                    _srv._backfill_gex_cells_from_last_valid(tk, payload["_gamma_surface"])
                except Exception as _bf_e:  # institutional-swallow-ok: never load-bearing
                    log.debug("gex snapshot backfill skipped for %s: %s", tk, _bf_e)
            if _overlay_n:
                # RC-UI-2/finding#2 fix (independent review, 2026-09-12, REPRODUCED): the
                # heatmap and the Strike Detail / GEX-by-strike panel disagreed on the SAME
                # strike because only _gamma_surface was ever refreshed from the overlay
                # while _per_strike (above) came from `snap` -- this ticker's UN-overlaid
                # `compute_terrain` result. Only recomputed when the overlay actually
                # changed something (_overlay_n > 0): the ordinary, nothing-is-streaming
                # cycle pays zero extra cost and keeps `snap`'s own per_strike, which is
                # also what _accrue_chain_observation banks below — a persisted historical
                # observation must reflect what the VENDOR's REST chain actually reported,
                # never a streamed freshening, so `snap` itself is never built from
                # `_overlaid_contracts`.
                payload["_per_strike"] = _psv._per_strike_view_from_contracts(_overlaid_contracts, float(spot))
            if payload["_gamma_surface"] is not None:
                payload["_gamma_surface"]["stream_overlay_contracts"] = _overlay_n
                # A SIXTH independent review (2026-09-13): the COUNT alone cannot tell a
                # consumer WHICH column/contracts actually received evidence -- see
                # _overlaid_symbols's own docstring finding. Exposed alongside the count
                # so a client can bind "observed" to the specific symbols it demanded,
                # never to "something, somewhere on this surface, was fresher."
                payload["_gamma_surface"]["stream_overlay_symbols"] = _overlay_syms
                # Independent-review finding (2026-09-12, state-authority review),
                # REPRODUCED: `_next_gamma_surface_seq` (bumps _gamma_surface_seq[tk] AND
                # pushes the SSE "gamma_surface_seq" notify) used to run HERE, in its own
                # EARLIER `with _terrain_cache_lock:` block -- a real gap of several
                # statements (and a possible exception) before `_terrain_cache[tk] =
                # payload` below, in a SECOND, later lock acquisition. Any reader in that
                # window (an SSE subscriber reacting to the notify by immediately
                # re-fetching, or an ordinary poll) could observe the NEW surface_seq while
                # `_terrain_cache[tk]` still held the PREVIOUS cycle's payload -- publication
                # announced before the published data was actually visible. Deferred: only
                # the DECISION to stamp a seq is made here; the seq itself is assigned (and
                # the SSE notify fired) atomically with the cache write below, exactly like
                # refresh_gamma_surface_from_stream already does it correctly.
                stamp_surface_seq = True
            # RC-UI-2: retained so a LATER streamed tick (arriving between this cycle and
            # the next ~60s REST refresh) can freshen the cached surface immediately without
            # a second vendor fetch — see refresh_gamma_surface_from_stream. Always the RAW
            # REST base, never a previously-overlaid result, so repeated eager freshenings
            # never compound away from what the vendor's chain actually reported.
            # `_contracts_rest_computed_ts` doubles as the generation marker
            # refresh_gamma_surface_from_stream compare-and-swaps against, so a REST cycle
            # landing mid-eager-computation is never silently overwritten by a stale result.
            payload["_contracts_rest"] = contracts
            payload["_contracts_rest_spot"] = float(spot)
            payload["_contracts_rest_computed_ts"] = rest_fetch_ts
        else:
            payload["_gamma_surface"] = None
    except Exception as _gs_e:  # institutional-swallow-ok: projection is a cache side-effect
        payload["_gamma_surface"] = None
        log.warning("gamma-surface projection raised for %s (surface withheld this cycle): %s", tk, _gs_e)
    return stamp_surface_seq


def _bank_daily_atm_iv_from_payload(tk, payload) -> None:
    """RC-354: bank the day's ATM IV from the sigma band this refresh already computed
    (one faucet, zero added vendor calls). UPSERT — last write of the session wins,
    converging to the CLOSING IV that IV Rank/Percentile are defined against."""
    import server as _srv

    try:
        _em_band = payload.get("implied_1d_move") or {}
        _iv = _em_band.get("iv_pct_atm")
        if _iv is not None and float(_iv) > 0:
            from time_et import now_et as _iv_now_et
            _srv.get_db().bank_daily_atm_iv(
                tk, _iv_now_et().strftime("%Y-%m-%d"), float(_iv),
                _em_band.get("dte_used"), _em_band.get("method"), time.time())
    except Exception as _iv_e:
        # institutional-swallow-ok: IV banking is an accrual side-effect — a write
        # failure is logged but must never take down the terrain refresh that feeds
        # the live desk. The gap simply shows as a missing day in iv_daily.
        log.warning("iv_daily banking failed for %s: %s", tk, _iv_e)


def _bank_daily_strike_oi_and_walls(tk, snap) -> None:
    """RC-359: bank today's per-strike OI (same exposures book) and compute the ΔOI
    walls vs the prior banked session. Fail-closed: no prior session -> walls None
    (the Console says 'banking'), never a fabricated diff."""
    import server as _srv

    try:
        _oi_map = getattr(snap, "oi_by_strike", None) or {}
        if _oi_map:
            from math_exposure_core import compute_delta_oi_walls as _doiw
            from time_et import now_et as _oi_now_et
            _oi_date = _oi_now_et().strftime("%Y-%m-%d")
            _srv.get_db().bank_daily_strike_oi(
                tk, _oi_date,
                [(k, c, p) for k, (c, p) in _oi_map.items()], time.time())
            _prev_oi = _srv.get_db().prev_session_strike_oi(tk, _oi_date)
            _walls = _doiw(_oi_map, _prev_oi)
            with terrain_state._terrain_cache_lock:
                if tk in terrain_state._terrain_cache:
                    terrain_state._terrain_cache[tk]["delta_oi_walls"] = _walls
    except Exception as _oi_e:
        # institutional-swallow-ok: same accrual doctrine as iv_daily above — log,
        # never break the refresh; a missing day is a visible gap.
        log.warning("oi_daily banking failed for %s: %s", tk, _oi_e)


def _terrain_refresh_one(ticker: str, priority: bool = False) -> str:
    """Fetch one chain and compute terrain into the cache. Never raises.

    RC-80 — THE SINGLE PRODUCER OF LEVELS. /api/terrain calls this on a cache miss rather than
    computing its own snapshot, because a second producer is a second faucet even when both write
    the same cache key. `priority` is True for that operator-facing miss (someone is waiting on
    the response) and False for the background rotation.
    """
    import server as _srv

    tk = ticker_storage_key(ticker)   # RC-126: SPX -> $SPX at the producer too — background
    if not tk:                        # callers (radar, enroll lists) don't pass the endpoints
        return "skip:empty"
    # RC-148: BEFORE the client, before the gate, before any vendor budget is spent. MEASURED
    # 2026-07-30 11:14 ET: RTY and XXT had each been re-requested every ~60 s all session for a
    # symbol Schwab answers with HTTP 400 — two permanently-wasted slots per minute out of a
    # 2-slot gate, against a book where $SPX could not get a chain through. Making that visible
    # (RC-147) was necessary and not sufficient: a control that reports the burn while the burn
    # continues has not fixed anything. A `priority` request (an operator is on the endpoint,
    # waiting) still honours the hold — the answer would be the same HTTP 400, just slower.
    if _tq._terrain_quarantine_blocks(tk):
        return "skip:quarantined"
    try:
        client = _srv.get_client()
        want_capture, cap_key = _tcap._universal_capture_wanted(tk)
        _width = chain_width._terrain_strike_count(tk)
        if want_capture:
            _width = max(_width, GEX_FULL_CHAIN_STRIKE_COUNT)
        # RC-127: the FULL multi-year index book ($SPX: weeklies + quarterlies + LEAPS) can
        # exceed the vendor read timeout under live load — measured 2026-07-29: every $SPX
        # refresh died in ReadTimeout while the same fetch succeeded on a quiet box. The
        # ladder narrows the DATE WINDOW on timeout, one rung at a time, and STAMPS the
        # basis on the payload — degraded is visible, never silent. The operator-locked
        # full-chain basis stays the first attempt always; the rungs keep the weekly+monthly
        # book dealers actually hedge (120d, then 45d) rather than serving nothing.
        resp, _chain_basis = _terrain_chain_fetch_ladder(client, tk, _width, priority)
        if resp is None or getattr(resp, "status_code", None) != 200:
            _code = getattr(resp, "status_code", None)
            _msg = f"chain fetch failed (HTTP {_code if _code is not None else 'timeout-at-all-rungs'})"
            terrain_state._terrain_refresh_last_error[tk] = _msg
            # RC-148: classify so the response fits the cause. A 4xx is the vendor refusing THIS
            # SYMBOL and will refuse it identically forever; a timeout or 5xx is the venue being
            # busy and deserves a backoff, not a death sentence.
            _tq._note_terrain_failure(tk, _msg, _tq._classify_chain_failure(
                _code, "timeout-at-all-rungs" if resp is None else None))
            return "error:chain_http"
        # Independent-review finding (2026-09-12), REPRODUCED: the generation marker used below
        # for stream-precedence ("is a streamed value newer than this REST data") was stamped
        # AFTER compute_terrain -- a real, non-trivial computation, not the REST observation
        # itself. A stream tick that arrived causally AFTER this REST response but BEFORE
        # compute_terrain finished was judged "not newer than REST" and discarded, even though
        # it genuinely postdated the REST DATA it would have overlaid. `_rest_fetch_ts` is
        # captured HERE -- the instant the 200 response is in hand, before any parsing or
        # computation -- and is what the overlay/eager-refresh precedence check (below) and the
        # compare-and-swap generation marker (_contracts_rest_computed_ts) actually use.
        # `payload["computed_ts_utc"]` keeps its own, different meaning (this cycle's full
        # computation finish time, used for display staleness/age) and is not reused for this.
        _rest_fetch_ts = time.time()
        c_json = resp.json()
        contracts = _srv.flatten_chain_contracts(c_json)
        # ONE spot authority (RC-14) — never the chain underlying on its own.
        spot, spot_source, spot_ts = _srv.resolve_spot(tk, chain_json=c_json)
        if want_capture and contracts:
            _tcap._persist_universal_capture(tk, cap_key, _width, contracts, spot)
        if contracts:
            # Deliberately NOT gated on want_capture: that flag reflects the SIBLING
            # wide-fetch's own once-per-day "done" state, and this function needs its
            # own chance to run on every cycle inside the window so a near-term
            # expiry universe wider than one cycle's budget still gets fully covered
            # over successive cycles (see the function's own docstring for the
            # operator-caught defect this fixes). It self-gates on window/trading-day/
            # remaining-work internally, so a no-op call here costs one cheap DB check,
            # never a vendor call.
            _tcap._persist_universal_complete_chain(tk, client, contracts)
        # Learn this instrument's geometry from the chain we just read, so the NEXT cycle
        # requests the width its +/-5% span actually needs instead of a tabulated guess.
        # RC-149: tell the learner WHICH basis produced this chain. A narrowed window under-counts
        # expiries, and that count is the denominator of the next request's width budget.
        _srv._learn_strike_geometry(tk, contracts, spot,
                               date_window_narrowed=(_chain_basis != "full"))
        snap = compute_terrain(tk, contracts, spot)
        payload = snap.to_dict()
        payload["computed_ts_utc"] = time.time()
        # RC-82: stamp WHICH producer computed these levels. The radar merges this loop's
        # wide-chain output with stored-chain fallback rows and ranks them against each other;
        # wall selection depends on chain width (RC-80 measured an 11-point difference on SPY),
        # so an unlabelled merge sorts systematically-different numbers as if they were peers.
        payload["levels_source"] = _srv.LEVELS_SOURCE_WIDE_CHAIN
        # RC-127: which rung of the timeout ladder produced this book — 'full' is the
        # operator-locked basis; a narrower rung is visible degradation, never silent.
        payload["chain_basis"] = _chain_basis
        payload["spot_source"] = spot_source
        payload["spot_as_of_ts_utc"] = spot_ts
        _atr = _srv._radar_atr(tk)
        payload["atr_daily"] = round(_atr.daily, 3) if _atr.daily else None
        payload["atr_15m"] = round(_atr.m15, 3) if _atr.m15 else None
        # RC-68: carry the LIVE per-strike map into the cache. to_dict() deliberately drops it
        # (hundreds of entries, far too heavy for every poll — same reason `profile` is dropped),
        # so /api/terrain/strikes reads it from the cached snapshot instead of the frozen morning
        # archive. Underscore-prefixed so it is unmistakably an internal cache field, not payload.
        # getattr, not attribute access: a snapshot without the map (older shape, or a stub) must
        # degrade to an EMPTY per-strike panel, never take down the whole terrain refresh.
        payload["_per_strike"] = getattr(snap, "per_strike", None) or {}
        stamp_surface_seq = _apply_gamma_surface_projection(
            tk, payload, contracts, spot, spot_source, spot_ts, _rest_fetch_ts)
        with terrain_state._terrain_cache_lock:
            if stamp_surface_seq:
                payload["_gamma_surface"]["surface_seq"] = _gss._next_gamma_surface_seq(tk)
            terrain_state._terrain_cache[tk] = payload
            _srv._terrain_profile_cache[tk] = snap.profile
        # RC-159 (operator mandate 2026-07-30): ACCRUE the wide chain across
        # [09:15, 16:15] ET == [08:15, 15:15] CT. The chain is already fetched and the
        # per-strike map already computed above, so this costs ZERO additional vendor calls —
        # it persists what RC-68 kept in memory and then discarded every cycle. Sentinels bank
        # every minute; the rest of the board every five, because 40 tickers x 1/min of
        # per-strike JSON is hundreds of MB a day for data no surface reads at that resolution.
        _tsch._accrue_chain_observation(tk, snap)
        _fdl._log_flip_drift(tk, payload)
        terrain_state._terrain_refresh_last_error.pop(tk, None)   # RC-126: success clears the sticky reason
        _tq._note_terrain_success(tk)                   # RC-148: and the failure streak with it
        _bank_daily_atm_iv_from_payload(tk, payload)
        _bank_daily_strike_oi_and_walls(tk, snap)
        return f"ok:{snap.confidence}"
    except Exception as e:
        # RC-126: DEBUG here meant $SPX failed silently for a full session while the operator
        # stared at 'not_ready' with no reason. The failure is WARNING-visible AND kept, so
        # the endpoint can tell the operator WHY instead of an eternal shrug.
        terrain_state._terrain_refresh_last_error[tk] = f"{type(e).__name__}: {e}"
        # RC-148: an exception is never a symbol rejection (those arrive as a 4xx RESPONSE), so
        # it always classifies soft — backoff, never a permanent hold. A crash in our own code
        # must not be able to evict a real instrument from the board.
        _tq._note_terrain_failure(tk, f"{type(e).__name__}: {e}", "soft")
        log.warning("terrain refresh %s failed: %s", tk, e, exc_info=True)
        return f"error:{type(e).__name__}"
