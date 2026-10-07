"""Every chain enters the app with Schwab's exact Greeks (operator, 2026-10-01: "you must use what
schwab gives us... no rounding, use the exact data that schwab gives us everywhere").

Schwab's option chain sends gamma, delta, theta, vega, rho and volatility rounded (Schwab: the
rounding cannot be changed); its quotes endpoint sends the same contract's unrounded. The capture
daemon's chain sweep, the one place a chain enters, never keeps the chain's Greeks: each contract
takes its quote's, so the heatmap, the levels, the per-strike rows and the forces read them
unchanged.

Real data (tests/fixtures/real_spy_2026_11_20_chain_and_quotes.json): SPY's 2026-11-20 contracts
from the capture daemon's full-chain capture of 2026-09-30 15:31:57 ET, and Schwab's quotes for every
one of them as answered at 2026-10-01 04:52 ET, served by Schwab's host as a local server
(tests/schwab_rest_standin.py) to the real sweep and client.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime

import pytest

import schwab_client as sc
import server
import time_et
from calibration.complete_chain_capture import ChainSweep
from numeric_contract import schwab_count
from stream_spine import CaptureWriter
from terrain_engine import compute_terrain
from tests.schwab_rest_standin import SPY, SPY_QUOTES, LocalSchwab, delivered

_SPOT = float(SPY["spot"])
_CAPTURED = datetime.fromtimestamp(SPY["capture_ts_utc"], time_et.ET)
_QUOTED = {s: e["quote"] for s, e in SPY_QUOTES.items()}
_CALL_875 = "SPY   261120C00875000"
_SWEEP_AT = datetime(2026, 8, 28, 9, 5, tzinfo=time_et.ET).timestamp()   # before the expiry, no capture window


@pytest.fixture
def fetched(tmp_path):
    """SPY's chain as the sweep delivers it; `withheld` symbols get no quote back."""
    def run(withheld: "set[str]" = frozenset()) -> "list[dict]":
        schwab = LocalSchwab()
        schwab.withheld = set(withheld)
        published: list = []
        sweep = ChainSweep(tmp_path / "ed_console.db", ["SPY"], lambda t, m: published.append((t, m)),
                           clock=lambda: _SWEEP_AT, failures=CaptureWriter(tmp_path / "stream_capture.db"),
                           streamed=lambda symbol: None)
        client = schwab.client(tmp_path)
        try:
            assert sweep.rotation(lambda: client, ["SPY"], threading.Event()) == {"SPY"}
        finally:
            schwab.close()
        return list(delivered(published, "SPY").values())
    return run


def _column(contracts: "list[dict]") -> "tuple[dict, dict]":
    """The heatmap's 2026-11-20 column as the levels producer projects it: {strike: (cell's gex,
    its contracts)}, and the surface."""
    snap = compute_terrain("SPY", contracts, _SPOT, now=_CAPTURED)
    surface = server.project_gamma_surface(contracts, snap.books)
    j = [e["expiry"] for e in surface["expirations"]].index("2026-11-20")
    by_k = {}
    for ct in contracts:
        by_k.setdefault(float(ct["strikePrice"]), []).append(ct)
    return {row["strike"]: (row["gex"][j], by_k[row["strike"]]) for row in surface["cells"]}, surface


def test_the_875_call_cell_is_its_exact_quote_gamma_times_open_interest(fetched):
    """The measured defect: the chain sends this call's gamma as 0.0, so its cell read $0 with
    23,235 contracts open. The cell is now Schwab's quote gamma x OI x 100 x spot^2 x 1%, exactly
    (its put has no open interest)."""
    chain_ct = next(c for c in SPY["chain"] if c["symbol"] == _CALL_875)
    assert chain_ct["gamma"] == 0.0 and chain_ct["openInterest"] == 23235      # what the chain sends
    gamma = _QUOTED[_CALL_875]["gamma"]
    assert gamma == 0.00037225                                                   # what the quote sends
    cells, _surface = _column(fetched())
    gex, contracts = cells[875.0]
    put = next(c for c in contracts if c["putCall"] == "PUT")
    assert put["openInterest"] == 0
    assert gex == gamma * 23235 * 100.0 * _SPOT * _SPOT * 0.01


def test_every_contract_carries_its_quotes_greeks_as_sent_and_none_of_the_chains(fetched):
    contracts = fetched()
    assert len(contracts) == len(SPY["chain"]) == 442
    for ct in contracts:
        for f in sc.GREEK_FIELDS:
            assert ct[f] == _QUOTED[ct["symbol"]][f], (ct["symbol"], f)
    rounded = {(c["symbol"], f) for c in SPY["chain"] for f in sc.GREEK_FIELDS
               if c[f] != _QUOTED[c["symbol"]][f]}
    assert len(rounded) > 1000, "the chain's rounding is what this replaces"


def test_no_cell_with_open_interest_and_greeks_reads_zero_unless_its_exact_gamma_nets_to_zero(fetched):
    """Across the whole column: on the chain's rounded gamma, cells with open interest read $0;
    on the quotes' gamma, a cell reads 0 only where its contracts' exact gamma x OI is 0."""
    def zero_cells(contracts):
        cells, _s = _column(contracts)
        oi = {k: sum(schwab_count(c["openInterest"]) or 0 for c in cts) for k, (_g, cts) in cells.items()}
        return cells, {k for k, (g, _cts) in cells.items() if oi[k] > 0 and g == 0}

    _cells, rounded_zero = zero_cells(json.loads(json.dumps(SPY["chain"])))
    assert len(rounded_zero) >= 40, len(rounded_zero)              # the defect, on the chain's values
    cells, exact_zero = zero_cells(fetched())
    for k in exact_zero:
        assert all(c["gamma"] * (schwab_count(c["openInterest"]) or 0) == 0 for c in cells[k][1]), k
    assert len(exact_zero) < len(rounded_zero)
    with_oi = [k for k, (_g, cts) in cells.items() if any((schwab_count(c["openInterest"]) or 0) > 0 for c in cts)]
    assert all(cells[k][0] is not None for k in with_oi), "every cell with open interest has its GEX"


def test_a_contract_whose_quote_did_not_come_back_has_no_greek_never_the_chains(fetched):
    """The 875 call's quote withheld: its Greeks are absent and its cell has no GEX, served with
    the reason (Schwab sent no Greek for a contract with open interest) -- never the chain's
    rounded 0.0."""
    contracts = fetched(withheld={_CALL_875})
    call = next(c for c in contracts if c["symbol"] == _CALL_875)
    assert all(call[f] is None for f in sc.GREEK_FIELDS)
    cells, surface = _column(contracts)
    assert cells[875.0][0] is None
    j = [e["expiry"] for e in surface["expirations"]].index("2026-11-20")
    row = next(r for r in surface["cells"] if r["strike"] == 875.0)
    assert row["absent"]["gex"][j] == server.CELL_EXPOSURE_NOT_SENT
    assert surface["absent_reasons"][server.CELL_EXPOSURE_NOT_SENT] == "Schwab sent no Greek/OI"
