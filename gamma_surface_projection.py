"""Gamma-surface (strike x expiry net_gex_1pct grid) projection, extracted out of
server.py (RC-REHAB-1, 2026-09-23), twenty-fourth real module-level slice of the
server.py decomposition.

Unlike the server_state_*.py siblings (server_state_volatility.py,
server_state_candles.py, server_state_signals.py, server_state_order_flow.py,
server_state_persistence_tail.py, server_state_predictive_positioning.py,
server_state_vol_envelope_sector.py, server_state_exposures.py -- each one a phase
of _fetch_state's own body), this module is NOT part of the _fetch_state cycle. It is
called from three independent places (the terrain-refresh loop, the streamed-tick
eager-refresh path, and the /api/options/gamma-surface route's banked-morning
fallback) -- a standalone projection utility, not a fetch_state sub-phase, so it gets
its own top-level name instead of the server_state_ prefix.

project_gamma_surface/project_gamma_surface_update_expiry (the public API, called
from server.py's refresh_gamma_surface_from_stream/refresh_gamma_surface_from_
spot_tick/_terrain_refresh_one, and externally via `from server import
project_gamma_surface` in app/api/routes/options.py) and their three private helpers
(_project_gamma_expiry_slice, _gamma_surface_cell_fields,
_gamma_surface_unavailable_reason -- each confirmed to have no OTHER caller anywhere
in server.py before moving) move together as one unit. _backfill_gex_cells_from_
last_valid/_flush_last_valid_gex_cells_to_db (immediately above this group in the
original file) are a SEPARATE concern -- last-valid-value DB backfill, not chain->grid
projection -- and deliberately stay in server.py, not bundled in here just because
they were adjacent.

MONKEYPATCH/RUNTIME-STATE NOTE: _expiries_from_contracts (2 other internal callers
plus an external `from server import _expiries_from_contracts` caller in
app/api/routes/debug.py) and _filter_contracts_by_selected_expiry (one other internal
caller, inside _fetch_state's own body) both stay in server.py, reached via the
established lazy `import server` pattern proven in prior slices.
math_exposure_core.compute_exposures_by_strike and numeric_contract.
float_finite_or_none were already lazily imported inline inside the function bodies
in the original code and stay that way, unchanged.
"""
from __future__ import annotations


def _project_gamma_expiry_slice(chain: list, e: str, spot: float):
    """Compute ONE expiry's strike-bucketed exposures through the canonical faucet
    (extracted 2026-09-16 from project_gamma_surface, audit finding #2, so
    project_gamma_surface_update_expiry can call the identical per-expiry logic on a
    single expiry instead of duplicating a second computation). Returns
    (exposures_e, sym_map, dte) or None if this expiry's slice is unusable (no native
    schwab_expirationDate match, or empty) — the caller's job to decide what "unusable"
    means for its own shape (project_gamma_surface skips it; the incremental update
    falls back to a full recompute)."""
    import server as _srv
    from math_exposure_core import compute_exposures_by_strike as _cebs
    from numeric_contract import float_finite_or_none

    slice_e, slice_src = _srv._filter_contracts_by_selected_expiry(chain, e)
    if slice_src != "schwab_expirationDate" or not slice_e:
        return None
    # THE canonical faucet — identical call the selected-expiry analytics path uses
    exposures_e, _diag_e = _cebs(slice_e, spot=spot, require_oi=True)
    dte: "int | None" = None
    sym_map: dict[float, dict[str, str]] = {}
    for ct in slice_e:  # native DTE for the column header, never inferred
        if dte is None:
            _d = ct.get("daysToExpiration")
            if _d is not None:
                try:
                    dte = int(_d)
                except (TypeError, ValueError):
                    pass
        side = (ct.get("putCall") or "").upper()
        sym = ct.get("symbol")
        # Same canonical vendor-numeric coercion compute_exposures_by_strike itself uses
        # for this exact field (math_exposure_core._f -> float_finite_or_none) — a raw
        # float() here would be a second, ad-hoc coercion authority for a Schwab vendor
        # field.
        _sk = float_finite_or_none(ct.get("strikePrice"))
        if sym and side in ("CALL", "PUT") and _sk is not None:
            sym_map.setdefault(_sk, {})[side.lower()] = str(sym)
    return exposures_e, sym_map, dte, len(slice_e)


