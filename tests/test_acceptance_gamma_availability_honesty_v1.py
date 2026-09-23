"""PHASE 3.5 (acceptance layer, first slice) — the gamma surface must never claim
availability it cannot back up.

WHY THIS EXISTS. The repo's test suite is bottom-heavy: thousands of unit/contract/lock
tests prove individual functions do what their own docstring says, but almost nothing
proves the operator's actual, stated promise -- that a value the UI marks available/live
really is. `CARD_TRUST_CONTRACT.md` described a UI-trust surface that no longer existed for
months and nothing caught it, because nothing tested the promise itself, only the pieces.

This file is the first of a small, deliberately short acceptance layer that checks
operator-stated product promises directly, as code, against the real route function and
real cache state -- not a mock of the business logic. It is an ordinary pytest file: it
runs inside the SAME required `pytest-full` CI gate as every other test here (no new CI
job, no new lock file, nothing to remember to invoke separately).

THE PROMISE UNDER TEST. `app/api/routes/options.py`'s CAPS-audit fix (2026-09-20):
`surf.get("gamma_available", False)` must fail CLOSED when a live-cached surface is  # caps-ok: scanner false positive: module docstring describing the fail-closed read under test
missing its `gamma_available` key. Every real producer (`project_gamma_surface` and its
refresh-path siblings) always sets this key; a missing key means a malformed/incomplete
surface reached the cache, and defaulting to True would silently claim a "LIVE" signal a
trader could act on. This test proves the ROUTE'S OWN JSON RESPONSE reflects that -- not
just that the internal variable computes correctly, which a unit test could already show
without ever proving the HTTP-facing promise holds.
"""
from __future__ import annotations

import json

import server
from app.api.routes.options import get_options_gamma_surface
from instrument_identity import ticker_storage_key
import terrain_state

_BASE_SURF = {
    "expirations": [{"expiry": "2026-09-25", "dte": 5}],
    "strikes": [580.0, 583.0, 586.0],
    "cells": [{"strike": 580.0, "gex": [-90000]}, {"strike": 583.0, "gex": [958600]},
              {"strike": 586.0, "gex": [-264500]}],
    "contracts_total": 3, "contracts_used": 3, "contracts_excluded_malformed_expiry": 0,
}


def _call(tk: str) -> dict:
    return json.loads(get_options_gamma_surface(tk).body)


def _put_live(tk: str, surf: dict, *, computed_ts: float) -> None:
    import time as _time

    with terrain_state._terrain_cache_lock:
        terrain_state._terrain_cache[tk] = {
            "_gamma_surface": surf, "computed_ts_utc": computed_ts, "spot": 583.41,
            "spot_source": "last", "spot_as_of_ts_utc": computed_ts, "chain_basis": "full",
        }
    _ = _time  # imported for symmetry with sibling tests' computed_ts convention


def _clear(tk: str) -> None:
    with terrain_state._terrain_cache_lock:
        terrain_state._terrain_cache.pop(tk, None)
    server._GAMMA_SURFACE_CACHE.pop(tk, None)


def test_a_malformed_surface_reports_unavailable_not_a_fabricated_true():
    """The mutation this test must catch: `surf.get("gamma_available", False)` reverting  # caps-ok: scanner false positive: docstring naming the mutation this test catches
    to `surf.get("gamma_available", True)`. A surface missing the key entirely (never  # caps-ok: scanner false positive: docstring naming the mutation this test catches
    produced by any real producer -- this is what a malformed/incomplete surface looks
    like) must never read back to the API caller as available."""
    import time

    tk = ticker_storage_key("SPY")
    malformed = {**_BASE_SURF}  # gamma_available deliberately absent
    _clear(tk)
    _put_live(tk, malformed, computed_ts=time.time())
    try:
        d = _call(tk)
        assert d["available"] is False, (
            f"a surface with no gamma_available key reported available={d['available']!r} "
            f"-- a missing key is being read as a fabricated True claim of availability")
        assert d["reason"] is not None, (
            "an unavailable surface must disclose a reason, not just a bare False")
    finally:
        _clear(tk)


def test_a_surface_that_honestly_computed_unavailable_still_says_so():
    """Negative control in the other direction: an honest False must not get overwritten
    into a True by any later step in the response assembly."""
    import time

    tk = ticker_storage_key("SPY")
    surf = {**_BASE_SURF, "gamma_available": False, "gamma_unavailable_reason": "no cells carried usable open interest"}
    _clear(tk)
    _put_live(tk, surf, computed_ts=time.time())
    try:
        d = _call(tk)
        assert d["available"] is False
        assert d["reason"] == "no cells carried usable open interest"
    finally:
        _clear(tk)


def test_a_surface_that_honestly_computed_available_is_reported_as_such():
    """Positive control: the fail-closed default must not become fail-closed-always --
    a real, honestly-computed True must still read through as available."""
    import time

    tk = ticker_storage_key("SPY")
    surf = {**_BASE_SURF, "gamma_available": True}
    _clear(tk)
    _put_live(tk, surf, computed_ts=time.time())
    try:
        d = _call(tk)
        assert d["available"] is True
        assert d["reason"] is None
    finally:
        _clear(tk)
