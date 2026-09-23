"""Live repricing of the cached terrain snapshot: re-reads spot and re-derives the spot-relative
read (gamma at price, wall geometry, the terrain read) against the SAME cached wide chain the
producer computed, and the cached contracts + live spot pair the gamma-surface route and the
eager refresh project from. Extracted from server.py (RC-REHAB-1, 2026-09-23, forty-eighth
slice). Spot comes from server's resolve_spot / current_spot_state via a lazy import.
"""
from __future__ import annotations

import terrain_state
from instrument_identity import ticker_storage_key
from math_exposure import gamma_at_price
from terrain_engine import wall_geometry_state
from terrain_freshness import terrain_staleness
from terrain_read import build_terrain_read


def _reprice_cached_terrain(payload: dict, ticker: str) -> dict:
    """Serve CACHED LEVELS against a LIVE SPOT.

    RC-28: levels move slowly (a 60 s loop is right for them) but spot moves continuously,
    and spot was frozen into the cached payload. The card therefore ran up to 75 s behind
    the header -- observed 745.10 on the card against 744.88 live.

    Levels, walls and the profile stay as cached. Spot is re-resolved every request, and
    the REGIME is recomputed as the sign of the cached profile at that fresh spot, so the
    regime can never disagree with the price shown beside it.
    """
    import server as _srv

    spot, spot_source, spot_ts = _srv.resolve_spot(ticker)
    if spot is None:
        out = dict(payload)
        out["spot"] = None
        out["spot_source"] = "none"
        out["spot_state"] = "unavailable"
        out["spot_as_of_ts_utc"] = None
        out["spot_disp"] = "UNAVAILABLE"
        return out

    out = dict(payload)
    out["spot"] = spot
    out["spot_source"] = spot_source
    out["spot_state"] = _srv.current_spot_state(spot_source, ticker)
    out["spot_as_of_ts_utc"] = spot_ts
    # RC-130: wall geometry states are a function of SPOT, which was just re-resolved —
    # recomputed with the SAME producer definition (wall_geometry_state), and BEFORE the
    # profile early-return below, or a wall crossed intra-cycle would keep claiming the
    # containment the painted spot contradicts. Needs only spot + the cached walls.
    out["call_wall_state"] = wall_geometry_state(spot, payload.get("call_wall"), "call")
    out["put_wall_state"] = wall_geometry_state(spot, payload.get("put_wall"), "put")

    profile = terrain_state._terrain_profile_cache.get(ticker_storage_key(ticker))  # RC-345/F25: read key matches canonical write (tk)
    if not profile:
        return out                      # levels stand; regime left as cached

    fresh_gamma = gamma_at_price(profile, spot)
    read = build_terrain_read(
        spot=spot,
        flip=payload.get("gamma_flip"),
        flip_confidence=payload.get("confidence") or "UNAVAILABLE",
        put_wall=payload.get("put_wall"),
        call_wall=payload.get("call_wall"),
        gamma_at_spot=fresh_gamma,
        ticker=ticker,   # SIGN-DEMOTION: single names get regime withheld, levels stand
    )
    out["regime"] = read.regime
    out["posture"] = read.posture
    out["headline"] = read.headline
    out["lines"] = read.lines
    # flip_diag travels WITH the regime it justified. The regime above was recomputed at
    # the fresh spot but flip_diag still carried the loop-time gamma_at_spot, so the
    # dealer tile printed a stale γ beside a live regime — the two could even disagree in
    # sign (Bugbot 2026-07-20, confirmed: the UI renders flip_diag.gamma_at_spot).
    out["flip_diag"] = {**(payload.get("flip_diag") or {}), "gamma_at_spot": fresh_gamma}
    # net_gex_at_spot IS gamma_at_spot (schema v2) — reprice both or the NET GEX chip
    # would show loop-time gamma beside a live-spot regime (same defect class as above).
    out["net_gex_at_spot"] = fresh_gamma
    # RC-91: the levels are cached and the spot is live, so the payload must say HOW OLD the
    # levels are rather than let a live price imply live structure. Every consumer gets the age,
    # a stale flag and the reason — absence of the flag is not permission to assume currency.
    out.update(terrain_staleness(payload.get("computed_ts_utc"), ticker))
    return out


def _live_terrain_contracts_and_spot(tk: str) -> tuple[list | None, float | None]:
    """The SAME live wide chain + live spot the terrain loop already fetched THIS cycle for
    `tk` (_terrain_cache[tk]["_contracts_rest"]/["_contracts_rest_spot"]) -- zero extra
    vendor calls, ONE FAUCET. None/None when the ticker has not been viewed/warmed (the
    cache entry, or that specific field, does not exist yet) — callers fail closed to
    'unavailable', never to a banked/stale substitute silently presented as live.

    Repo-wide spot audit (operator directive, 2026-09-15): `_contracts_rest_spot` reads like
    the same stale-cache pattern that was the root cause of the (now-fixed)
    refresh_gamma_surface_from_stream bug, but it is NOT a second spot selector -- it is the
    EXACT resolve_spot() result _terrain_refresh_one already stamped onto THIS SAME chain
    generation (see its call site: resolve_spot() runs, then both
    `_contracts_rest`=chain and `_contracts_rest_spot`=that same result are written together
    in one cycle). Vanna/charm-by-strike need spot and chain to reconcile to the identical
    observation instant; calling resolve_spot() fresh here could return a NEWER value than
    the cached chain reflects, which would silently reintroduce a chain/spot generation
    mismatch -- the opposite failure mode from the bug that was fixed. This is the
    "historical spot stamped on a completed surface may remain provenance" carve-out, not a
    duplicate authority: the value traces to exactly one resolve_spot() call, never a second
    computation.

    RC-571 follow-up (2026-09-21): prefers `_contracts_overlaid`/`_contracts_overlaid_spot`
    -- refresh_gamma_surface_from_stream's own per-tick-freshened contracts, the SAME ones
    the heatmap/Key Levels now read live -- over the REST-cycle-only `_contracts_rest`, so
    Vanna/Charm-by-strike are no longer the one pair of panels still bound exclusively to
    the REST floor while everything else derived from this same cache went live. Both
    fields are written together, from the same call, exactly like `_contracts_rest`/
    `_contracts_rest_spot` always have been -- one generation, never a chain/spot mismatch.
    Falls back to `_contracts_rest`/`_contracts_rest_spot` whenever no tick has overlaid
    this ticker yet (a cold cache, or one with no actively-streamed contract) -- the
    existing REST-only behavior, unchanged for that case.
    """
    with terrain_state._terrain_cache_lock:
        payload = terrain_state._terrain_cache.get(tk) or {}
        contracts = payload.get("_contracts_overlaid") or payload.get("_contracts_rest")
        spot = payload.get("_contracts_overlaid_spot")
        if spot is None:
            spot = payload.get("_contracts_rest_spot")
    if not contracts or spot is None:
        return None, None
    return contracts, float(spot)
