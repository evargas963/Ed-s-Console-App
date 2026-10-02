"""The gamma heatmap draws what Schwab sent (operator, 2026-10-01: "From Schwab's mouth to our UI's
ears. Period."; "shouldn't be a dash should be 0").

A listed contract with open interest 0 holds no position: its GEX is gamma x 0 = 0, whatever its
Greeks (Schwab sends -999 Greeks for a contract that has not traded). The cell is 0, drawn "$0".
A strike with no contract listed in an expiry is served as "-" and drawn so (operator, 2026-10-01:
"i don't like that message in the heatmap cells or anywhere else, just use a - instead").

Real data, one column each:
- SPY 2026-10-14 as the production console held it on 2026-10-01 08:59:47 ET
  (tests/fixtures/real_spy_2026_10_14_chain_oi_zero.json; Schwab's chain with its quotes' Greeks):
  124 strikes list only contracts with open interest 0; the 121 whose 242 contracts carry -999
  Greeks were drawn "--" (measured on the live surface that minute).
- SPY 2026-10-15 from the capture daemon's 09:36:28 ET capture the same day
  (tests/fixtures/real_spy_2026_10_15_chain_oi_zero.json): 30 strikes, every contract open
  interest 0 (the live surface at 08:59 drew all 30 "--").
- SPY 2026-11-20 (tests/fixtures/real_spy_2026_11_20_chain_and_quotes.json, captured 2026-09-30).
A strike listed in one column and not another is that column's "-" cell.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

import server
import time_et
from math_exposure_core import exposure_books

_FX = Path(__file__).resolve().parent / "fixtures"
_OCT14 = json.loads((_FX / "real_spy_2026_10_14_chain_oi_zero.json").read_text(encoding="utf-8"))
_OCT15 = json.loads((_FX / "real_spy_2026_10_15_chain_oi_zero.json").read_text(encoding="utf-8"))
_NOV20 = json.loads((_FX / "real_spy_2026_11_20_chain_and_quotes.json").read_text(encoding="utf-8"))
_SPOT = float(_OCT14["priced_at_spot"])
_AT = datetime.fromtimestamp(_OCT14["chain_as_of_ts_utc"], time_et.ET)
_COLUMNS = {"2026-10-14": _OCT14["contracts"], "2026-10-15": _OCT15["contracts"], "2026-11-20": _NOV20["chain"]}


@pytest.fixture(autouse=True)
def _at_capture(monkeypatch):
    """Valued at the 10/14 chain's own time."""
    monkeypatch.setattr(time_et, "now_et", lambda: _AT)


def _surface() -> dict:
    contracts = [c for cs in _COLUMNS.values() for c in cs]
    surface = server.project_gamma_surface(contracts, exposure_books(contracts, spot=_SPOT, now=_AT))
    return dict(surface, ticker="SPY", available=True, live=True, stale=False, spot=_SPOT)


def _by_strike(contracts) -> "dict[float, list]":
    out: "dict[float, list]" = {}
    for c in contracts:
        out.setdefault(float(c["strikePrice"]), []).append(c)
    return out


def _open_interest_zero(expiry) -> "set[float]":
    return {k for k, cs in _by_strike(_COLUMNS[expiry]).items() if all(c["openInterest"] == 0 for c in cs)}


def _column(surface, expiry) -> "dict[float, tuple]":
    j = [e["expiry"] for e in surface["expirations"]].index(expiry)
    return {r["strike"]: (r["gex"][j], r["dex"][j], r["vanna"][j], r["absent"]["gex"][j]) for r in surface["cells"]}


def test_every_strike_listing_only_open_interest_zero_is_a_computed_zero():
    oct14 = _by_strike(_OCT14["contracts"])
    zero14, zero15 = _open_interest_zero("2026-10-14"), _open_interest_zero("2026-10-15")
    drawn_blank = {k for k in zero14 if any(c["gamma"] == -999.0 for c in oct14[k])}
    no_greek = [c for k in zero14 for c in oct14[k] if c["gamma"] == -999.0]
    # the measured populations: 10/14's 124 strikes of open interest 0, the 121 with -999 Greeks
    # drawn "--"; every one of 10/15's 30 strikes
    assert (len(zero14), len(drawn_blank), len(no_greek)) == (124, 121, 242)
    assert zero15 == set(_by_strike(_OCT15["contracts"])) and len(zero15) == 30
    surface = _surface()
    for expiry, zero in (("2026-10-14", zero14), ("2026-10-15", zero15)):
        col = _column(surface, expiry)
        for k in zero:
            assert col[k] == (0.0, 0.0, 0.0, None), (expiry, k, col[k])


def test_a_strike_with_no_contract_listed_is_served_as_such():
    surface = _surface()
    assert surface["absent_reasons"][server.CELL_NOT_LISTED] == "-"
    for expiry, contracts in _COLUMNS.items():
        listed = _by_strike(contracts)
        col = _column(surface, expiry)
        unlisted = set(col) - set(listed)
        assert unlisted, expiry
        for k in unlisted:
            assert col[k] == (None, None, None, server.CELL_NOT_LISTED), (expiry, k)
        for k in listed:
            assert col[k][3] != server.CELL_NOT_LISTED, (expiry, k)


def test_the_page_draws_zero_as_zero_and_an_unlisted_strike_as_a_dash(tmp_path):
    """Through the page's own render (static/js/ed-gamma.js), the server's surface drawn: every
    open-interest-zero strike of 10/14 and 10/15 reads "$0", every unlisted one "-", none "—"."""
    node = shutil.which("node")
    assert node, "Node.js is required on PATH (the same prerequisite as Playwright E2E)"
    with server._terrain_cache_lock:
        server._terrain_cache["SPY"] = {"_gamma_surface": _surface(), "spot": _SPOT, "spot_source": "last",
                                        "computed_ts_utc": _OCT14["chain_as_of_ts_utc"], "chain_basis": "full"}
    try:   # what the route serves for every strike and column
        surface = json.loads(server.get_options_gamma_surface(
            "SPY", scope="all", centre=None, shift=0, cols=None, expiry=None).body)
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop("SPY", None)
    path = tmp_path / "surface.json"
    path.write_text(json.dumps(surface), encoding="utf-8")
    r = subprocess.run([node, str(Path(__file__).parent / "ed_gamma_cells_node.mjs"), str(path)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    drawn = {(c["strike"], c["expiry"]): c["text"] for c in map(json.loads, r.stdout.splitlines())}
    for expiry in ("2026-10-14", "2026-10-15"):
        unlisted = set(surface["strikes"]) - set(_by_strike(_COLUMNS[expiry]))
        assert {drawn[(k, expiry)] for k in _open_interest_zero(expiry)} == {"$0"}, expiry
        assert {drawn[(k, expiry)] for k in unlisted} == {"-"}, expiry
    assert "—" not in drawn.values()
