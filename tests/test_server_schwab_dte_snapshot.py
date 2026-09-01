"""The snapshot writer's DTE/hours-to-expiry must use Schwab's own daysToExpiration
field (never a locally date-subtracted approximation) and fail closed when that
field is missing, including correctly handling an early-close session."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server


def test_snapshot_dte_uses_selected_schwab_days_to_expiration():
    # institutional-synthetic-ok: DTE-selection test needs controlled per-contract DTEs.
    contracts = [
        {
            "expirationDate": "2099-05-05",
            "putCall": "CALL",
            "strikePrice": 500.0,
            "daysToExpiration": 2,
        },
        {
            "expirationDate": "2099-05-05",
            "putCall": "PUT",
            "strikePrice": 500.0,
            "daysToExpiration": 3,
        },
    ]

    assert server._selected_schwab_days_to_expiration(
        contracts,
        "2099-05-05",
        preferred_strike=500.0,
        preferred_side="CALL",
    ) == 2


def test_snapshot_dte_fails_closed_when_schwab_days_to_expiration_missing():
    # institutional-synthetic-ok: fail-closed test omits daysToExpiration deliberately.
    contracts = [
        {
            "expirationDate": "2099-05-05",
            "putCall": "CALL",
            "strikePrice": 500.0,
        }
    ]

    assert server._selected_schwab_days_to_expiration(
        contracts,
        "2099-05-05",
        preferred_strike=500.0,
        preferred_side="CALL",
    ) is None


def test_snapshot_hours_to_expiry_uses_schwab_dte_without_date_subtraction():
    now_et = datetime(2026, 5, 5, 10, 30, tzinfo=__import__('time_et', fromlist=['ET']).ET)

    assert server._snapshot_expiry_hours_from_schwab_dte(0, now_et) == 5.5
    assert server._snapshot_expiry_hours_from_schwab_dte(None, now_et) is None


def test_snapshot_hours_to_expiry_uses_early_close_not_1600():
    from time_et import ET

    early = datetime(2026, 11, 27, 11, 0, tzinfo=ET)
    assert server._snapshot_expiry_hours_from_schwab_dte(0, early) == 2.0
    after_close = datetime(2026, 11, 27, 14, 0, tzinfo=ET)
    assert server._snapshot_expiry_hours_from_schwab_dte(0, after_close) is None
    # dte>0 without expiry date is not a clock (pre-fix DTE*24 + today's remainder).
    assert server._snapshot_expiry_hours_from_schwab_dte(1, early) is None
    # Early-close Friday 11:00 ET -> Monday 16:00 ET regular close.
    assert server._snapshot_expiry_hours_from_schwab_dte(
        3, early, expiry_et_date="2026-11-30"
    ) == 77.0
    # Pre-fix: DTE*24 + today's 13:00 remainder = 74.0 (lands Monday 13:00).
    assert server._snapshot_expiry_hours_from_schwab_dte(
        3, early, expiry_et_date="2026-11-30"
    ) != round(3 * 24.0 + 2.0, 2)
    # Regular Wednesday -> early-close Friday: expiry close is 13:00, not today's 16:00 + 2*24.
    wed = datetime(2026, 11, 25, 11, 0, tzinfo=ET)
    assert server._snapshot_expiry_hours_from_schwab_dte(
        2, wed, expiry_et_date="2026-11-27"
    ) == 50.0
    assert 50.0 != round(2 * 24.0 + 5.0, 2)
