"""Gamma-surface eager per-tick refresh hooks (server.py decomposition, twenty-
seventh slice, RC-REHAB-1, 2026-09-23).

refresh_gamma_surface_from_stream (registered with app.options.order_flow.
streaming.set_streamed_greeks_hook at startup: fires on a streamed option
contract's own greeks tick) and refresh_gamma_surface_from_spot_tick (its
documented SYMMETRIC SIBLING, RC-570: same trigger shape, fires on canonical spot
changing instead) move here verbatim, along with _per_strike_view_update_expiry
(confirmed sole caller: refresh_gamma_surface_from_stream). Neither hook is a
_fetch_state phase -- they eagerly freshen the _terrain_cache payload
_terrain_refresh_one (terrain_refresh.py) already seeded, between its ~60s REST
cycles -- so, like terrain_refresh.py and gamma_surface_projection.py, this gets
its own top-level name rather than a server_state_ prefix. server.py keeps a
2-name re-export: both functions are passed as first-class callables at startup
(set_streamed_greeks_hook(refresh_gamma_surface_from_stream);
on_tick_callback=_dispatch_spot_gamma_refresh, which itself calls
refresh_gamma_surface_from_spot_tick) from _app_lifespan's own body, still in
server.py.

MONKEYPATCH/RUNTIME-STATE NOTE: every server.py-local name this module touches
(_terrain_cache/_terrain_cache_lock, _desired_stream_greeks_for_ticker,
GAMMA_SURFACE_STREAM_STALENESS_SEC, resolve_spot, _overlaid_symbols,
_per_strike_view_from_contracts, _merge_all_expiry_exposures,
_contract_expiry_str, _stamp_gamma_surface_cell_stream_state,
_desired_option_symbols_for_ticker, _backfill_gex_cells_from_last_valid,
_next_gamma_surface_seq) has a confirmed OTHER caller/reader elsewhere in
server.py -- checked individually before this slice, not assumed.
_per_strike_view_from_contracts and its own private helpers
(_merge_all_expiry_exposures, _merge_strike_exposure_bucket,
_per_strike_exposures_by_expiry, _contract_expiry_str) deliberately ALL stay
together in server.py as one cohesive private group, even though
_per_strike_view_update_expiry (which moved here) is their only OTHER caller --
_per_strike_view_from_contracts itself has a real external caller in
terrain_refresh.py, so splitting its own private implementation helpers across
files while it stays would gain nothing.

project_gamma_surface/project_gamma_surface_update_expiry (gamma_surface_
projection.py), compute_terrain (terrain_engine.py), and ticker_storage_key
(instrument_identity.py) are re-imported here directly from their own modules.
vendor_option_root, contract_matches_underlying, overlay_streamed_contract_
fields, read_producer_rejected_option_contracts/is_option_producer_daemon_
available, compute_exposures_by_strike, and _per_strike_rows were already lazily
imported inline inside the function bodies in the original code and stay that
way, unchanged.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import gamma_surface_state as _gss  # RC-REHAB-1 forty-second slice
import per_strike_view as _psv  # RC-REHAB-1 forty-second slice
log = logging.getLogger(__name__)

from gamma_surface_projection import project_gamma_surface, project_gamma_surface_update_expiry
from instrument_identity import ticker_storage_key
from terrain_engine import compute_terrain
import terrain_state


def _per_strike_view_update_expiry(prior_by_expiry: "dict[str, dict] | None",
                                   prior_view: "dict | None", overlaid: list, spot: float,
                                   affected_expiries: "list[str]", *,
                                   prior_spot: "float | None") -> "tuple[dict, dict] | None":
    """Incrementally update the per-strike 'all' view for ONLY the expiries a streamed tick
    actually touched, reusing every OTHER expiry's already-computed contribution from
    `prior_by_expiry` (2026-09-16 audit follow-up — see `_per_strike_exposures_by_expiry`'s
    docstring for the additive-merge proof this relies on). Returns
    `(new_view, new_by_expiry_cache)`, or None when an incremental update cannot be proven
    safe (no cache to update from, the tick's own contracts carry no resolvable expiry, or
    spot has moved — see below) — the caller falls back to
    `_per_strike_view_from_contracts`'s full recompute exactly like
    `project_gamma_surface_update_expiry`'s own fallback contract.

    Independent-review finding (2026-09-16, follow-up mandate): every field this view
    reports (net_gex_1pct and the raw exposures the 'all' rows are built from) is a
    function of spot, for EVERY expiry, not only the touched one — the identical hazard
    `project_gamma_surface_update_expiry` guards against, and the identical fix: `spot`
    must be IDENTICAL to `prior_spot` (the spot `prior_by_expiry`/`prior_view` were
    themselves computed against) or this returns None, forcing a full, fresh-spot
    recompute of every expiry rather than merging a fresh slice for one expiry with
    stale-spot contributions cached from every other.

    Scope, disclosed: only the 'all' aggregate (the one /api/terrain/strikes' primary GEX-
    by-strike panel and the heatmap's own per-cell backfill actually read on a streamed
    tick) is recomputed here. 'near'/'far' (the <=7DTE / >7DTE chips) are CARRIED OVER
    unchanged from `prior_view` — recomputing them incrementally would require the same
    per-expiry decomposition AGAIN split a second way (by DTE, not by expiry identity),
    which is a real, separable piece of work with its own edge cases (a contract crossing
    the 7-DTE boundary as calendar time passes) — deferred rather than risked here. Those
    two chips are refreshed at the normal REST cadence (`_terrain_refresh_one`), same as
    the expirations list, walls, and regime already are; only the primary aggregate gets
    the eager, per-tick, incremental treatment the operator's mandate targets."""

    if not prior_by_expiry or not affected_expiries:
        return None
    if prior_spot is None or float(prior_spot) != float(spot):
        return None
    from terrain_engine import _per_strike_rows
    new_by_expiry = dict(prior_by_expiry)
    for exp in affected_expiries:
        exp_contracts = [ct for ct in overlaid if isinstance(ct, dict)
                         and _psv._contract_expiry_str(ct) == exp]
        if not exp_contracts:
            return None   # nothing to recompute this expiry's contribution from -- unsafe
        try:
            from math_exposure_core import compute_exposures_by_strike as _cebs
            exposures, _diag = _cebs(exp_contracts, spot=spot, require_oi=True)
        except Exception:
            return None
        new_by_expiry[exp] = exposures
    merged = _psv._merge_all_expiry_exposures(new_by_expiry)
    new_view = {
        "all": _per_strike_rows(merged, overlaid),
        "near": (prior_view or {}).get("near", []),  # caps-ok: prior_view: "dict | None" -- neither guard clause above checks it for None, so a genuinely-absent prior view honestly carries over an empty near/far chip, never a fabricated non-empty value
        "far": (prior_view or {}).get("far", []),  # caps-ok: same reasoning as the "near" line above
    }
    return new_view, new_by_expiry


