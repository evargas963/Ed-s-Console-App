"""Every chain enters the app with Schwab's exact Greeks (operator, 2026-10-01: "you must use what
schwab gives us... no rounding, use the exact data that schwab gives us everywhere").

Schwab's option chain sends gamma, delta, theta, vega, rho and volatility rounded to 3 decimals; its
quotes endpoint sends the same contract's unrounded. schwab_client.fetch_full_chain, the one place
a chain enters (the capture daemon's chain sweep), replaces each contract's Greeks
with its quote's, so the heatmap, the levels, the per-strike rows and the forces read them unchanged.

Real data (tests/fixtures/real_spy_2026_11_20_chain_and_quotes.json): SPY's 2026-11-20 contracts
from the capture daemon's full-chain capture of 2026-09-30 15:31:57 ET, and Schwab's quotes for every
one of them as answered at 2026-10-01 04:52 ET. Schwab's network is the only stand-in: `_Schwab`
answers the chain with the captured contracts and each quotes request with the recorded quotes of
the symbols it asks for.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import schwab_client as sc
import server
import time_et
from numeric_contract import schwab_count
from terrain_engine import compute_terrain

_FX = json.loads((Path(__file__).resolve().parent / "fixtures"
                  / "real_spy_2026_11_20_chain_and_quotes.json").read_text(encoding="utf-8"))
_SPOT = float(_FX["spot"])
_CAPTURED = datetime.fromtimestamp(_FX["capture_ts_utc"], time_et.ET)
_QUOTED = {s: e["quote"] for q in _FX["quotes"] for s, e in q["reply"].items()}
_CALL_875 = "SPY   261120C00875000"


class _Resp:
    def __init__(self, status_code: int, payload: "dict | None" = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> dict:
        return self._payload


class _Schwab:
    """Schwab's network (the stand-in): the captured chain, and the recorded quotes of whatever
    symbols a request asks for. `withheld` symbols get no quote back; `refused` answers every
    quotes request with that HTTP status."""

    def __init__(self, withheld: "set[str] | None" = None, refused: "int | None" = None):
        self.withheld = withheld or set()
        self.refused = refused
        self.asked: "list[list[str]]" = []

    def chain(self, **dates) -> _Resp:
        payload = {"symbol": "SPY", "underlyingPrice": _SPOT, "callExpDateMap": {}, "putExpDateMap": {}}
        for ct in json.loads(json.dumps(_FX["chain"])):
            side = "callExpDateMap" if ct["putCall"] == "CALL" else "putExpDateMap"
            key = f"{ct['expirationDate'][:10]}:{ct['daysToExpiration']}"
            payload[side].setdefault(key, {}).setdefault(str(ct["strikePrice"]), []).append(ct)
        return _Resp(200, payload)

    def quote(self, symbols: "list[str]") -> _Resp:
        self.asked.append(list(symbols))
        if self.refused is not None:
            return _Resp(self.refused)
        return _Resp(200, {s: {"symbol": s, "quote": dict(_QUOTED[s])}
                           for s in symbols if s in _QUOTED and s not in self.withheld})


def _fetched(schwab: _Schwab) -> "list[dict]":
    resp = sc.fetch_full_chain(schwab, "SPY", schwab.chain, schwab.quote)
    assert resp.status_code == 200
    return sc.flatten_chain_contracts(resp.json())


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


@pytest.fixture(autouse=True)
def _at_capture(monkeypatch):
    """Valued at the capture's own time, so the expiry passing never changes what is measured."""
    monkeypatch.setattr(time_et, "now_et", lambda: _CAPTURED)


def test_the_875_call_cell_is_its_exact_quote_gamma_times_open_interest():
    """The measured defect: the chain sends this call's gamma as 0.0, so its cell read $0 with
    23,235 contracts open. The cell is now Schwab's quote gamma x OI x 100 x spot^2 x 1%, exactly
    (its put has no open interest)."""
    chain_ct = next(c for c in _FX["chain"] if c["symbol"] == _CALL_875)
    assert chain_ct["gamma"] == 0.0 and chain_ct["openInterest"] == 23235      # what the chain sends
    gamma = _QUOTED[_CALL_875]["gamma"]
    assert gamma == 0.00037225                                                   # what the quote sends
    cells, _surface = _column(_fetched(_Schwab()))
    gex, contracts = cells[875.0]
    put = next(c for c in contracts if c["putCall"] == "PUT")
    assert put["openInterest"] == 0
    assert gex == gamma * 23235 * 100.0 * _SPOT * _SPOT * 0.01


