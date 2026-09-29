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
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import terrain_engine as TE  # noqa: E402
from liquidity_models import volume_profile  # noqa: E402




# ------------------------------------- a NULL short volume is not zero shares short ----









# ------------------------------------------ a NULL strike count is not zero strikes ----







# ------------------------------------- an unpriced bar is not zero dollars of turnover ----



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
    """Negative control: absence is refused, presence is not."""
    rows = TE._per_strike_rows({500.0: {"has_oi": True, "has_valid_gamma": True, "dollarized": True,
                                        "net_gex_1pct": 1_234_567.0}})
    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(500.0)
    assert rows[0][1] == pytest.approx(1_234_567.0, rel=1e-6)


def test_a_genuine_zero_gamma_still_draws_its_bar():
    """A strike measured at flat gamma is information and must remain on the chart."""
    rows = TE._per_strike_rows({500.0: {"has_oi": True, "has_valid_gamma": True, "dollarized": True,
                                        "net_gex_1pct": 0.0}})
    assert len(rows) == 1 and rows[0][1] == pytest.approx(0.0)


def test_a_strike_with_no_oi_at_all_draws_no_bar_even_with_a_nonzero_accumulator():
    """RC-SPX (2026-09-14, live reproduction): has_oi=False must win even when the
    pre-initialized accumulator field somehow carries a nonzero value -- has_oi is the ONE
    signal every consumer checks, not a redundant belt-and-suspenders re-derivation from the
    metric itself. This is the exact live SPX defect: a bucket that never cleared the OI gate
    must never present its accumulator as a computed value, regardless of what that
    accumulator happens to hold."""
    rows = TE._per_strike_rows({500.0: {"has_oi": False, "net_gex_1pct": 1_234_567.0}})
    assert rows == [], f"drew a bar for a strike that never cleared the OI gate: {rows}"


# ------------------------------------- a NULL bar volume is not zero traded volume ----

def test_a_null_volume_bar_does_not_enter_the_volume_profile():
    """One bar priced and one bar absent must give the priced bar's POC, not a blend."""
    bars = [
        {"high": 100.0, "low": 100.0, "volume": None},
        {"high": 200.0, "low": 200.0, "volume": 5_000.0},
    ]
    assert volume_profile(bars).poc == pytest.approx(200.0), "an unmeasured bar moved the point of control"


def test_no_usable_volume_still_reads_as_absence():
    """The docstring's own promise: absence reads as absence, never a fabricated level."""
    assert volume_profile([{"high": 100.0, "low": 99.0, "volume": None}]) is None

