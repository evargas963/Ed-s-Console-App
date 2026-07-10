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


# ── VOL_INPUT_CONTRACT 1.0.0 (lane V1) — replay unit boundary (VOL-UNIT-001) ──
# Golden records are checked-in fixture dicts (no DB dependency) per the
# ratified freeze (Matrix 11). GR-2 is the defect-killing record.

from features.replay_signal_input_v1 import (  # noqa: E402
    REPLAY_ROUTE_IDENTITY,
    VOL_INPUT_CONTRACT_VERSION,
    _replay_vol_decimal,
)
from volatility_regime import vol_percent_to_decimal  # noqa: E402

GOLDEN_GR2 = _row(
    vix_level=26.0, vix_direction="rising", vix_vs_prev=3.5,
    iv_level=18.5, realized_vol=18.5,
)


def test_gr2_percent_row_converts_to_decimal_both_fields():
    """GR-2: percent row 18.5 -> 0.185 on both fields (kills VOL-UNIT-001)."""
    inp = signal_input_from_snapshot_row_dict(GOLDEN_GR2)
    assert inp.iv_level == pytest.approx(0.185)
    assert inp.realized_vol == pytest.approx(0.185)


def test_gr1_replay_equals_live_conversion_boundary():
    """GR-1: replay-built vol fields equal the live boundary function's output
    for the same persisted values — same canonical function, one conversion."""
    row = _row(iv_level=22.0, realized_vol=18.0)
    inp = signal_input_from_snapshot_row_dict(row)
    assert inp.iv_level == vol_percent_to_decimal(22.0) == 0.22
    assert inp.realized_vol == vol_percent_to_decimal(18.0) == 0.18


def test_gr3_missing_vol_fields_stay_missing_never_zero():
    """GR-3: missing stays None — absence is never directional evidence."""
    inp = signal_input_from_snapshot_row_dict(_row())
    assert inp.iv_level is None
    assert inp.realized_vol is None
    assert inp.vix_vs_prev is None
    assert inp.vix_direction is None


def test_replay_zero_stays_zero_where_valid():
    inp = signal_input_from_snapshot_row_dict(_row(realized_vol=0.0))
    assert inp.realized_vol == 0.0


def test_replay_invalid_negative_becomes_unavailable():
    """Ratified range (0, 5.0] internal: negatives are classified unavailable
    (None), never passed through as fake evidence."""
    inp = signal_input_from_snapshot_row_dict(_row(iv_level=-3.0, realized_vol=-1.0))
    assert inp.iv_level is None
    assert inp.realized_vol is None


def test_replay_no_double_conversion_for_already_decimal():
    """An already-decimal value (<= heuristic passthrough) is not divided again."""
    assert _replay_vol_decimal(0.185) == pytest.approx(0.185)
    assert _replay_vol_decimal(_replay_vol_decimal(18.5)) == pytest.approx(0.185)


def test_replay_route_identity_and_contract_version_constants():
    assert REPLAY_ROUTE_IDENTITY == "replay"
    assert VOL_INPUT_CONTRACT_VERSION == "1.0.0"


def test_replay_msd001_fields_still_carried_from_row():
    """MSD-001 parity: replay continues to carry direction/change columns —
    now the LIVE route stamps the same fields from the per-cycle context."""
    inp = signal_input_from_snapshot_row_dict(GOLDEN_GR2)
    assert inp.vix_direction == "rising"
    assert inp.vix_vs_prev == 3.5
    assert inp.vix_level == 26.0