def refresh_gamma_surface_from_stream(contract_symbol: str, ts_recv: float) -> str:
    """Eagerly freshen a cached ticker's gamma surface AND per-strike view the instant a
    streamed L1 tick carries new GAMMA/DELTA/OPEN_INTEREST for its currently-active option
    contract, instead of waiting for the next ~60s wide-chain REST cycle
    (_terrain_refresh_one). Registered with
    app.options.order_flow.streaming.set_streamed_greeks_hook at startup.

    Still the ONE canonical faucet: re-runs project_gamma_surface AND
    _per_strike_view_from_contracts on the SAME RAW REST chain (`_contracts_rest`, stamped by
    _terrain_refresh_one) with EVERY currently-desired contract's fields overlaid via
    overlay_streamed_contract_fields — never a second exposure formula, and always overlaid
    onto the untouched REST base so repeated eager refreshes never compound away from what the
    vendor's chain actually reported.

    Three independent-review findings (2026-09-12), all REPRODUCED, are fixed together here
    because they share one cause (this function used to touch only `_gamma_surface`, and only
    the ONE triggering contract's overlay):
      - the heatmap (_gamma_surface) and the Strike Detail / GEX-by-strike panel (_per_strike)
        disagreed on the SAME strike, because only one of the two was ever refreshed from the
        overlay -- fixed by publishing both from the SAME overlaid contracts, together.
      - a REST refresh landing WHILE this function was computing could be silently overwritten
        by this function's stale-baseline result once it finally wrote back -- fixed by a
        compare-and-swap on the REST generation marker (_contracts_rest_computed_ts): if the
        cache's generation changed between this function's read and its write, the computed
        result is DISCARDED, never published over a generation newer than the one it was
        computed from.
      - refreshing B (RC-UI-3 multi-contract coverage) silently discarded A's already-fresh
        overlaid value, because this always rebuilt a single-entry `{contract_symbol: greeks}`
        map for whichever ONE contract's tick triggered the call, overlaid onto the untouched
        REST baseline -- which carries no memory of A's prior overlay. Fixed at the root by
        gathering EVERY currently-desired contract's live streamed state fresh on every call
        (_desired_stream_greeks_for_ticker), so A's freshness is included even when B's tick is
        what triggered this particular refresh.

    Returns a status string (never raises) — diagnostic/test surface only, never load-bearing:
    a caller that ignores the return value still gets the fail-closed no-op on any failure.
    """
    import server as _srv

    try:
        from instrument_identity import vendor_option_root
        from app.options.order_flow.streaming import contract_matches_underlying
        if not vendor_option_root(contract_symbol):
            return "not_an_option_symbol"
        with terrain_state._terrain_cache_lock:
            tk = next((k for k in terrain_state._terrain_cache if contract_matches_underlying(contract_symbol, k)), None)  # caps-ok: None means "genuinely no cached ticker matches this contract", checked explicitly on the next line and triggers an early "no_cached_ticker" return -- not a silent default
            if tk is None:
                return "no_cached_ticker"
            payload = terrain_state._terrain_cache.get(tk) or {}
            base_contracts = payload.get("_contracts_rest")
            read_generation = payload.get("_contracts_rest_computed_ts")
            prior_gamma_surface = payload.get("_gamma_surface")
            prior_per_strike = payload.get("_per_strike")
            # The by-expiry cache is only trustworthy when it was built from THIS EXACT REST
            # baseline generation -- _terrain_refresh_one does not maintain it (that path
            # keeps its own, separately-gated per_strike write; see that function), so it is
            # populated lazily, here, by whichever eager call is first for a given
            # `read_generation`. A stale-generation cache (leftover from a PRIOR baseline) is
            # never used for the merge: silently rolling an old baseline's unaffected-expiry
            # contributions into a new baseline's total would understate/overstate strikes
            # the new REST cycle already corrected, for a reason having nothing to do with
            # streaming freshness.
            prior_per_strike_by_expiry = (
                payload.get("_per_strike_expiry_raw")
                if payload.get("_per_strike_expiry_raw_generation") == read_generation else None)
        if not base_contracts:
            return "no_rest_baseline"
        from math_exposure_core import overlay_streamed_contract_fields
        streamed = _gss._desired_stream_greeks_for_ticker(tk)
        if contract_symbol not in streamed:
            # The contract whose tick triggered THIS call has nothing to offer (already
            # stale-gated, or its coverage ended between the hook firing and this running)
            # -- still a real "nothing new from this call" outcome, even though some OTHER
            # desired contract might have data (that contract's own tick will trigger its
            # own call when it changes).
            return "no_streamed_greeks"
        overlaid, n = overlay_streamed_contract_fields(
            base_contracts, streamed,
            newer_than_ts=read_generation, max_staleness_sec=_gss.GAMMA_SURFACE_STREAM_STALENESS_SEC)
        if n == 0:
            return "no_change"
        # ONE spot faucet (operator directive, 2026-09-15, SECOND pass): "streamed GEX must
        # use the canonical fresh spot, not the REST-cycle spot... Remove the heatmap-local
        # _contracts_rest_spot fallback; a historical spot stamped on a completed surface may
        # remain provenance, but it must not become an alternate current-spot selector." This
        # eager path used to read `_contracts_rest_spot` -- a value cached from the LAST
        # wide-chain REST cycle (up to ~TERRAIN_REFRESH_SEC stale) -- as either the primary
        # OR a fallback spot, even though the whole point of this function is that a streamed
        # tick can be materially newer than that cycle. resolve_spot is THE single authority
        # (RC-14) -- no consumer, including this one, may fall back to reading its own cached
        # copy of a past resolve_spot answer as if it were a second source. If resolve_spot
        # itself has nothing right now (no live plane, no REST quote, no stored snapshot --
        # rare for an actively-streamed ticker), this refresh fails closed rather than
        # reaching for a stale substitute. Resolved here, only once we know there is real new
        # data to recompute -- a true no-op call (nothing streamed, or nothing newer than the
        # REST baseline) must never be turned into a spurious "no_current_spot" failure.
        spot, spot_source, spot_ts = _srv.resolve_spot(tk)
        if not spot:
            return "no_current_spot"
        _overlaid_syms_now = _gss._overlaid_symbols(base_contracts, overlaid)
        # Audit finding #2 (2026-09-16): a streamed tick only ever freshens the specific
        # contracts _desired_stream_greeks_for_ticker found newer data for -- each one
        # belongs to exactly one expiry (an option symbol encodes its own expiry) -- so
        # recomputing the FULL strike x expiry grid through compute_exposures_by_strike on
        # every tick (measured ~1.95s at SPXW scale) recomputes N-1 unaffected expiries'
        # worth of exposure math for nothing. Incrementally update only the expiries whose
        # own contracts were actually overlaid this call, through the SAME canonical faucet
        # (project_gamma_surface_update_expiry), falling back to one full recompute the
        # instant that cannot be done SAFELY (no cached surface to update from, or a
        # strike/expiry shape the incremental splice does not recognize) -- never a
        # shape-mismatched or approximated surface.
        _sym_to_exp = {ct.get("symbol"): str(ct.get("expirationDate") or "")[:10]
                      for ct in overlaid if isinstance(ct, dict) and ct.get("symbol")}
        affected_expiries = sorted({
            _sym_to_exp[s] for s in _overlaid_syms_now
            if s in _sym_to_exp and len(_sym_to_exp[s]) == 10
        })
        # The spot `prior_gamma_surface` (and, by construction, `prior_per_strike`/
        # `prior_per_strike_by_expiry` — always co-written with it, in this function and in
        # _terrain_refresh_one alike) were themselves computed/stamped against — captured
        # ONCE here, never re-derived from an intermediate splice result further down (whose
        # own dict has no "spot" key until the caller stamps the FINAL result). Both
        # incremental attempts below are validated against this SAME prior identity.
        _prior_spot = prior_gamma_surface.get("spot") if prior_gamma_surface is not None else None
        new_surface = None
        if prior_gamma_surface is not None:
            _incremental = prior_gamma_surface
            for _exp in affected_expiries:
                _updated = project_gamma_surface_update_expiry(
                    _incremental, overlaid, spot, _exp, prior_spot=_prior_spot)
                if _updated is None:
                    _incremental = None
                    break
                _incremental = _updated
            if _incremental is not None and affected_expiries:
                new_surface = _incremental
        if new_surface is None:
            new_surface = project_gamma_surface(overlaid, spot)
        # Audit follow-up (2026-09-16): the per-strike 'all' aggregate is a DEPENDENT
        # aggregate of the surface (the same underlying exposure math, rolled up by strike
        # across every expiry) -- it must not be recomputed over the whole chain on every
        # tick either, once the surface itself no longer is. Same incremental-with-fallback
        # contract as the surface above; see _per_strike_view_update_expiry's docstring for
        # the scope this covers (the 'all' rows only; 'near'/'far' carry over to the next
        # REST cycle).
        new_per_strike = None
        new_per_strike_by_expiry = None
        _incremental_ps = _per_strike_view_update_expiry(
            prior_per_strike_by_expiry, prior_per_strike, overlaid, spot, affected_expiries,
            prior_spot=_prior_spot)
        if _incremental_ps is not None:
            new_per_strike, new_per_strike_by_expiry = _incremental_ps
        if new_per_strike is None:
            new_per_strike_by_expiry = {}
            new_per_strike = _psv._per_strike_view_from_contracts(
                overlaid, spot, by_expiry_out=new_per_strike_by_expiry)
        if new_surface is not None:
            # ONE spot faucet (operator directive, 2026-09-15): stamp the EXACT resolve_spot
            # result this cycle used, same convention as _terrain_refresh_one's own stamp --
            # a reader of this surface (by its own surface_seq generation) sees the identical
            # value/source/as-of that actually produced these numbers, never a mix of "cells
            # computed from a fresh plane tick" and "top-level spot field still showing the
            # last REST cycle's number."
            new_surface["spot"] = float(spot)
            new_surface["spot_source"] = spot_source
            new_surface["spot_as_of_ts_utc"] = spot_ts
            # Always-live heatmap mandate (2026-09-15): the eager per-tick refresh path gets
            # the SAME per-cell stream-state stamp as the REST cycle (_terrain_refresh_one) --
            # this is the path a genuinely fresh tick actually takes, so it is the one MOST
            # likely to move a cell from 'stale'/'unavailable' into 'live'.
            from app.options.order_flow.streaming import (
                read_producer_rejected_option_contracts, is_option_producer_daemon_available)
            _gss._stamp_gamma_surface_cell_stream_state(
                new_surface, streamed, set(_overlaid_syms_now),
                read_producer_rejected_option_contracts(),
                set(_gss._desired_option_symbols_for_ticker(tk)),
                daemon_available=is_option_producer_daemon_available())
            try:
                # Best-effort enhancement -- a bug here must never block publishing an
                # otherwise-genuinely-fresh eager refresh.
                _srv._backfill_gex_cells_from_last_valid(tk, new_surface)
            except Exception as _bf_e:  # institutional-swallow-ok: never load-bearing
                log.debug("gex snapshot backfill skipped for %s: %s", tk, _bf_e)
        # RC-UI-2 latency label (independent-review finding 2026-09-12): this timestamp is the
        # instant the OVERLAID computation finished and was about to be offered for cache
        # publication — it is NOT when the browser received or rendered anything, and it
        # excludes the compare-and-swap / lock / transport / render legs entirely. Named and
        # documented for exactly what it measures, not what it does not.
        applied_ts = time.time()
        if new_surface is not None:
            new_surface["stream_overlay_contracts"] = n
            # A SIXTH independent review (2026-09-13): see _overlaid_symbols's own docstring
            # finding -- the count alone let one overlaid contract on an unrelated expiry
            # promote every OTHER currently-accepted column to 'observed' too. Named here so
            # a client can bind that promotion to the specific symbols actually freshened.
            new_surface["stream_overlay_symbols"] = _overlaid_syms_now
            new_surface["stream_overlay_computed_ts_utc"] = applied_ts
            if ts_recv:
                new_surface["stream_overlay_receipt_to_computed_ms"] = round((applied_ts - ts_recv) * 1000.0, 1)
        # RC-570 (2026-09-21, live-RTH finding): this function used to refresh ONLY
        # `_gamma_surface`/`_per_strike` on every qualifying tick -- Key Levels'
        # own fields (gamma_flip, call_wall, put_wall, absolute_gamma_strike,
        # net_gex_peak, gsf/grc, and everything else terrain_engine.compute_terrain
        # produces) stayed frozen at whatever the last ~60s REST cycle
        # (_terrain_refresh_one) computed, even while the heatmap cells right next to
        # them updated per-tick. The operator's own words: "all tickers need to work...
        # everything needs to work universally" and the explicit demand that the UI
        # actually be live, not just the heatmap grid. Same canonical faucet
        # (terrain_engine.compute_terrain) the REST cycle already uses, on the SAME
        # freshly-overlaid contracts + resolved spot this function already computed for
        # the surface -- no second exposure formula, no second vendor call, just a
        # second CONSUMER of data already in hand. Best-effort: a failure here degrades
        # to "Key Levels waits for the next REST cycle," never to no heatmap update at
        # all -- the surface/per-strike publication below does not depend on this
        # succeeding.
        new_terrain_fields: dict | None = None
        try:
            _terrain_snap = compute_terrain(tk, overlaid, spot)
            new_terrain_fields = _terrain_snap.to_dict()
        except Exception as _terr_e:  # institutional-swallow-ok: never load-bearing
            log.debug("eager terrain refresh skipped for %s: %s", tk, _terr_e)
        with terrain_state._terrain_cache_lock:
            payload = terrain_state._terrain_cache.get(tk)
            if payload is None:      # evicted/replaced between the read above and now
                return "cache_evicted"
            if payload.get("_contracts_rest_computed_ts") != read_generation:
                # A REST cycle published a NEWER generation while this ran on the OLD baseline.
                # That generation's own numbers are already correct and current; publishing
                # this stale-baseline result over them would silently regress the cache to
                # older data while claiming success. Discard rather than overwrite.
                return "stale_baseline_superseded"
            seq = _gss._next_gamma_surface_seq(tk)
            if new_surface is not None:
                new_surface["surface_seq"] = seq
            payload["_gamma_surface"] = new_surface
            payload["_per_strike"] = new_per_strike
            payload["_per_strike_expiry_raw"] = new_per_strike_by_expiry
            payload["_per_strike_expiry_raw_generation"] = read_generation
            if new_terrain_fields is not None:
                payload.update(new_terrain_fields)
                payload["computed_ts_utc"] = applied_ts
            # RC-571 follow-up (operator directive, 2026-09-21: "this live fix applied to
            # the app repo wide... i better not find out you only made targeted fixes"):
            # /api/options/vanna-by-strike and /api/options/charm-by-strike
            # (_live_terrain_contracts_and_spot) read `_contracts_rest`/`_contracts_rest_spot`
            # -- the RAW REST baseline -- and NEVER this function's tick-overlaid contracts,
            # so those two panels stayed bound to the REST cycle no matter how fast options
            # ticked, even after gamma_flip/walls/heatmap all went live above. Persisting the
            # SAME `overlaid`/`spot` this call already computed (never a second computation)
            # so those endpoints can prefer it too.
            payload["_contracts_overlaid"] = overlaid
            payload["_contracts_overlaid_spot"] = spot
            payload["_contracts_overlaid_computed_ts_utc"] = applied_ts
        return "ok"
    except Exception as e:  # never let a best-effort freshening take the feed loop down
        log.debug("refresh_gamma_surface_from_stream failed for %s: %s", contract_symbol, e)
        return f"error:{type(e).__name__}"


