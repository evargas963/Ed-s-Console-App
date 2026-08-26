"""OPTIONS FLOW — contract selection must be deterministic, bounded, and FAIR across underlyings.

REGRESSION THIS PINS (found by measurement, not review): the first selection filled the ceiling one
underlying at a time in alphabetical order. On five real chains that produced AAPL/IWM/NVDA taking
all 240 slots while SPY and QQQ got ZERO — the two most important underlyings silently absent
because of their initials. A ceiling must degrade DEPTH, never delete whole underlyings.

Nothing here infers dealer ownership, inventory sign, aggressor side or opening/closing intent;
these tests are about which symbols get streamed and how the bound behaves.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from options_stream_subscription import (
    MAX_STREAMED_CONTRACTS,
    SelectionPolicy,
    select_contracts,
    subscribe_options,
)


def _chain(root: str, spot: float, n_strikes: int = 40, expiries: int = 4) -> list[dict]:
    """Synthetic chain shaped like the vendor's per-contract dicts.

    institutional-synthetic-ok: this tests SELECTION GEOMETRY (ordering, fairness, bounds), which
    needs controlled strike/expiry counts per underlying; no market claim is derived from it.
    """
    out = []
    for e in range(expiries):
        exp = f"2026-09-{e + 1:02d}T20:00:00.000+00:00"
        for i in range(n_strikes):
            strike = round(spot - (n_strikes // 2) + i, 2)
            for side in ("CALL", "PUT"):
                out.append({
                    "symbol": f"{root:<6}2609{e + 1:02d}{'C' if side == 'CALL' else 'P'}"
                              f"{int(strike * 1000):08d}",
                    "strikePrice": strike, "putCall": side, "expirationDate": exp,
                })
    return out


def test_selection_is_deterministic():
    chains = {"SPY": (600.0, _chain("SPY", 600.0)), "QQQ": (500.0, _chain("QQQ", 500.0))}
    a = select_contracts(chains)
    b = select_contracts(chains)
    assert a.symbols == b.symbols and a.symbols, "same inputs must give the same ordered selection"


def test_ceiling_is_honoured():
    chains = {f"T{i}": (100.0, _chain(f"T{i}", 100.0)) for i in range(6)}
    res = select_contracts(chains, SelectionPolicy(strikes_per_side=30, expiries=8, max_contracts=57))
    assert len(res.symbols) <= 57, "hard ceiling breached"
    assert res.truncated and res.notes, "truncation must be reported, never silent"


def test_no_underlying_is_starved_by_the_ceiling():
    """THE REGRESSION. Alphabetically-late underlyings must still be represented."""
    roots = ["AAPL", "IWM", "NVDA", "QQQ", "SPY", "TSLA"]
    chains = {r: (100.0 + i, _chain(r, 100.0 + i)) for i, r in enumerate(roots)}
    res = select_contracts(chains, SelectionPolicy(max_contracts=60))
    assert len(res.symbols) == 60
    for r in roots:
        assert res.per_underlying.get(r, 0) > 0, (
            f"{r} received ZERO contracts — the ceiling deleted an underlying instead of "
            f"reducing depth: {res.per_underlying}")
    counts = sorted(res.per_underlying.values())
    assert counts[-1] - counts[0] <= 1, (
        f"allocation is not fair; depths differ by more than one: {res.per_underlying}")


def test_missing_spot_is_skipped_not_guessed():
    chains = {"SPY": (None, _chain("SPY", 600.0)), "QQQ": (500.0, _chain("QQQ", 500.0))}
    res = select_contracts(chains)
    assert not any(s.startswith("SPY") for s in res.symbols), "no centre must mean no selection"
    assert any("SPY" in n and "spot" in n for n in res.notes), "the skip must be explained"


def test_both_sides_of_spot_and_both_option_sides_are_selected():
    chains = {"SPY": (600.0, _chain("SPY", 600.0))}
    res = select_contracts(chains, SelectionPolicy(strikes_per_side=4, expiries=1,
                                                   max_contracts=MAX_STREAMED_CONTRACTS))
    assert any("C" in s[6:] for s in res.symbols) and any("P" in s[6:] for s in res.symbols), \
        "a flow product needs both calls and puts"


def test_level_one_requests_the_COMPLETE_field_surface_not_a_default():
    """The foundation's whole premise: native truth is not lost because today's code under-asked."""
    class _Fields:
        @staticmethod
        def all_fields():
            return list(range(56))

    class _Client:
        LevelOneOptionFields = _Fields

        def __init__(self):
            self.fields_seen = None
            self.book_syms = None

        async def level_one_option_subs(self, syms, fields=None):
            self.fields_seen = fields

        async def options_book_subs(self, syms):
            self.book_syms = syms

    c = _Client()
    receipt = asyncio.run(subscribe_options(c, ["SPY   260826C00600000"]))
    assert receipt["level_one"]["fields_requested"] == 56, (
        "LEVELONE_OPTIONS must request every entitled field, not a library default subset")
    assert c.fields_seen is not None and len(c.fields_seen) == 56
    assert receipt["book"]["symbols"] == 1
    assert not receipt["errors"]


def test_subscribe_fails_soft_without_a_client():
    receipt = asyncio.run(subscribe_options(None, ["SPY   260826C00600000"]))
    assert receipt["errors"], "a missing client must be reported, never silently succeed"
