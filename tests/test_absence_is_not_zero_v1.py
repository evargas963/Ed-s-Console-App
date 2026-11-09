"""RC-274 — a missing measurement must not be stored, summed, or drawn as the number zero.

WHAT WAS MEASURED (2026-08-06). `test_no_schwab_leaf_zero_injection_repo_wide` had been
failing with 13 production hits of the `float(x or 0.0)` family. Nine were harmless: a
`<= 0` or RTH guard rejected the fabricated zero on the very next line. Four were not, and
those four are what this file drives:

    desk_store.materialize_short_volume    NULL short_volume / total -> ratio 0.0 stored
                                           under tier "MEASURED"
    desk_store.materialize_dollar_volume   NULL close * volume -> 0 dollars added to the
                                           turnover that ADV ranks names on
    desk_store.materialize_options_listed  NULL n_strikes -> written as 0, tier "MEASURED"
    terrain_engine._per_strike_rows        gamma unresolvable -> a 0.0 bar on the chart

WHY THE PATTERN SURVIVED SO LONG. `or 0.0` is a real type-narrowing idiom for Optional, and
at nine of the thirteen sites that is exactly what it was. One shape carried two meanings and
the reader had to hold both at once. These tests assert the BEHAVIOUR: feed each function a
NULL and prove the zero never reaches the fact table, the sum, or the frame.

THE TEST THAT WOULD HAVE CAUGHT IT is not a stricter regex. It is this: write a NULL into the
source table and read what comes out the other end.

Real data: CRWD's 2026-10-16 expiry captured 2026-10-07 10:38:40 ET (tests/real_chains.py), summed
per strike by math_exposure_core.compute_exposures_by_strike; SPY's CHART_EQUITY bars of 2026-10-01
as the capture daemon recorded them (real_daemon_bars_spy_tsla_2026_10_01_02.json). Induced
(named): a field taken out of a real contract or bar, as Schwab leaves a field out.
"""

from __future__ import annotations

import pytest

import terrain_engine as TE
from liquidity_models import volume_profile
from math_exposure_core import compute_exposures_by_strike
from option_contract import read_chain
from tests.feed_live_helper import daemon_bars
from tests.real_chains import CRWD

_BARS = daemon_bars("real_daemon_bars_spy_tsla_2026_10_01_02.json", "SPY")


def _exposures(chain: list[dict]) -> dict[float, dict]:
    return compute_exposures_by_strike(read_chain(chain), spot=CRWD.spot, now=CRWD.now)[0]


def _at(strike: float) -> dict[str, dict]:
    return {ct["putCall"]: ct for ct in CRWD.chain if ct["strikePrice"] == strike}


# ---------------------------------------- an unknown gamma is not a flat gamma bar ----


def test_a_strike_with_no_resolvable_gamma_draws_no_bar():
    """The exact law stated four lines above the defect, applied to the value as well.

    `terrain_engine` already refuses to draw a NaN STRIKE ("a NaN strike must never become a
    rendered bar"). An unknown GAMMA was drawn at 0.0 anyway -- visually identical to a strike
    measured at flat gamma, on the surface used to read where dealers are short.
    """
    rows = TE._per_strike_rows({500.0: {}})
    assert rows == [], f"drew a bar for a strike with no gamma: {rows}"


def test_a_measured_gamma_still_draws_its_bar():
    """Negative control: absence is refused, presence is not.

    Strike 270's net GEX per 1%: gamma * open interest * multiplier * spot^2 * 0.01, calls less
    puts, worked out from Schwab's fields.
    """
    legs = _at(270.0)
    gex = {
        side: ct["gamma"] * ct["openInterest"] * ct["multiplier"] * CRWD.spot * CRWD.spot * 0.01
        for side, ct in legs.items()
    }
    rows = [r for r in TE._per_strike_rows(_exposures(CRWD.chain)) if r[0] == 270.0]
    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(270.0)
    assert rows[0][1] == pytest.approx(gex["CALL"] - gex["PUT"], rel=1e-12)
    assert rows[0][1] != 0.0


def test_a_genuine_zero_gamma_still_draws_its_bar():
    """A strike measured at flat gamma is information and must remain on the chart.

    Strike 297.5: Schwab sent open interest 0 on both sides.
    """
    assert [ct["openInterest"] for ct in _at(297.5).values()] == [0, 0]
    rows = [r for r in TE._per_strike_rows(_exposures(CRWD.chain)) if r[0] == 297.5]
    assert len(rows) == 1 and rows[0][1] == pytest.approx(0.0)


def test_a_strike_with_a_contract_whose_gamma_term_was_not_sent_has_gex_unknown():
    """A contract at the strike sent no open interest (or has open interest and no Greek).

    The strike's GEX is not known, whatever its accumulator holds.
    """
    chain = [dict(ct) for ct in CRWD.chain]
    call = next(c for c in chain if c["strikePrice"] == 270.0 and c["putCall"] == "CALL")
    assert call["openInterest"] > 0
    del call["gamma"]
    rows = TE._per_strike_rows(_exposures(chain))
    assert [r[:2] for r in rows if r[0] == 270.0] == [[270.0, None]]


# ------------------------------------- a NULL bar volume is not zero traded volume ----


def test_a_null_volume_bar_does_not_enter_the_volume_profile():
    """One bar priced and one bar absent must give the priced bar's POC, not a blend."""
    priced, other = _BARS[0], next(b for b in _BARS if b["low"] > _BARS[0]["high"])
    absent = dict(other, volume=None)
    assert volume_profile([absent, priced]).poc == pytest.approx(volume_profile([priced]).poc), (
        "an unmeasured bar moved the point of control"
    )
    assert volume_profile([other, priced]).poc != volume_profile([priced]).poc


def test_no_usable_volume_still_reads_as_absence():
    """The docstring's own promise: absence reads as absence, never a fabricated level."""
    assert volume_profile([dict(_BARS[0], volume=None)]) is None
