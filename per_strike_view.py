"""Per-strike exposure view built from option contracts: exposures computed per expiry, merged
across expiries, then shaped into the per-strike scopes the terrain payload serves
(`_per_strike_view_from_contracts`). Extracted from server.py (RC-REHAB-1, 2026-09-23,
forty-second slice) as one cohesive private group; its callers are terrain_refresh.py and
gamma_surface_eager_refresh.py. Pure: no server runtime state.
"""
from __future__ import annotations


def _contract_expiry_str(ct: dict) -> str:
    return str((ct or {}).get("expirationDate") or "")[:10]


def _per_strike_exposures_by_expiry(contracts: list, spot: float) -> "dict[str, dict]":
    """Partition `contracts` by their own `expirationDate` and run the SAME canonical faucet
    (compute_exposures_by_strike) once per partition, returning {expiry: exposures_dict}.

    2026-09-16 audit follow-up: this is the building block for an incremental per-strike
    update, mirroring project_gamma_surface_update_expiry's per-expiry splice for the
    strike x expiry surface. `_merge_all_expiry_exposures` sums these back into the exact
    same total compute_exposures_by_strike(contracts, ...) would produce in one call —
    because every field that function accumulates is a plain per-contract sum, or an OR of
    a per-contract boolean (see its own body: call_oi/call_delta/call_gamma/.../put_* are
    running sums; has_oi/has_valid_gamma are booleans; net_gamma/net_delta/net_dex_dollars/
    net_gex_1pct/total_oi_dollars are linear combinations of those sums) — never an average,
    rank, or anything else that would make summing per-expiry partials wrong."""
    from math_exposure_core import compute_exposures_by_strike as _cebs
    by_exp: "dict[str, list]" = {}
    for ct in contracts or []:
        if not isinstance(ct, dict):
            continue
        by_exp.setdefault(_contract_expiry_str(ct), []).append(ct)
    out: "dict[str, dict]" = {}
    for exp, subset in by_exp.items():
        exposures, _diag = _cebs(subset, spot=spot, require_oi=True)
        out[exp] = exposures
    return out


def _merge_strike_exposure_bucket(a: dict, b: dict) -> dict:
    """Additively merge two per-strike exposure buckets from DIFFERENT expiries (see
    `_per_strike_exposures_by_expiry`'s docstring for why plain add/OR reproduces the
    single-call result exactly). Generic over field names, not a hardcoded list, so a field
    compute_exposures_by_strike adds later merges correctly as long as it keeps the same
    additive-or-boolean-or-sparse-None shape every existing field already has.

    Two field shapes need special handling beyond plain `+`: `has_oi`/`has_valid_gamma` are
    booleans (OR, not add), and `call_oi`/`put_oi`/`call_volume`/`put_volume` use `None` —
    not `0.0` — as their sparse "no contract at this strike/expiry contributed this field"
    sentinel (see `_strike_bucket`'s own initializer). `None + None -> None` (still nothing
    contributed anywhere), `None + X -> X` (one side had it, the other didn't -- exactly
    `_strike_bucket`'s own `prev if prev is not None else ...` accumulation rule, applied to
    merging two already-summed partials instead of one raw value at a time)."""
    out = dict(a)
    for k, v in b.items():
        if k not in out:
            out[k] = v
            continue
        cur = out[k]
        if isinstance(v, bool) or isinstance(cur, bool):
            out[k] = bool(cur) or bool(v)
        elif cur is None:
            out[k] = v
        elif v is None:
            out[k] = cur
        else:
            out[k] = cur + v
    return out


def _merge_all_expiry_exposures(by_expiry: "dict[str, dict]") -> dict:
    merged: dict = {}
    for exposures in by_expiry.values():
        for strike, bucket in exposures.items():
            merged[strike] = (_merge_strike_exposure_bucket(merged[strike], bucket)
                              if strike in merged else dict(bucket))
    return merged


def _per_strike_view_from_contracts(contracts: list, spot: float,
                                    by_expiry_out: "dict | None" = None) -> dict:
    """The exact {all, near, far} shape /api/terrain/strikes serves, computed directly from
    `contracts` via the SAME reusable, pure functions terrain_engine.compute_terrain already
    calls internally (compute_exposures_by_strike -> _per_strike_scopes) — not a second
    formula, just called directly so a caller that already has an OVERLAID contract list (and
    does not want to pay for the rest of compute_terrain's unrelated fields: pin, walls,
    regime, confidence) can get a consistent per-strike view from it.

    The 'all' exposures are now built by partitioning `contracts` per expiry and merging
    (`_per_strike_exposures_by_expiry` / `_merge_all_expiry_exposures`) instead of one call
    over the whole list — numerically IDENTICAL (see those functions' docstrings), but this
    lets a caller pass `by_expiry_out` (a dict this function fills in-place) to capture the
    per-expiry breakdown for a LATER incremental update (`_per_strike_view_update_expiry`)
    without a second full pass. 'near'/'far' (DTE-scoped chips) are unchanged — still one
    full-chain pass each inside `_per_strike_scopes` — that cost is paid on this (the
    REST-cadence) path only, never on the eager per-tick path; see
    `_per_strike_view_update_expiry`'s own docstring for why those two chips are carried
    over rather than recomputed on every streamed tick."""
    from terrain_engine import _per_strike_scopes
    by_expiry = _per_strike_exposures_by_expiry(contracts, spot)
    if by_expiry_out is not None:
        by_expiry_out.clear()
        by_expiry_out.update(by_expiry)
    exposures = _merge_all_expiry_exposures(by_expiry)
    return _per_strike_scopes(exposures, contracts, spot)
