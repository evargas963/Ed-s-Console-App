"""The gamma heatmap, Schwab to the screen: a cell with no value draws "-", whatever the reason the
server serves for it (operator, 2026-10-11).

Real data: NFLX's chain as production's complete_chain_captures held it
(tests/fixtures/real_nflx_chain_2026_10_07_three_expiries.json): on 2027-12-17 and 2028-01-21, 8
contracts with open interest whose Greeks Schwab sent as -999, so their cells have no GEX
(exposure_not_sent); and strikes no contract is listed at in a column (not_listed).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import server
import time_et
from math_exposure_core import exposure_books

_NFLX = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_nflx_chain_2026_10_07_three_expiries.json")
                   .read_text(encoding="utf-8"))


def _drawn(projected: dict, spot: float, as_of: float, tmp_path) -> "tuple[dict, dict]":
    """What the route serves at `as_of` for every strike and column of `projected`, and each
    cell's text as the page's own render (static/js/ed-gamma.js) draws it:
    (surface, {(strike, expiry): text})."""
    node = shutil.which("node")
    assert node, "Node.js is required on PATH (the same prerequisite as Playwright E2E)"
    tk = projected["ticker"]
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_gamma_surface": projected, "spot": spot, "spot_source": "last",
                                     "computed_ts_utc": as_of, "chain_basis": "full"}
    try:
        surface = server.gamma_surface_payload(tk, "all", None, 0, None, None,
                                               datetime.fromtimestamp(as_of, time_et.ET))
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
    path = tmp_path / "surface.json"
    path.write_text(json.dumps(surface), encoding="utf-8")
    r = subprocess.run([node, str(Path(__file__).parent / "ed_gamma_cells_node.mjs"), str(path)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    return surface, {(c["strike"], c["expiry"]): c["text"] for c in map(json.loads, r.stdout.splitlines())}


def test_the_page_draws_every_cell_with_no_value_as_a_dash(tmp_path):
    """Schwab's chain priced by the real exposure book, projected into the surface, served by the
    heatmap route's body and drawn by the page: every cell with no value draws "-", the cells whose
    Greeks Schwab sent as -999 (exposure_not_sent) as the strikes no contract is listed at."""
    at = datetime.fromtimestamp(_NFLX["ts_utc"], time_et.ET)
    contracts = _NFLX["chain"]
    projected = dict(server.project_gamma_surface(contracts, exposure_books(contracts, spot=_NFLX["spot"], now=at)),
                     ticker="NFLX", available=True, live=True, stale=False, spot=_NFLX["spot"])
    surface, drawn = _drawn(projected, _NFLX["spot"], _NFLX["ts_utc"], tmp_path)
    exps = [e["expiry"] for e in surface["expirations"]]
    absent = {(r["strike"], exps[j]): code for r in surface["cells"] for j, code in enumerate(r["absent"]["gex"]) if code}
    assert set(absent.values()) == {server.CELL_NOT_LISTED, server.CELL_EXPOSURE_NOT_SENT}
    assert {drawn[cell] for cell in absent} == {"-"}
    assert set(surface["absent_reasons"].values()) == {"-"}