def refresh_gamma_surface_from_spot_tick(ticker: str) -> str:
    """CONFIRMED ROOT DEFECT (2026-09-17): the header's spot updates on every streamed
    LEVELONE_EQUITIES tick (live_market_plane -> resolve_spot's own top-priority source),
    but NOTHING downstream of that path ever re-ran the gamma exposure math —
    refresh_gamma_surface_from_stream fires ONLY on a streamed OPTION contract's own
    greeks tick (app.options.order_flow.streaming's `_streamed_greeks_hook`), a
    completely independent signal. A quiet options market with an actively-moving
    underlying could show a fresh, correct, ticking header spot over a heatmap whose
    every dollar cell was still priced off spot from up to ~60s ago (the next terrain
    REST cycle) — GEX/DEX/OI$ all scale with spot (gamma exposure by spot SQUARED), so
    this is a real, visible correctness defect, not merely a latency one.

    This is the SYMMETRIC sibling of refresh_gamma_surface_from_stream: same trigger
    SHAPE (a streamed tick, eagerly freshening a cached surface between REST cycles),
    different trigger SIGNAL (canonical spot changed, not an option's own greeks).
    Registered as app.options.order_flow.streaming.start_order_flow_stream's
    `on_tick_callback` (an EXISTING, already-built hook for exactly this equity-tick
    signal that was simply never wired to anything) via the coalesced dispatcher
    `_dispatch_spot_gamma_refresh`, which is what actually keeps this off the capture
    ingestion path — this function itself is a plain, potentially-slow, synchronous
    call, exactly like refresh_gamma_surface_from_stream is once its own caller has
    already moved it to a background thread.

    A spot change invalidates EVERY expiry's dollar values simultaneously — this ALWAYS
    performs a full project_gamma_surface recompute, never
    project_gamma_surface_update_expiry's per-expiry splice (which would, correctly,
    refuse via its own `prior_spot` identity guard anyway; this path does not even
    attempt it, since "spot moved" is precisely the condition that guard exists to
    catch). Per-strike is refreshed the identical way, for the identical reason.

    No-ops (returns a diagnostic status, never raises) when: there is no cached ticker
    at all (nothing to refresh — the next REST cycle seeds it), there is no prior
    surface yet, canonical spot is unavailable, or canonical spot is UNCHANGED since the
    surface's own stamped value (exact identity, not a tolerance — requirement: never an
    unnecessary full-surface recomputation when nothing actually moved). Publishes
    through the SAME REST-baseline compare-and-swap (`_contracts_rest_computed_ts`)
    refresh_gamma_surface_from_stream already uses, so a late/superseded computation can
    only ever be silently discarded, never corrupt a newer result."""
    import server as _srv

    try:
        tk = ticker_storage_key(ticker or "")
        if not tk:
            return "no_ticker"
        with terrain_state._terrain_cache_lock:
            payload = terrain_state._terrain_cache.get(tk)
            if payload is None:
                return "no_cached_ticker"
            base_contracts = payload.get("_contracts_rest")
            read_generation = payload.get("_contracts_rest_computed_ts")
            prior_gamma_surface = payload.get("_gamma_surface")
        if not base_contracts:
            return "no_rest_baseline"
        if prior_gamma_surface is None:
            return "no_prior_surface"
        prior_spot = prior_gamma_surface.get("spot")
        spot, spot_source, spot_ts = _srv.resolve_spot(tk)
        if not spot:
            return "no_current_spot"
        if prior_spot is not None and float(prior_spot) == float(spot):
            return "spot_unchanged"
        # Overlay every currently-desired contract's freshest streamed greeks onto the
        # untouched REST baseline — the SAME overlay refresh_gamma_surface_from_stream
        # uses, so an option contract's own tick freshness is respected here too, even
        # though THIS call was triggered by spot, not by that contract's own tick.
        from math_exposure_core import overlay_streamed_contract_fields
        streamed = _gss._desired_stream_greeks_for_ticker(tk)
        overlaid, n = overlay_streamed_contract_fields(
            base_contracts, streamed,
            newer_than_ts=read_generation, max_staleness_sec=_gss.GAMMA_SURFACE_STREAM_STALENESS_SEC)
        _overlaid_syms_now = _gss._overlaid_symbols(base_contracts, overlaid)
        new_surface = project_gamma_surface(overlaid, spot)
        new_surface["spot"] = float(spot)
        new_surface["spot_source"] = spot_source
        new_surface["spot_as_of_ts_utc"] = spot_ts
        from app.options.order_flow.streaming import (
            read_producer_rejected_option_contracts, is_option_producer_daemon_available)
        _gss._stamp_gamma_surface_cell_stream_state(
            new_surface, streamed, set(_overlaid_syms_now),
            read_producer_rejected_option_contracts(),
            set(_gss._desired_option_symbols_for_ticker(tk)),
            daemon_available=is_option_producer_daemon_available())
        try:
            _srv._backfill_gex_cells_from_last_valid(tk, new_surface)
        except Exception as _bf_e:  # institutional-swallow-ok: never load-bearing
            log.debug("gex snapshot backfill skipped for %s: %s", tk, _bf_e)
        applied_ts = time.time()
        new_surface["stream_overlay_contracts"] = n
        new_surface["stream_overlay_symbols"] = _overlaid_syms_now
        new_surface["stream_overlay_computed_ts_utc"] = applied_ts
        new_surface["spot_tick_triggered"] = True   # disclosure: this generation was
        # published by a spot tick, not an option tick or the REST cycle -- diagnostic
        # only, never load-bearing for any gate.
        # The per-strike aggregate is equally spot-dependent for every expiry — always a
        # full recompute here too, never an incremental per-expiry merge.
        new_per_strike_by_expiry: dict = {}
        new_per_strike = _psv._per_strike_view_from_contracts(
            overlaid, spot, by_expiry_out=new_per_strike_by_expiry)
        # RC-570 (2026-09-21, operator directive: "this live fix applied to the app repo
        # wide... i better not find out you only made targeted fixes"): this function is
        # refresh_gamma_surface_from_stream's own documented SYMMETRIC SIBLING (same
        # trigger shape, different signal) and carried the IDENTICAL gap -- Key Levels
        # (gamma_flip/walls/pin/etc.) never refreshed on a spot tick either, even though a
        # moving underlying invalidates every dollar value on that panel too (GEX scales
        # by spot SQUARED, per this function's own docstring). Same canonical faucet, same
        # freshly-overlaid contracts and spot this call already computed for the surface --
        # no second exposure formula, no second vendor call.
        new_terrain_fields: dict | None = None
        try:
            _terrain_snap = compute_terrain(tk, overlaid, spot)
            new_terrain_fields = _terrain_snap.to_dict()
        except Exception as _terr_e:  # institutional-swallow-ok: never load-bearing
            log.debug("eager terrain refresh (spot tick) skipped for %s: %s", tk, _terr_e)
        with terrain_state._terrain_cache_lock:
            payload = terrain_state._terrain_cache.get(tk)
            if payload is None:
                return "cache_evicted"
            if payload.get("_contracts_rest_computed_ts") != read_generation:
                return "stale_baseline_superseded"
            new_surface["surface_seq"] = _gss._next_gamma_surface_seq(tk)
            payload["_gamma_surface"] = new_surface
            payload["_per_strike"] = new_per_strike
            payload["_per_strike_expiry_raw"] = new_per_strike_by_expiry
            payload["_per_strike_expiry_raw_generation"] = read_generation
            if new_terrain_fields is not None:
                payload.update(new_terrain_fields)
                payload["computed_ts_utc"] = applied_ts
            # Same Vanna/Charm-by-strike fix as refresh_gamma_surface_from_stream: persist
            # the overlaid contracts so _live_terrain_contracts_and_spot can prefer them
            # over the REST-only baseline for THIS trigger path too.
            payload["_contracts_overlaid"] = overlaid
            payload["_contracts_overlaid_spot"] = spot
            payload["_contracts_overlaid_computed_ts_utc"] = applied_ts
        return "ok"
    except Exception as e:  # never let a best-effort freshening take the feed loop down
        log.debug("refresh_gamma_surface_from_spot_tick failed for %s: %s", ticker, e)
        return f"error:{type(e).__name__}"


