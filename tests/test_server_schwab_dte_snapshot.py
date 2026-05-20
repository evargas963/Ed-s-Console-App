from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server


def test_snapshot_dte_uses_selected_schwab_days_to_expiration():
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