def test_every_contract_carries_its_quotes_greeks_as_sent_and_none_of_the_chains():
    contracts = _fetched(_Schwab())
    assert len(contracts) == len(_FX["chain"]) == 442
    for ct in contracts:
        for f in sc.GREEK_FIELDS:
            assert ct[f] == _QUOTED[ct["symbol"]][f], (ct["symbol"], f)
    rounded = {(c["symbol"], f) for c in _FX["chain"] for f in sc.GREEK_FIELDS
               if c[f] != _QUOTED[c["symbol"]][f]}
    assert len(rounded) > 1000, "the chain's rounding is what this replaces"


def test_no_cell_with_open_interest_and_greeks_reads_zero_unless_its_exact_gamma_nets_to_zero():
    """Across the whole column: on the chain's rounded gamma, cells with open interest read $0;
    on the quotes' gamma, a cell reads 0 only where its contracts' exact gamma x OI is 0."""
    def zero_cells(contracts):
        cells, _s = _column(contracts)
        oi = {k: sum(schwab_count(c["openInterest"]) or 0 for c in cts) for k, (_g, cts) in cells.items()}
        return cells, {k for k, (g, _cts) in cells.items() if oi[k] > 0 and g == 0}

    _cells, rounded_zero = zero_cells(json.loads(json.dumps(_FX["chain"])))
    assert len(rounded_zero) >= 40, len(rounded_zero)              # the defect, on the chain's values
    cells, exact_zero = zero_cells(_fetched(_Schwab()))
    for k in exact_zero:
        assert all(c["gamma"] * (schwab_count(c["openInterest"]) or 0) == 0 for c in cells[k][1]), k
    assert len(exact_zero) < len(rounded_zero)
    with_oi = [k for k, (_g, cts) in cells.items() if any((schwab_count(c["openInterest"]) or 0) > 0 for c in cts)]
    assert all(cells[k][0] is not None for k in with_oi), "every cell with open interest has its GEX"


def test_a_contract_whose_quote_did_not_come_back_has_no_greek_never_the_chains():
    """The 875 call's quote withheld: its Greeks are absent and its cell has no GEX, served with
    the reason (Schwab sent no Greek for a contract with open interest) -- never the chain's
    rounded 0.0."""
    contracts = _fetched(_Schwab(withheld={_CALL_875}))
    call = next(c for c in contracts if c["symbol"] == _CALL_875)
    assert all(call[f] is None for f in sc.GREEK_FIELDS)
    cells, surface = _column(contracts)
    assert cells[875.0][0] is None
    j = [e["expiry"] for e in surface["expirations"]].index("2026-11-20")
    row = next(r for r in surface["cells"] if r["strike"] == 875.0)
    assert row["absent"]["gex"][j] == server.CELL_EXPOSURE_NOT_SENT
    assert surface["absent_reasons"][server.CELL_EXPOSURE_NOT_SENT] == "Schwab sent no Greek/OI"


def test_a_refused_quotes_batch_fails_the_chain():
    """Schwab answering HTTP 429 to a quotes batch: the chain fails with that status and its
    reason, so the levels keep their last good publication with the failure as their stale reason
    (a book missing a batch of Greeks published as the book flipped the regime and walls in the
    PR #431 review). Every batch is asked at once (operator 2026-10-01)."""
    schwab = _Schwab(refused=429)
    resp = sc.fetch_full_chain(schwab, "SPY", schwab.chain, schwab.quote)
    assert resp.status_code == 429
    assert "returned HTTP 429" in resp.reason


def test_quotes_are_asked_in_batches_of_at_most_300_every_contract_once():
    schwab = _Schwab()
    _fetched(schwab)
    assert [len(b) for b in schwab.asked] == [300, 142]
    asked = [s for b in schwab.asked for s in b]
    assert sorted(asked) == sorted(c["symbol"] for c in _FX["chain"])