def _gamma_surface_cell_fields(bucket: "dict | None", syms: "dict | None"):
    """Shape ONE (strike, expiry) cell's gex/dex/vanna/oi/volume/contracts fields from its
    compute_exposures_by_strike bucket (extracted 2026-09-16 alongside
    _project_gamma_expiry_slice — see that function's docstring; this is the OTHER half
    project_gamma_surface's per-cell loop used to inline, now shared with the incremental
    update path so both produce byte-identical cells from the same bucket). Returns
    (gex, dex, vanna, oi, volume, contracts, has_gex_data, has_oi) — see
    project_gamma_surface's own inline comments (moved here verbatim) for why each gate
    exists."""
    from numeric_contract import float_finite_or_none

    def _bf(v):
        fv = float_finite_or_none(v)
        return round(fv) if fv is not None else None

    syms = syms or {}
    _has_oi = bool(bucket is not None and bucket.get("has_oi"))
    _has_gex_data = bool(_has_oi and bucket.get("has_valid_gamma"))
    gex = _bf(bucket.get("net_gex_1pct")) if _has_gex_data else None
    dex = _bf(bucket.get("net_dex_dollars")) if _has_gex_data else None
    _vn = bucket["call_vanna"] - bucket["put_vanna"] if _has_gex_data else None
    vanna = round(_vn, 2) if _vn is not None else None
    call_oi, put_oi = (bucket or {}).get("call_oi"), (bucket or {}).get("put_oi")
    oi = {"call": _bf(call_oi), "put": _bf(put_oi)} if bucket is not None else {"call": None, "put": None}
    call_vol, put_vol = (bucket or {}).get("call_volume"), (bucket or {}).get("put_volume")
    volume = {"call": _bf(call_vol), "put": _bf(put_vol)} if bucket is not None else {"call": None, "put": None}
    contracts = {"call": syms.get("call"), "put": syms.get("put")}
    return gex, dex, vanna, oi, volume, contracts, _has_gex_data, _has_oi


