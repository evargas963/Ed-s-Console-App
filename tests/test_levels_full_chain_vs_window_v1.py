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

import calibration.complete_chain_capture as cch
import server
import time_et
from schwab_client import flatten_chain_contracts
from terrain_engine import compute_terrain

_FX = json.loads((Path(__file__).resolve().parent / "fixtures"
                  / "real_mrvl_full_chain_vs_strike_window.json").read_text(encoding="utf-8"))
_CAPTURED = datetime.fromtimestamp(_FX["captured_utc"], time_et.ET)
_SPOT = float(_FX["full"]["underlying"]["last"])


def _contracts(payload: dict) -> list[dict]:
    return flatten_chain_contracts(payload)


def _levels(snap) -> dict:
    return {k: getattr(snap, k) for k in ("call_wall", "put_wall", "gamma_flip",
                                          "absolute_gamma_strike", "net_gex_peak", "max_pain")}


def test_the_fixture_is_the_full_chain_and_its_window():
    full, window = _contracts(_FX["full"]), _contracts(_FX["window"])
    assert len(full) == _FX["n_full"] and len(window) == _FX["n_window"]
    assert len(window) < len(full)
    strikes = lambda cs: {c["strikePrice"] for c in cs}   # noqa: E731
    assert strikes(window) < strikes(full), "the window is a strict subset of the chain's strikes"


def test_the_window_gives_different_levels_than_the_full_chain():
    """The measurement itself: same code, same spot, same instant (the capture's) -- only the
    strikes differ."""
    full = _levels(compute_terrain("MRVL", _contracts(_FX["full"]), _SPOT, now=_CAPTURED))
    window = _levels(compute_terrain("MRVL", _contracts(_FX["window"]), _SPOT, now=_CAPTURED))
    differing = {k for k in full if full[k] != window[k]}
    assert differing, (full, window)
    assert full["gamma_flip"] is not None, "the full chain has a flip for MRVL"


def test_the_level_producer_computes_from_the_full_chain(tmp_path):
    """The one producer (server._publish_levels) prices the full chain stored as the daemon
    stores it (every expiry, with Schwab's underlying price), valued at the capture's own time:
    the full chain's levels -- not the window's. That the sweep delivers the whole chain is
    tests/test_chain_history_v1.py::test_the_daemons_chain_is_the_current_record_whole_once_all_parts_are_in."""
    tk = server.ticker_storage_key("MRVL")
    db = tmp_path / "ed.db"
    by_expiry: dict = {}
    for ct in _contracts(_FX["full"]):
        by_expiry.setdefault(ct["expirationDate"][:10], []).append(ct)
    for expiry, cts in by_expiry.items():
        cch.persist_complete_chain_capture(db, ticker=tk, expiry=expiry, contracts=cts, spot=_SPOT,
                                           completeness_basis=cch.CAPTURE_BASIS,
                                           ts_utc=_FX["captured_utc"])
    server._publish_levels(tk, captures=cch.last_capture_per_day(db, tk, 2))
    published = server.terrain_cache_get(tk) or {}
    full = _levels(compute_terrain("MRVL", _contracts(_FX["full"]), _SPOT, now=_CAPTURED))
    window = _levels(compute_terrain("MRVL", _contracts(_FX["window"]), _SPOT, now=_CAPTURED))
    got = {k: published.get(k) for k in full}
    assert got == full, (got, full)
    assert got != window
