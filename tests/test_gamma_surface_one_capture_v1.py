"""The Options/Gamma strike x expiry surface is a projection of the one exposure faucet
(math_exposure_core.compute_exposures_by_strike), never a second GEX producer. Each ticker's own
multi-expiry chain at one instant, as the capture daemon recorded Schwab's option chain
(tests/fixtures/real_daemon_chains_spy_tsla_2026_10_02_0930.json: three whole expiries of SPY's
and of TSLA's 2026-10-02 morning sweep, with their open-interest-0 rows and the -999 Greeks
Schwab sent), valued at the capture's own time."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import server
import time_et
from math_exposure_core import (bucket_metric, compute_exposures_by_strike, exposure_books,
                                merge_exposure_books, strike_oi_legs, strike_volume_legs)
from server import project_gamma_surface
from terrain_engine import compute_terrain

_ROWS = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_daemon_chains_spy_tsla_2026_10_02_0930.json")
                   .read_text(encoding="utf-8"))["rows"]
TICKERS = ("SPY", "TSLA")


class Capture:
    """One ticker's recorded expiries: the chain, its spot and its instant."""

    def __init__(self, ticker: str):
        rows = [r for r in _ROWS if r["ticker"] == ticker]
        self.ticker = ticker
        self.expiries = [r["expiry"] for r in rows]
        self.chain = [ct for r in rows for ct in r["chain"]]
        self.spot = rows[0]["spot"]
        self.at = datetime.fromtimestamp(rows[0]["ts_utc"], time_et.ET)

    def slice(self, expiry: str) -> list[dict]:
        return [ct for ct in self.chain if _exp_key(ct) == expiry]

    def faucet(self, contracts: list[dict]) -> dict:
        return compute_exposures_by_strike(contracts, spot=self.spot, now=self.at)[0]

    def surface(self, contracts: list[dict] | None = None) -> dict:
        """The grid as _publish_levels builds it: shaped from the chain's exposure_books."""
        contracts = self.chain if contracts is None else contracts
        return project_gamma_surface(contracts, exposure_books(contracts, spot=self.spot, now=self.at))


def _exp_key(ct: dict) -> str:
    """The projection's column key: the native expirationDate's first 10 characters."""
    return str(ct.get("expirationDate") or "")[:10]


def _col(surface: dict, expiry: str) -> int:
    return [e["expiry"] for e in surface["expirations"]].index(expiry)


def _row(surface: dict, strike: float) -> dict:
    return next(r for r in surface["cells"] if r["strike"] == strike)


@pytest.fixture(params=TICKERS)
def cap(request) -> Capture:
    return Capture(request.param)


def test_each_capture_is_one_tickers_expiries_at_one_instant(cap):
    assert len(cap.expiries) == 3 and len(set(cap.expiries)) == 3
    assert {_exp_key(ct) for ct in cap.chain} == set(cap.expiries)
    assert all(ct["symbol"].startswith(cap.ticker + " ") for ct in cap.chain)
    assert len({r["ts_utc"] for r in _ROWS if r["ticker"] == cap.ticker}) == 1
    assert all(any((ct.get("openInterest") or 0) > 0 for ct in cap.slice(e)) for e in cap.expiries)


def test_a_cell_is_the_faucet_on_its_expirys_slice(cap):
    surface = cap.surface()
    assert [e["expiry"] for e in surface["expirations"]] == cap.expiries
    checked = 0
    for exp in cap.expiries:
        j = _col(surface, exp)
        for k, bucket in cap.faucet(cap.slice(exp)).items():
            row = _row(surface, float(k))
            assert row["gex"][j] == bucket_metric(bucket, "net_gex_1pct")
            assert row["dex"][j] == bucket_metric(bucket, "net_dex_dollars")
            checked += 1
    assert checked > 100


def test_the_expiry_cells_sum_to_the_full_book(cap):
    surface = cap.surface()
    for k, bucket in cap.faucet(cap.chain).items():
        full = bucket_metric(bucket, "net_gex_1pct")
        if full is None:
            continue
        cells = [_row(surface, float(k))["gex"][_col(surface, e)] for e in cap.expiries]
        assert abs(sum(v for v in cells if v is not None) - full) < 1e-6, k


def test_one_expirys_contracts_never_move_anothers_cells(cap):
    first, rest = cap.expiries[0], cap.expiries[1:]
    base = cap.surface()
    fewer = cap.surface([ct for ct in cap.chain if _exp_key(ct) != rest[-1]])
    j0, j0_after = _col(base, first), _col(fewer, first)
    strikes = [k for k in base["strikes"] if _row(base, k)["gex"][j0] is not None]
    assert strikes
    for k in strikes:
        assert _row(base, k)["gex"][j0] == _row(fewer, k)["gex"][j0_after]


