"""DFR-005 / OP-018: strict Schwab expirationDate slice; no full-chain fallback."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server


def test_filter_contracts_by_selected_expiry_matches_schwab_leaf():
    # institutional-synthetic-ok: expiry-slice behavior needs controlled expirationDates
    # (assert exactly one match for a specific expiry) — not a greek/GEX correctness test.
    contracts = [
        {"expirationDate": "2099-05-05T20:00:00.000+00:00", "putCall": "CALL", "strikePrice": 500.0},
        {"expirationDate": "2099-06-05", "putCall": "PUT", "strikePrice": 500.0},
    ]
    filtered, src = server._filter_contracts_by_selected_expiry(contracts, "2099-05-05")
    assert len(filtered) == 1
    assert src == "schwab_expirationDate"
    assert str(filtered[0]["expirationDate"])[:10] == "2099-05-05"


def test_filter_contracts_no_full_chain_fallback_when_expiry_missing():
    contracts = [
        {"expirationDate": "2099-06-01", "putCall": "CALL"},
        {"expirationDate": "2099-07-01", "putCall": "PUT"},
    ]
    filtered, src = server._filter_contracts_by_selected_expiry(contracts, "2099-05-05")
    assert filtered == []
    assert src == "unavailable_no_contracts_for_expiry"


def test_kl_expiry_source_labels_user_vs_default():
    assert server._kl_expiry_source_label(
        expiry_param="2099-05-05",
        slice_source="schwab_expirationDate",
    ) == "schwab_expirationDate_user"
    assert server._kl_expiry_source_label(
        expiry_param=None,
        slice_source="schwab_expirationDate",
    ) == "schwab_expirationDate_default_nearest"