# RC-REHAB-1 (2026-09-23, forty-second slice): the coalesced spot-tick dispatcher moved here
# from server.py, beside the refresh it dispatches.
#: Coalesced per-ticker dispatch for refresh_gamma_surface_from_spot_tick (2026-09-17).
#: One lifecycle owner (this module-level executor + state), at most one recompute in
#: flight per ticker, a tick arriving mid-flight coalesces into exactly one trailing
#: rerun (never an unbounded queue), latest-state convergence (the rerun always reads
#: CURRENT resolve_spot/_terrain_cache state fresh, never a stale captured snapshot),
#: and CAS protection via the SAME `_contracts_rest_computed_ts` compare-and-swap the
#: underlying function already publishes through. Reimplemented here (rather than
#: reusing app.options.order_flow.streaming's own option-tick hook dispatcher) because
#: that one's coalescing state is a private closure of its `_feed_loop`, not exposed for
#: reuse from this module — this is the smallest complete mechanism with the identical
#: properties, on its own dedicated single-worker executor so a slow recompute never
#: blocks the daemon-plane-feed's own DB-read thread that calls this callback.
_spot_gamma_refresh_executor: "ThreadPoolExecutor | None" = None
_spot_gamma_refresh_inflight: "set[str]" = set()
_spot_gamma_refresh_pending: "set[str]" = set()
_spot_gamma_refresh_lock = threading.Lock()


