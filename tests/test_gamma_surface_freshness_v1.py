"""RC-UI-1 — proof that /api/options/gamma-surface PREFERS the live terrain surface and labels
freshness honestly: a morning snapshot is never served as intraday, and a stale live surface
reads stale. The projection math is unchanged (still compute_exposures_by_strike); this covers
the SOURCE-SELECTION and FRESHNESS semantics the operator required."""
import json
import time

import server
from server import get_options_gamma_surface, ticker_storage_key

_SURF = {
    "expirations": [{"expiry": "2026-09-11", "dte": 2}],
    "strikes": [583.0], "cells": [{"strike": 583.0, "gex": [958600]}],
    "contracts_total": 1, "contracts_used": 1, "contracts_excluded_malformed_expiry": 0,
}


def _call(tk):
    return json.loads(get_options_gamma_surface(tk).body)


def _put_live(tk, *, computed_ts, levels_stale=False):
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {
            "_gamma_surface": _SURF, "computed_ts_utc": computed_ts, "spot": 583.41,
            "spot_source": "last", "spot_as_of_ts_utc": computed_ts, "chain_basis": "full",
            "levels_stale": levels_stale, "levels_stale_reason": ("cadence gap" if levels_stale else None),
        }


def _clear(tk):
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    server._GAMMA_SURFACE_CACHE.pop(tk, None)


def test_live_terrain_surface_is_preferred_and_fresh():
    tk = ticker_storage_key("SPY")
    _clear(tk); _put_live(tk, computed_ts=time.time())
    try:
        d = _call(tk)
        assert d["source"] == "terrain_live_cache" and d["live"] is True and d["stale"] is False
        assert d["chain_as_of_ts_utc"] is not None and d["spot"] == 583.41
        assert d["provenance"]["spot_basis"] == "live_resolve_spot"
        assert d["cells"] == _SURF["cells"]           # served verbatim (formatting-only downstream)
    finally:
        _clear(tk)


def test_live_surface_reads_stale_when_old():
    tk = ticker_storage_key("SPY")
    _clear(tk); _put_live(tk, computed_ts=time.time() - 600)   # older than GAMMA_SURFACE_LIVE_STALE_SEC
    try:
        d = _call(tk)
        assert d["source"] == "terrain_live_cache" and d["live"] is True and d["stale"] is True
    finally:
        _clear(tk)


def test_fallback_is_labelled_not_live_never_intraday():
    # a ticker with no live cache and (in the offline test DB) no banked chain
    tk = ticker_storage_key("ZZTESTX")
    _clear(tk)
    try:
        d = _call(tk)
        # never claims live; if a banked chain existed it would be source=banked_morning_reference
        assert d["live"] is False and d["stale"] is True
        assert d["source"] in ("unavailable", "banked_morning_reference")
        if d["source"] == "banked_morning_reference":
            assert "not intraday" in d["degraded"].lower() or "morning" in d["degraded"].lower()
    finally:
        _clear(tk)