def project_gamma_surface(chain: list, spot: float) -> dict:
    """PURE projection of a wide chain into a strike × expiry net_gex_1pct grid.

    Owns only orchestration/shaping — NO exposure math. Every cell is produced by the one
    canonical authority ``math_exposure_core.compute_exposures_by_strike`` run on the native
    ``expirationDate`` slice for that expiry (via the existing _filter_contracts_by_selected_expiry
    helper). Because the faucet buckets each contract independently, summing per-expiry cells at
    a strike reconciles exactly to the full-book value at that strike (same spot). Contracts with
    malformed/missing native expiry are excluded and counted — never reassigned to a column."""
    import server as _srv

    total_contracts = len(chain) if isinstance(chain, list) else 0
    expiries = _srv._expiries_from_contracts(chain)
    valid_exp_keys = {str(e)[:10] for e in expiries}
    excluded_malformed = sum(
        1 for ct in (chain or [])
        if str((ct or {}).get("expirationDate") or "")[:10] not in valid_exp_keys
    )

    strike_set: set[float] = set()
    per_expiry: dict[str, dict] = {}
    exp_dte: dict[str, int | None] = {}
    # Live-heatmap coverage (state-authority review, 2026-09-12): the heatmap grid itself
    # had no per-cell contract identity, so nothing could ever ask the streaming layer to
    # keep its VISIBLE cells fresh sub-second -- only whatever ONE strike Strike Detail had
    # separately selected ever streamed live. This is the vendor OSI symbol already present
    # on each native contract (never invented, never a second identity authority), carried
    # alongside the existing net_gex_1pct aggregate so the browser can ask for exactly the
    # contracts backing what it is actually showing. Never fed into compute_exposures_by_
    # strike (the canonical exposure-math faucet stays untouched) -- a plain per-(strike,
    # expiry) lookup built from the same `slice_e` this loop already holds.
    symbols_by_expiry: dict[str, dict[float, dict[str, str]]] = {}
    contracts_used = 0
    for e in expiries:
        _slice = _project_gamma_expiry_slice(chain, e, spot)
        if _slice is None:
            continue
        exposures_e, sym_map, dte, n_used = _slice
        per_expiry[e] = exposures_e
        contracts_used += n_used
        for k in exposures_e.keys():
            strike_set.add(float(k))
        exp_dte[e] = dte
        symbols_by_expiry[e] = sym_map

    strikes = sorted(strike_set)
    expirations = [{"expiry": e, "dte": exp_dte.get(e)} for e in expiries if e in per_expiry]
    # A SEVENTH independent review (2026-09-13, operator field-inventory audit): this loop
    # already builds `bucket` (== compute_exposures_by_strike's own per-(strike,expiry)-slice
    # dict) for every cell to read ONE field (net_gex_1pct) out of it -- but that SAME bucket
    # already carries net_dex_dollars (dollar delta exposure), call_vanna/put_vanna (BS vanna,
    # RC-211's exact-formula faucet), and call_oi/put_oi/call_volume/put_volume, computed by
    # the ONE canonical faucet every GEX cell already uses, for FREE -- no second computation,
    # no new formula. They were being discarded before ever reaching a cell. Carried through
    # here so the SAME strike x expiry grid can serve a DEX, Open Interest, or Volume measure
    # (net_gex_1pct's own siblings) without a second projection function; Vanna's own natural
    # per-cell value (call_vanna - put_vanna, matching compute_net_vanna's +call/-put dealer
    # convention) is carried too, though today's UI surfaces Vanna aggregated by strike (its
    # own aggregate-only maturity today: see AGG_$_ONLY), not yet as a per-expiry column.
    #
    # Independent-review finding, REPRODUCED (live SPX, 2026-09-14): `bucket is not None`
    # was once the ONLY gate here, but compute_exposures_by_strike creates a bucket for
    # every strike/side/multiplier-valid contract BEFORE the require_oi filter runs -- a
    # contract with a real strike and multiplier but zero/missing OI still gets a bucket,
    # just one whose net_gex_1pct/net_dex_dollars never left their pre-initialized 0.0
    # default. has_oi/has_valid_gamma (math_exposure_core.py's own canonical signals) are
    # the fix — see _gamma_surface_cell_fields, which now owns this gating for both the
    # full-surface and incremental-update paths.
    cells = []
    cells_with_data = 0
    cells_total = 0
    cells_with_oi_but_invalid_greeks = 0
    for k in strikes:
        row, dex_row, vanna_row, oi_row, vol_row, contracts_row = [], [], [], [], [], []
        for col in expirations:
            cells_total += 1
            bucket = per_expiry.get(col["expiry"], {}).get(k)
            syms = symbols_by_expiry.get(col["expiry"], {}).get(k)
            gex, dex, vanna, oi, volume, contracts, has_gex, has_oi = \
                _gamma_surface_cell_fields(bucket, syms)
            if has_gex:
                cells_with_data += 1
            elif has_oi:
                cells_with_oi_but_invalid_greeks += 1
            row.append(gex)
            dex_row.append(dex)
            vanna_row.append(vanna)
            oi_row.append(oi)
            vol_row.append(volume)
            contracts_row.append(contracts)
        cells.append({
            "strike": k, "gex": row, "dex": dex_row, "vanna": vanna_row,
            "oi": oi_row, "volume": vol_row, "contracts": contracts_row,
        })

    # Operator directive (2026-09-14, live SPX reproduction): a grid where every single cell
    # lacks usable OI is not merely "a lot of quiet cells" -- it means this ticker's exposure
    # data is unavailable end to end, and that must be a surface-level fact the caller can
    # check in one field, not something it has to infer by scanning every cell for None.
    # contracts_used > 0 alone is not enough: a wide chain can have thousands of USED
    # contracts (real strike/side/multiplier, real greeks) while still having zero cells with
    # usable OI (exactly the live SPX case this was written from) -- gamma_available is
    # gated on cells_with_data specifically, the same signal each cell's own _has_data used.
    gamma_available = cells_with_data > 0
    _reason = _gamma_surface_unavailable_reason(gamma_available, cells_with_oi_but_invalid_greeks,
                                                cells_total)
    return {
        "expirations": expirations, "strikes": strikes, "cells": cells,
        "contracts_total": total_contracts, "contracts_used": contracts_used,
        "contracts_excluded_malformed_expiry": excluded_malformed,
        "gamma_available": gamma_available,
        "gamma_unavailable_reason": _reason,
        "cells_total": cells_total,
        "cells_with_oi_but_invalid_greeks": cells_with_oi_but_invalid_greeks,
    }


