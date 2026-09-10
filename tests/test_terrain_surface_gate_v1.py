"""RC-UI-1 #1 — behavioral proof at the REAL producer branch: _terrain_refresh_one projects the
gamma surface only for a demanded (viewed) ticker, exactly once with that cycle's contracts+spot, and
a projection failure never fails the terrain refresh. Heavy leaf deps are monkeypatched (existing
seam); no new production abstraction was created to make this testable."""
import json
import types
from pathlib import Path

import server

#: A REAL complete Schwab capture (native rows verbatim) stands in for the cycle's flattened
#: chain — the producer hands project_gamma_surface whatever flatten_chain_contracts returns.
_REAL_CHAIN = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "real_cde_complete_chain_half_dollar.json")
    .read_text(encoding="utf-8"))["chain"]


def _stub_terrain(monkeypatch, proj):
    class R:
        status_code = 200
        def json(self):  # noqa: D401 - stub
            return {"x": 1}

    class Snap:
        profile = {}
        per_strike = {}
        oi_by_strike = {}
        confidence = None
        def to_dict(self):
            return {}

    monkeypatch.setattr(server, "_terrain_quarantine_blocks", lambda t: False)
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "_universal_capture_wanted", lambda t: (False, None))
    monkeypatch.setattr(server, "_terrain_strike_count", lambda t: 60)
    monkeypatch.setattr(server, "_gated_safe_get_chain", lambda *a, **k: (R(), 0.0, 0.0))
    monkeypatch.setattr(server, "flatten_chain_contracts", lambda j: [dict(ct) for ct in _REAL_CHAIN])
    monkeypatch.setattr(server, "resolve_spot", lambda t, chain_json=None: (100.0, "stub", 0.0))
    monkeypatch.setattr(server, "_persist_universal_complete_chain", lambda *a, **k: None)
    monkeypatch.setattr(server, "_learn_strike_geometry", lambda *a, **k: None)
    monkeypatch.setattr(server, "compute_terrain", lambda *a, **k: Snap())
    monkeypatch.setattr(server, "_accrue_chain_observation", lambda *a, **k: None)
    monkeypatch.setattr(server, "_log_flip_drift", lambda *a, **k: None)
    monkeypatch.setattr(server, "_radar_atr", lambda t: types.SimpleNamespace(daily=None, m15=None))
    monkeypatch.setattr(server, "_note_terrain_success", lambda t: None)
    monkeypatch.setattr(server, "project_gamma_surface", proj)


def _cached_surface(tk):
    return (server.terrain_cache_get(tk) or {}).get("_gamma_surface")


def test_producer_gates_projection_on_demand(monkeypatch):
    tk = server.ticker_storage_key("SPY")
    calls = {"n": 0, "args": None}

    def proj(contracts, spot):
        calls["n"] += 1
        calls["args"] = (len(contracts), spot)
        return {"expirations": [], "strikes": [], "cells": []}

    _stub_terrain(monkeypatch, proj)

    # UNWANTED ticker -> the producer path does NOT invoke project_gamma_surface
    server._gamma_surface_demand.pop(tk, None)
    server._terrain_refresh_one(tk)
    assert calls["n"] == 0
    assert _cached_surface(tk) is None

    # WANTED ticker -> invoked EXACTLY ONCE, with that cycle's contracts + live spot
    server._note_gamma_surface_demand(tk)
    server._terrain_refresh_one(tk)
    assert calls["n"] == 1
    assert calls["args"] == (len(_REAL_CHAIN), 100.0)
    assert _cached_surface(tk) == {"expirations": [], "strikes": [], "cells": []}

    server._gamma_surface_demand.pop(tk, None)


def test_projection_failure_does_not_fail_terrain_refresh(monkeypatch):
    tk = server.ticker_storage_key("SPY")

    def boom(contracts, spot):
        raise RuntimeError("projection boom")

    _stub_terrain(monkeypatch, boom)
    server._note_gamma_surface_demand(tk)
    res = server._terrain_refresh_one(tk)          # wanted, but the projection raises
    assert not str(res).startswith("error")        # terrain refresh still succeeded
    assert _cached_surface(tk) is None             # surface absent -> endpoint falls back to reference
    server._gamma_surface_demand.pop(tk, None)
