"""RC-68: the terrain engine must RETAIN the live per-strike map, not discard it.

compute_exposures_by_strike already runs on every ~60s terrain refresh; its result was used to
pick the walls and then thrown away, which forced /api/terrain/strikes to render the per-strike
gamma+volume histogram from the FROZEN option_chain_morning_full archive. MEASURED 2026-07-27 on
SPY: a 09:47 capture served at 11:31 understated session volume by 281 percent (1,095,874 shown
vs 4,176,672 live), with ~500K missing on strike 740 alone.

These lock the retention and its numeric contract so the panel can never silently regress to the
archive, and so a NaN vendor leaf can never enter the histogram as a value.

Real data: SPY's whole chain of 2026-11-09 11:06 ET, 35 expiries (tests/real_chains.py).
"""

from __future__ import annotations

import time_et
from calc.math_exposure_core import compute_exposures_by_strike
from calc.terrain_engine import TerrainSnapshot, compute_terrain, per_strike_view
from option_contract import read_chain
from tests.real_chains import SPY_FULL


def test_an_unknown_dte_keeps_its_contract_in_its_own_expiry():
    """A daysToExpiration that is not a number is no DTE, and its contract stays in its expiry.

    The contract record's `days_to_expiry` is None for an unreadable DTE (never a sentinel). A
    strike view's rows are an expiry's contracts by Schwab's expirationDate, so the contract is
    in the rows of the expiry it was listed under, whatever its DTE. INDUCED CONDITIONS: three of
    SPY's contracts with a daysToExpiration that is not a number, absent, and infinite.
    """
    rows = [dict(c) for c in SPY_FULL.chain]
    rows[0]["daysToExpiration"] = float("nan")
    del rows[1]["daysToExpiration"]
    rows[2]["daysToExpiration"] = float("inf")
    contracts = read_chain(rows)
    assert contracts[0].days_to_expiry is None
    assert contracts[1].days_to_expiry is None
    assert contracts[2].days_to_expiry is None
    view = compute_terrain(
        SPY_FULL.ticker, contracts, SPY_FULL.spot, now=SPY_FULL.now, sessions=time_et.sessions()
    ).per_strike
    # every expiry Schwab listed is a choice, the three's own included
    assert set(view["by_expiry"]) == {r["expirationDate"][:10] for r in rows}
    for c in contracts[:3]:
        assert c.strike in {r.strike for r in view["by_expiry"][c.expiry]["gex"]}


def test_a_book_priced_with_no_price_has_no_dollar_rows_and_keeps_its_counts():
    """SPY's whole chain priced with no price: a book with no dollars in it.

    Its GEX and DEX rows are dollars, so it has none; its open interest and vanna rows are each
    strike's, as the book holds them.
    """
    raw, _diag = compute_exposures_by_strike(
        read_chain(SPY_FULL.chain), spot=None, now=SPY_FULL.now, sessions=time_et.sessions()
    )
    view = per_strike_view({}, raw, {}, {})
    assert raw and (view["gex"], view["dex"]) == ([], [])
    assert [r.strike for r in view["oi"]] == [r.strike for r in view["vanna"]] == sorted(raw)


def test_a_chain_with_no_strike_or_no_days_to_expiration_says_what_it_lacks():
    """INDUCED on SPY's whole chain: every strikePrice taken out, then every daysToExpiration.

    With no strike nothing is exposed at any price: the levels are unavailable, saying so. With
    no days to expiration no expiry is the front one, so max pain, the front expiry's, is "-".
    """
    struck_out = [{k: v for k, v in c.items() if k != "strikePrice"} for c in SPY_FULL.chain]
    undated = [{k: v for k, v in c.items() if k != "daysToExpiration"} for c in SPY_FULL.chain]

    def terrain(rows):
        return compute_terrain(
            SPY_FULL.ticker,
            read_chain(rows),
            SPY_FULL.spot,
            now=SPY_FULL.now,
            sessions=time_et.sessions(),
        )

    assert terrain(struck_out).error == "chain produced no exposures"
    dated, no_days = terrain(SPY_FULL.chain), terrain(undated)
    assert dated.max_pain is not None and dated.error == ""
    assert (no_days.max_pain, no_days.max_pain_dte, no_days.error) == (None, None, "")


def test_per_strike_is_excluded_from_to_dict_but_timestamp_is_not():
    """per_strike is hundreds of entries — too heavy for every poll.

    Same reason `profile` is excluded. computed_ts_utc MUST survive: every consumer has to be
    able to render an age.
    """
    snap = TerrainSnapshot(ticker=SPY_FULL.ticker, spot=SPY_FULL.spot)
    d = snap.to_dict()
    assert "per_strike" not in d
    assert "profile" not in d
    assert "computed_ts_utc" in d


def test_snapshot_defaults_are_absent_not_fabricated():
    snap = TerrainSnapshot(ticker=SPY_FULL.ticker, spot=SPY_FULL.spot)
    assert snap.per_strike == per_strike_view({}, {}, {}, {}), "no book priced: the producer's view"
    assert set(snap.per_strike) == {"gex", "dex", "oi", "vanna", "charm", "settled", "by_expiry"}
    assert all(not rows for rows in snap.per_strike.values()), "no row is fabricated"
    assert snap.computed_ts_utc is None, "absence must read as absence, never a fake timestamp"