def _gamma_surface_unavailable_reason(gamma_available: bool, cells_with_oi_but_invalid_greeks: int,
                                      cells_total: int) -> "str | None":
    """The ONE message for why a surface has no usable gamma this cycle (extracted
    2026-09-16 alongside _project_gamma_expiry_slice/_gamma_surface_cell_fields so
    project_gamma_surface_update_expiry reports identically to a full recompute).
    Operator directive (2026-09-15, canonical input-validity rules): distinguishes a real
    OI outage (SPX, 2026-09-14: the vendor reports zero OI) from an invalid-greeks-only
    outage (SPY/QQQ 0DTE ITM puts, 2026-09-15: OI is real, Schwab's own greeks for it are
    internally self-contradictory) — an operator reading this could not tell "there is
    nothing here" from "there is real interest but Schwab's greeks for it are unusable
    right now" before this split. Both counts are diagnostic-only, never load-bearing for
    any gate (gamma_available/cells_with_data are the actual authorities)."""
    if gamma_available:
        return None
    if cells_with_oi_but_invalid_greeks > 0:
        return (
            "real open interest exists but Schwab's own reported greeks for it are invalid "
            "this cycle ({} of {} strike×expiry cells have OI with unusable greeks)"
        ).format(cells_with_oi_but_invalid_greeks, cells_total)
    return "no usable open interest in this chain (0 of {} strike×expiry cells)".format(cells_total)


