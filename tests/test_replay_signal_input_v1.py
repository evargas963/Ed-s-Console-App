from __future__ import annotations

import pytest

from features.replay_signal_input_v1 import signal_input_from_snapshot_row_dict
from timeframe_config import CANONICAL_TIMEFRAME


def _row(**overrides):
    base = {
        "ticker": "SPY",
        "timeframe": CANONICAL_TIMEFRAME,
        "spot": 500.0,
        "ts_utc": 1_700_000_000.0,
    }
    base.update(overrides)
    return base


def test_signal_input_from_snapshot_row_uses_positive_spot():
    inp = signal_input_from_snapshot_row_dict(_row(spot="501.25"))

    assert inp.spot == 501.25
    assert inp.ticker == "SPY"


@pytest.mark.parametrize("bad_spot", [None, "", 0, -1, "not-a-number"])
def test_signal_input_from_snapshot_row_fails_closed_on_missing_or_invalid_spot(bad_spot):
    with pytest.raises(ValueError, match="spot"):
        signal_input_from_snapshot_row_dict(_row(spot=bad_spot))
