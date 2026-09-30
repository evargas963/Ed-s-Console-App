"""Contract -> underlying: a contract is the ticker's when Schwab listed it in the ticker's chain.
One rule for every instrument, whatever the contract's root (TICK-02, 2026-09-28 audit: roots
were compared by name, and $SPX's SPXW contracts went through a second path that read a stored
capture from the database on the live path). Real chains: $SPX (SPX and SPXW roots, the same
expiration), CDE (whose root starts with C) and TSLA."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import app.options.order_flow.streaming as ofs
import server

_FX = Path(__file__).resolve().parent / "fixtures"
_SPX = json.loads((_FX / "real_spx_chain_contracts_2026_09_28.json").read_text(encoding="utf-8"))
_CDE = json.loads((_FX / "real_cde_complete_chain_half_dollar.json").read_text(encoding="utf-8"))
_TSLA = json.loads((_FX / "real_tsla_complete_chain_strike_range_all.json").read_text(encoding="utf-8"))
_CHAINS = {"$SPX": (_SPX["contracts"], _SPX["spot"]),
           "CDE": (_CDE["chain"], 5.0),                  # stand-in: the CDE capture carries no spot
           "TSLA": (_TSLA["chain"], 330.0)}              # stand-in: the TSLA capture carries no spot


@pytest.fixture(autouse=True)
def _published(monkeypatch, pin_clock):
    pin_clock(2026, 8, 30, 12, 0)                        # before every fixture chain's expiry
    spots = {tk: spot for tk, (_c, spot) in _CHAINS.items()}
    # stand-in (named): the live price
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (spots.get(tk), server.SPOT_SOURCE_PLANE, 1.0))
    monkeypatch.setattr(server, "_desired_stream_greeks_for_ticker", lambda tk, listed=None: {})
    for tk, (chain, _spot) in _CHAINS.items():
        server._publish_levels(tk, [dict(c) for c in chain], time.time(), now=time.time())
    yield
    with server._terrain_cache_lock:
        for tk in _CHAINS:
            server._terrain_cache.pop(tk, None)
    ofs._active_option_contract = None


def test_every_contract_schwab_listed_for_a_ticker_is_that_tickers_whatever_its_root():
    roots = {c["symbol"][:6].strip() for c in _SPX["contracts"]}
    assert roots == {"SPX", "SPXW"}
    for tk, (chain, _spot) in _CHAINS.items():
        assert all(server._contract_is_for(c["symbol"], tk) for c in chain), tk
        assert {server._contract_ticker(c["symbol"]) for c in chain} == {tk}


def test_a_contract_is_no_other_tickers_and_a_ticker_with_no_chain_has_none():
    cde = _CDE["chain"][0]["symbol"]
    assert not server._contract_is_for(cde, "C")              # CDE's root starts with C
    assert not server._contract_is_for(_TSLA["chain"][0]["symbol"], "$SPX")
    assert not server._contract_is_for(_SPX["contracts"][0]["symbol"], "SPY")
    assert server._contract_ticker("ZZZ   261016C00001000") is None
    assert not server._contract_is_for(None, "$SPX")


def test_the_streamed_contract_follows_the_ticker_by_the_same_rule(monkeypatch):
    """The page's ticker gets its front expiry's at-the-money call, for an index and a single
    name alike; a contract already desired for the ticker is kept (an SPXW contract for $SPX)."""
    chosen = []
    monkeypatch.setattr(ofs, "set_active_option_contract", lambda sym: chosen.append(sym) or True)
    monkeypatch.setattr(server.lmp, "daemon_status", lambda now: None)
    for tk in _CHAINS:
        ofs._active_option_contract = None
        server._ensure_default_option_contract(tk, time.time())
        with server._terrain_cache_lock:
            want = server._terrain_cache[tk]["_default_contract"]
        assert want and chosen[-1] == want and server._contract_is_for(want, tk)
    weekly = next(c["symbol"] for c in _SPX["contracts"] if c["symbol"].startswith("SPXW"))
    ofs._active_option_contract = weekly
    n = len(chosen)
    server._ensure_default_option_contract("$SPX", time.time())
    assert len(chosen) == n                               # kept: it is $SPX's
