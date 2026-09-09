"""RC-UI-1 — proof that /api/options/gamma-surface PREFERS the live terrain surface, borrows its
freshness from the ONE authority (terrain_staleness via terrain_cache_get, RC-424) rather than a
second age policy, discloses coverage honestly (live near-money window, not a complete chain), and
never presents the banked morning snapshot as intraday."""
import json
import time

import server
from server import get_options_gamma_surface, ticker_storage_key

_SURF = {
    "expirations": [{"expiry": "2026-09-11", "dte": 2}], "strikes": [580.0, 583.0, 586.0],
    "cells": [{"strike": 580.0, "gex": [-90000]}, {"strike": 583.0, "gex": [958600]},
              {"strike": 586.0, "gex": [-264500]}],
    "contracts_total": 3, "contracts_used": 3, "contracts_excluded_malformed_expiry": 0,
}


def _call(tk):
    return json.loads(get_options_gamma_surface(tk).body)


def _put_live(tk, *, computed_ts):
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {
            "_gamma_surface": _SURF, "computed_ts_utc": computed_ts, "spot": 583.41,
            "spot_source": "last", "spot_as_of_ts_utc": computed_ts, "chain_basis": "full",
        }


def _clear(tk):
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    server._GAMMA_SURFACE_CACHE.pop(tk, None)


def test_live_terrain_surface_is_preferred_and_discloses_coverage():
    tk = ticker_storage_key("SPY")
    _clear(tk); _put_live(tk, computed_ts=time.time())
    try:
        d = _call(tk)
        assert d["source"] == "terrain_live_cache" and d["live"] is True
        assert d["spot"] == 583.41 and d["cells"] == _SURF["cells"]     # served verbatim
        assert d["provenance"]["spot_basis"] == "live_resolve_spot"
        # coverage is honest: a live near-money window, NOT a complete strike_range=ALL chain
        assert d["complete"] is False
        assert d["coverage"]["strike_count"] == 3 and d["coverage"]["strike_min"] == 580.0
        assert "not the full strike_range=all" in d["coverage"]["note"].lower()
    finally:
        _clear(tk)


def test_freshness_is_the_one_terrain_authority_not_a_second_policy():
    # gamma-surface freshness must EQUAL terrain_cache_get's canonical freshness, field-for-field
    tk = ticker_storage_key("SPY")
    _clear(tk); _put_live(tk, computed_ts=time.time() - 240)   # 4 min old — a 5-min roster cadence is legitimate
    try:
        live = server.terrain_cache_get(tk)                    # the one authority
        d = _call(tk)
        assert d["stale"] == bool(live.get("levels_stale"))
        assert d["age_sec"] == live.get("levels_age_sec")
        expected_reason = live.get("levels_stale_reason") if bool(live.get("levels_stale")) else None
        assert (d["degraded"] or None) == expected_reason
        # no separate 180s threshold survives on the module
        assert not hasattr(server, "GAMMA_SURFACE_LIVE_STALE_SEC")
    finally:
        _clear(tk)


def test_fallback_is_labelled_not_live_never_intraday():
    tk = ticker_storage_key("ZZTESTX")   # no live cache, no banked chain in the offline test DB
    _clear(tk)
    try:
        d = _call(tk)
        assert d["live"] is False and d["stale"] is True
        assert d["source"] in ("unavailable", "banked_morning_reference")
        if d["source"] == "banked_morning_reference":
            assert "not intraday" in d["degraded"].lower() or "morning" in d["degraded"].lower()
    finally:
        _clear(tk)
