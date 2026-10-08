"""Contract -> underlying: a contract is the ticker's when Schwab listed it in the ticker's chain, one
rule for every instrument whatever the contract's root (TICK-02, 2026-09-28 audit: roots were
compared by name). It decides which ticker an option's streamed values reprice, and that the Flow
panel's contract is one Schwab listed (question 2: the screen shows the right values promptly).

Real chains, published by the levels producer (server._publish_levels) at their capture: $SPX (SPX
and SPXW roots, the same expiration), CDE (whose root starts with C) and TSLA."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import server
from time_et import ET

_FX = Path(__file__).resolve().parent / "fixtures"
_SPX = json.loads((_FX / "real_spx_chain_contracts_2026_09_28.json").read_text(encoding="utf-8"))
_CDE = json.loads((_FX / "real_cde_complete_chain_half_dollar.json").read_text(encoding="utf-8"))
_TSLA = json.loads((_FX / "real_tsla_complete_chain_strike_range_all.json").read_text(encoding="utf-8"))
_CHAINS = {"$SPX": _SPX["contracts"], "CDE": _CDE["chain"], "TSLA": _TSLA["chain"]}
#: before every fixture chain's expiry
_VALUED = datetime(2026, 8, 30, 12, 0, tzinfo=ET)


def test_every_contract_schwab_listed_for_a_ticker_is_that_tickers_and_no_others():
    assert {c["symbol"][:6].strip() for c in _SPX["contracts"]} == {"SPX", "SPXW"}
    try:
        for tk, chain in _CHAINS.items():
            server._publish_levels(tk, [dict(c) for c in chain], _VALUED.timestamp(), now=_VALUED)
        owners = {tk: {server._contract_ticker(c["symbol"]) for c in chain} for tk, chain in _CHAINS.items()}
        unlisted = server._contract_ticker("ZZZ   261016C00001000")
    finally:
        with server._terrain_cache_lock:
            for tk in _CHAINS:
                server._terrain_cache.pop(tk, None)
    assert owners == {tk: {tk} for tk in _CHAINS}          # CDE's contracts are never C's, SPXW's are $SPX's
    assert unlisted is None
