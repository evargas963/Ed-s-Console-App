"""The gamma heatmap, Schwab to the screen: a cell with no value is served as None and drawn "-",
with nothing saying why (AGENTS.md rule 5).

Real data: NFLX's chain as production's complete_chain_captures held it (tests/real_chains.py
NFLX): on 2027-12-17 and 2028-01-21, 8 contracts with open interest whose Greeks Schwab sent as
-999, so their cells have no GEX; and strikes no contract is listed at in a column.
"""
from __future__ import annotations

from tests.gamma_render_helper import drawn
from tests.real_chains import NFLX


def test_the_page_draws_every_cell_with_no_value_as_a_dash(tmp_path):
    """Schwab's chain published by the levels producer, served by the heatmap's answer and drawn
    by the page: every cell with no value draws "-", those with open interest whose Greeks Schwab
    sent as -999 as the strikes no contract is listed at. Nothing says why a value is missing."""
    surface, text = drawn(NFLX.ticker, NFLX.chain, NFLX.spot, NFLX.now, tmp_path)
    exps = [e["expiry"] for e in surface["expirations"]]
    listed = {(float(c["strikePrice"]), c["expirationDate"][:10]) for c in NFLX.chain}
    no_greek = {(float(c["strikePrice"]), c["expirationDate"][:10]) for c in NFLX.chain
                if c["openInterest"] > 0 and -999.0 in (c["gamma"], c["delta"], c["volatility"])}
    gex = {(r["strike"], exps[j]): v for r in surface["cells"] for j, v in enumerate(r["gex"])}
    assert no_greek and set(gex) - listed
    assert all(gex[cell] is None for cell in no_greek | (set(gex) - listed))
    assert {text[cell] for cell, v in gex.items() if v is None} == {"-"}
    assert "absent_reasons" not in surface and not any("absent" in r for r in surface["cells"])