def test_every_listed_strike_of_the_chain_is_projected_with_its_native_dte(cap):
    surface = cap.surface()
    expected = set()
    for exp in cap.expiries:
        expected |= {float(k) for k in cap.faucet(cap.slice(exp))}
    assert set(surface["strikes"]) == expected
    native_dte = {e: next(int(ct["daysToExpiration"]) for ct in cap.slice(e)) for e in cap.expiries}
    assert {e["expiry"]: e["dte"] for e in surface["expirations"]} == native_dte
    assert surface["contracts_total"] == surface["contracts_used"] == len(cap.chain)


def test_a_cell_carries_the_vendor_symbols_of_its_strike_and_expiry(cap):
    surface = cap.surface()
    for exp in cap.expiries:
        j = _col(surface, exp)
        for ct in cap.slice(exp):
            side = "call" if ct["putCall"] == "CALL" else "put"
            assert _row(surface, float(ct["strikePrice"]))["contracts"][j][side] == ct["symbol"]


def test_vanna_oi_and_volume_cells_are_the_faucets(cap):
    surface = cap.surface()
    nonzero = 0
    for exp in cap.expiries:
        j = _col(surface, exp)
        for k, bucket in cap.faucet(cap.slice(exp)).items():
            row = _row(surface, float(k))
            if bucket_metric(bucket, "net_vanna") is None:
                assert row["vanna"][j] is None
            else:
                assert row["vanna"][j] == pytest.approx(bucket["call_vanna"] - bucket["put_vanna"], abs=0.005)
                nonzero += bucket["call_vanna"] != bucket["put_vanna"]
            for key, legs in (("oi", strike_oi_legs(bucket)), ("volume", strike_volume_legs(bucket))):
                assert row[key][j] == ({"call": None, "put": None, "total": None} if legs is None else
                                       {"call": round(legs[0]), "put": round(legs[1]),
                                        "total": round(legs[0] + legs[1])})
    assert nonzero > 10


def test_a_strike_not_listed_in_an_expiry_is_null_there_not_zero(cap):
    surface = cap.surface()
    unlisted = [(k, e) for e in cap.expiries for k in surface["strikes"]
                if k not in {float(ct["strikePrice"]) for ct in cap.slice(e)}]
    assert unlisted, "the expiries list different strikes"
    for k, e in unlisted:
        row, j = _row(surface, k), _col(surface, e)
        assert (row["gex"][j], row["dex"][j], row["vanna"][j]) == (None, None, None)
        assert row["oi"][j] == row["volume"][j] == {"call": None, "put": None, "total": None}


def test_the_expiry_books_merge_to_the_one_full_book(cap):
    full, diag = compute_exposures_by_strike(cap.chain, spot=cap.spot, now=cap.at)
    by_expiry = exposure_books(cap.chain, spot=cap.spot, now=cap.at)
    assert {exp for exp, _dte in by_expiry} == set(cap.expiries)
    merged, merged_diag = merge_exposure_books(by_expiry.values())
    assert (merged_diag.contracts_total, merged_diag.contracts_used) == (diag.contracts_total, diag.contracts_used)
    assert set(merged) == set(full)
    for strike, bucket in full.items():        # the same sums, up to float addition order
        assert merged[strike] == pytest.approx(bucket, rel=1e-12, abs=1e-9), strike


def test_the_chart_draws_the_heatmaps_own_dex_and_oi_per_strike(cap):
    """The Chart view's DEX and OI profiles (/api/terrain/strikes `measures`) are the heatmap's own
    cells summed across expiries: one computation, two views."""
    snap = compute_terrain(cap.ticker, cap.chain, cap.spot, now=cap.at)
    surface = project_gamma_surface(cap.chain, snap.books)
    with server._terrain_cache_lock:
        server._terrain_cache[cap.ticker] = {"ticker": cap.ticker, "spot": snap.spot,
                                             "computed_ts_utc": cap.at.timestamp(), "_per_strike": snap.per_strike}
    try:
        measures = json.loads(server.get_terrain_strikes(ticker=cap.ticker, scope="all").body)["measures"]
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(cap.ticker, None)
    assert measures["dex"]["rows"] and measures["oi"]["rows"]
    cols = len(surface["expirations"])
    for m, cell_value in (("dex", lambda c: c), ("oi", lambda c: c["total"])):
        for strike, value in measures[m]["rows"]:
            cells = [cell_value(c) for c in _row(surface, strike)[m] if c is not None and cell_value(c) is not None]
            assert cells and abs(sum(cells) - value) <= 0.5 * cols + 0.1, (m, strike, value, cells)