def project_gamma_surface_update_expiry(prior_surface: dict, chain: list, spot: float,
                                        target_expiry: str, *,
                                        prior_spot: "float | None") -> "dict | None":
    """Incremental sibling of project_gamma_surface (2026-09-16, audit finding #2: a
    streamed tick touches contracts belonging to exactly ONE expiry — an option symbol
    encodes its own expiry — but the eager refresh path used to re-run the full
    strike×expiry grid through compute_exposures_by_strike for EVERY expiry on every
    single tick, measured at ~1.95s at SPXW scale. This recomputes ONLY `target_expiry`'s
    strike slice, through the exact same canonical faucet
    (_project_gamma_expiry_slice/_gamma_surface_cell_fields — never a second exposure
    formula), and splices the result into a shallow COPY of `prior_surface`'s cells;
    every other expiry's cells are the SAME objects, not recomputed or even re-touched.

    `prior_surface` MUST be a surface project_gamma_surface (or this function) itself
    produced from the SAME strike/expiry set `chain` implies — true by construction in
    refresh_gamma_surface_from_stream, which builds both from the one REST-baseline
    chain. `contracts_total`/`contracts_used`/`contracts_excluded_malformed_expiry` are
    therefore copied verbatim from `prior_surface`: overlaying streamed fields onto an
    unchanged contract list never changes which contracts exist, only some of their
    field values, so those chain-shape counts cannot have moved.

    Independent-review finding (2026-09-16, follow-up mandate): net_gex_1pct/net_dex_
    dollars/net_oi_dollars/vanna are ALL functions of spot (gamma/delta/OI scaled by spot
    or spot², and vanna a genuinely non-separable closed-form function of spot via
    Black-Scholes d1/d2) — for EVERY expiry, not only `target_expiry`. Splicing in only
    the touched expiry's fresh slice while leaving every other column's cells computed
    against a STALE spot would silently show a mix of dollar values priced off different
    underlying prices the instant spot moves between two streamed ticks. `prior_spot` is
    the exact spot `prior_surface` was itself computed/stamped against (the caller's own
    cached record of it, never re-derived here); incremental reuse is safe ONLY when it is
    IDENTICAL to `spot` (this is an identity check, not a within-tolerance one — the
    slightest genuine spot movement invalidates every untouched expiry's dollar values,
    not just the touched one). `prior_spot=None` (unknown/never recorded) also forces a
    full recompute, fail-closed.

    Returns None — meaning "fall back to a full project_gamma_surface call" — whenever
    incremental splicing cannot be done SAFELY: spot has moved since `prior_surface` was
    computed (see above), `target_expiry` is not an existing column in `prior_surface` (a
    genuinely new expiry appearing must re-derive the sorted column list), or the
    recomputed slice contains a strike `prior_surface` never carried (a new strike
    appearing must re-derive the sorted row list). All three are handled the identical
    way — never silently producing a shape-mismatched or stale-spot surface; the caller
    always has the safe full recompute to fall back to."""
    if prior_spot is None or float(prior_spot) != float(spot):
        return None
    expirations = prior_surface.get("expirations") or []
    col_idx = next((i for i, e in enumerate(expirations) if e.get("expiry") == target_expiry), None)  # caps-ok: None means "expiry genuinely absent from prior_surface", checked explicitly on the next line and triggers a full-recompute fallback -- not a silent numeric default
    if col_idx is None:
        return None
    _slice = _project_gamma_expiry_slice(chain, target_expiry, spot)
    if _slice is None:
        return None
    exposures_e, sym_map, dte, _n_used = _slice
    prior_strikes = prior_surface.get("strikes") or []
    strike_index = {k: i for i, k in enumerate(prior_strikes)}

    prior_cells = prior_surface.get("cells") or []
    if len(prior_cells) != len(prior_strikes):
        return None     # shape already inconsistent -- do not compound it, fall back

    cells_with_data = 0
    cells_with_oi_but_invalid_greeks = 0
    new_cells = list(prior_cells)   # shallow: untouched strike rows are the SAME objects
    # Only strikes THIS expiry's slice actually names need a new row — the base REST chain
    # (and therefore which (strike, expiry) pairs have any contract at all) is unchanged by
    # a streamed overlay, so a strike absent from exposures_e/sym_map was equally absent
    # last time and this column's value there is already, and stays, None. Rebuilding every
    # strike's row unconditionally would touch (and reallocate) rows target_expiry never
    # affected, defeating the identity-preservation this function exists to provide.
    touched_strikes = set(exposures_e.keys()) | set(sym_map.keys())
    if any(float(k) not in strike_index for k in touched_strikes):
        return None    # a strike this expiry now reports that the prior surface never had
    for k in touched_strikes:
        i = strike_index[float(k)]
        old_cell = prior_cells[i]
        bucket = exposures_e.get(k)
        syms = sym_map.get(k)
        gex, dex, vanna, oi, volume, contracts, has_gex, has_oi = \
            _gamma_surface_cell_fields(bucket, syms)
        if has_gex:
            cells_with_data += 1
        elif has_oi:
            cells_with_oi_but_invalid_greeks += 1
        new_row = dict(old_cell)
        for field, value in (("gex", gex), ("dex", dex), ("vanna", vanna),
                             ("oi", oi), ("volume", volume), ("contracts", contracts)):
            col = list(old_cell.get(field) or [])
            if col_idx >= len(col):
                return None      # column count disagrees with `expirations` -- fall back
            col[col_idx] = value
            new_row[field] = col
        new_cells[i] = new_row

    # Every OTHER column's own cells_with_data/cells_with_oi_but_invalid_greeks contribution
    # is read back out of the UNTOUCHED cells this function never recomputed — a cheap scan
    # over already-computed values, not exposure math, so this stays genuinely incremental.
    other_cols_with_data = 0
    other_cols_invalid_oi = 0
    for j, e in enumerate(expirations):
        if j == col_idx:
            continue
        for cell in new_cells:
            gex_row = cell.get("gex") or []
            oi_row = cell.get("oi") or []
            if j < len(gex_row) and gex_row[j] is not None:
                other_cols_with_data += 1
            elif j < len(oi_row) and isinstance(oi_row[j], dict) and (
                    oi_row[j].get("call") or oi_row[j].get("put")):
                other_cols_invalid_oi += 1
    total_cells_with_data = other_cols_with_data + cells_with_data
    total_invalid_oi = other_cols_invalid_oi + cells_with_oi_but_invalid_greeks
    cells_total = int(prior_surface.get("cells_total") or (len(new_cells) * len(expirations)))
    gamma_available = total_cells_with_data > 0
    return {
        "expirations": expirations, "strikes": prior_strikes, "cells": new_cells,
        "contracts_total": prior_surface.get("contracts_total"),
        "contracts_used": prior_surface.get("contracts_used"),
        "contracts_excluded_malformed_expiry": prior_surface.get("contracts_excluded_malformed_expiry"),
        "gamma_available": gamma_available,
        "gamma_unavailable_reason": _gamma_surface_unavailable_reason(
            gamma_available, total_invalid_oi, cells_total),
        "cells_total": cells_total,
        "cells_with_oi_but_invalid_greeks": total_invalid_oi,
    }
