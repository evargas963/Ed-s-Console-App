"""The strike-window measurement, as a CI test, on a REAL Schwab chain.

MEASURED 2026-09-25 live across the 42 board tickers: levels computed from the strike window the
console fetched (strike_count sized to +/-5% around spot -- 20 strikes for most names) disagreed
with the same code run on the full chain for about a third of the board. MRVL was one. In
this fixture (captured the same afternoon) the window loses the gamma flip entirely (full chain:
230.53) and moves max pain from 242.5 to 247.5, at spot 263.51.

The fixture holds MRVL's full chain (strike_range=ALL) and its 20-strike window, captured from
Schwab at the same moment (tests/fixtures/real_mrvl_full_chain_vs_strike_window.json). These
tests (1) keep the measurement reproducible offline, and (2) hold the one level producer to the
full chain: if it is ever narrowed back to a window, its levels stop matching and CI fails.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import server
import time_et
from terrain_engine import compute_terrain

_FX = json.loads((Path(__file__).resolve().parent / "fixtures"
                  / "real_mrvl_full_chain_vs_strike_window.json").read_text(encoding="utf-8"))
_CAPTURED = datetime.fromtimestamp(_FX["captured_utc"], time_et.ET)
_SPOT = float(_FX["full"]["underlying"]["last"])


def _contracts(payload: dict) -> list[dict]:
    return server.flatten_chain_contracts(payload)


def _levels(snap) -> dict:
    return {k: getattr(snap, k) for k in ("call_wall", "put_wall", "gamma_flip",
                                          "absolute_gamma_strike", "net_gex_peak", "max_pain")}


@pytest.fixture
def at_capture(monkeypatch):
    """Value everything at the capture instant, so expiries passing after 2026-09-25 cannot
    change what the chain says."""
    monkeypatch.setattr(time_et, "now_et", lambda: _CAPTURED)
    return _CAPTURED


def test_the_fixture_is_the_full_chain_and_its_window():
    full, window = _contracts(_FX["full"]), _contracts(_FX["window"])
    assert len(full) == _FX["n_full"] and len(window) == _FX["n_window"]
    assert len(window) < len(full)
    strikes = lambda cs: {c["strikePrice"] for c in cs}   # noqa: E731
    assert strikes(window) < strikes(full), "the window is a strict subset of the chain's strikes"


def test_the_window_gives_different_levels_than_the_full_chain(at_capture):
    """The measurement itself: same code, same spot, same instant -- only the strikes differ."""
    full = _levels(compute_terrain("MRVL", _contracts(_FX["full"]), _SPOT, now=at_capture))
    window = _levels(compute_terrain("MRVL", _contracts(_FX["window"]), _SPOT, now=at_capture))
    differing = {k for k in full if full[k] != window[k]}
    assert differing, (full, window)
    assert full["gamma_flip"] is not None, "the full chain has a flip for MRVL"


def test_the_level_producer_computes_from_the_full_chain(monkeypatch, at_capture):
    """The one producer (_terrain_refresh_one), with its real compute_terrain, must publish the
    full chain's levels -- not the window's."""
    monkeypatch.setattr(server, "_is_loggable_session", lambda: True)   # an open-market test
    requested = []

    def fake_fetch(client, ticker, *, priority=False, expiry=None):
        requested.append((ticker, expiry))
        return server.FullChainResponse(200, json.loads(json.dumps(_FX["full"])), parts=1)

    monkeypatch.setattr(server, "fetch_full_chain", fake_fetch)
    monkeypatch.setattr(server, "_terrain_quarantine_blocks", lambda t: False)
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "_universal_capture_wanted", lambda t: (False, None))
    monkeypatch.setattr(server, "resolve_spot", lambda t, chain_json=None: (_SPOT, "fixture", 0.0))
    monkeypatch.setattr(server, "_persist_universal_complete_chain", lambda *a, **k: None)
    monkeypatch.setattr(server, "_accrue_chain_observation", lambda *a, **k: None)
    monkeypatch.setattr(server, "_log_flip_drift", lambda *a, **k: None)
    monkeypatch.setattr(server, "_note_terrain_success", lambda t: None)

    tk = server.ticker_storage_key("MRVL")
    status = server._terrain_refresh_one(tk)
    assert status.startswith("ok"), status
    assert requested == [(tk, None)], "the producer asks for the whole chain, every expiry"
    published = server.terrain_cache_get(tk) or {}
    full = _levels(compute_terrain("MRVL", _contracts(_FX["full"]), _SPOT, now=at_capture))
    window = _levels(compute_terrain("MRVL", _contracts(_FX["window"]), _SPOT, now=at_capture))
    got = {k: published.get(k) for k in full}
    assert got == full, (got, full)
    assert got != window