def _get_spot_gamma_refresh_executor() -> ThreadPoolExecutor:
    global _spot_gamma_refresh_executor
    if _spot_gamma_refresh_executor is None:
        _spot_gamma_refresh_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="spot-gamma-refresh")
    return _spot_gamma_refresh_executor


def _run_spot_gamma_refresh(tk: str) -> None:
    try:
        refresh_gamma_surface_from_spot_tick(tk)
    except Exception as e:  # institutional-swallow-ok: best-effort background refresh, never load-bearing
        log.debug("spot-triggered gamma refresh failed for %s: %s", tk, e)
    finally:
        rerun = False
        with _spot_gamma_refresh_lock:
            _spot_gamma_refresh_inflight.discard(tk)
            if tk in _spot_gamma_refresh_pending:
                _spot_gamma_refresh_pending.discard(tk)
                _spot_gamma_refresh_inflight.add(tk)
                rerun = True
    if rerun:
        _get_spot_gamma_refresh_executor().submit(_run_spot_gamma_refresh, tk)


def _dispatch_spot_gamma_refresh(ticker: str) -> None:
    """Registered as start_order_flow_stream's `on_tick_callback` — invoked synchronously,
    per qualifying equity row, on the daemon-plane-feed's own single-worker DB executor
    thread (app.options.order_flow.streaming._feed_loop). Must return immediately: all
    this does is coalesce-and-submit to this module's own dedicated executor, never the
    recompute itself."""
    try:
        tk = ticker_storage_key(ticker or "")
    except Exception:  # institutional-swallow-ok: a malformed ticker is simply skipped
        return
    if not tk:
        return
    with _spot_gamma_refresh_lock:
        if tk in _spot_gamma_refresh_inflight:
            _spot_gamma_refresh_pending.add(tk)
            return
        _spot_gamma_refresh_inflight.add(tk)
    _get_spot_gamma_refresh_executor().submit(_run_spot_gamma_refresh, tk)
