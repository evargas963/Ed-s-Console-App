"""A bar whose volume Schwab did not report is not zero traded volume."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from liquidity_models import volume_profile  # noqa: E402


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

