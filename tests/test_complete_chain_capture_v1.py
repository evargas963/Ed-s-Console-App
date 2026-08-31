"""OPTIONS_ORDER_FLOW_V1 — calibration/complete_chain_capture.py direct unit tests.

The canonical persistence for the COMPLETE vendor chain, distinct from the bounded
analytical snapshots (`snapshots.option_chain_json`) and from option_chain_morning_full.py
(near-term multi-expiry, once-daily). Uses the real captured TSLA fixture (real fractional
strikes, live strike_range=ALL capture) to prove the round trip preserves the exact contract
set — no rounding, no coercion, no dropped rows.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from calibration.complete_chain_capture import (
    latest_complete_chain_capture,
    persist_complete_chain_capture,
)

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "real_tsla_complete_chain_strike_range_all.json")
    .read_text(encoding="utf-8")
)
_TSLA_CONTRACTS = _FIXTURE["chain"]
_TSLA_EXPIRY = _FIXTURE["expiry"]


def test_persist_and_read_back_exact_contract_set(tmp_path):
    db_path = tmp_path / "cap.db"
    result = persist_complete_chain_capture(
        db_path, ticker="TSLA", expiry=_TSLA_EXPIRY, contracts=_TSLA_CONTRACTS,
        spot=350.0, completeness_basis="strike_range=ALL", ts_utc=1000.0)
    assert result["status"] == "written"
    assert result["n_contracts"] == len(_TSLA_CONTRACTS)

    cap = latest_complete_chain_capture(db_path, "TSLA", _TSLA_EXPIRY)
    assert cap is not None
    persisted_symbols = {c["symbol"] for c in cap["contracts"]}
    vendor_symbols = {c["symbol"] for c in _TSLA_CONTRACTS}
    assert persisted_symbols == vendor_symbols, "exact contract-symbol set equality"
    assert len(cap["contracts"]) == len(_TSLA_CONTRACTS), "no duplicate rows"

    # Fractional strikes survive the DB round trip byte-for-byte.
    frac_symbol = next(c["symbol"] for c in _TSLA_CONTRACTS if c["strikePrice"] % 1 != 0)
    vendor_row = next(c for c in _TSLA_CONTRACTS if c["symbol"] == frac_symbol)
    persisted_row = next(c for c in cap["contracts"] if c["symbol"] == frac_symbol)
    assert persisted_row == vendor_row


def test_latest_returns_the_newest_of_multiple_captures(tmp_path):
    db_path = tmp_path / "cap.db"
    old_contracts = _TSLA_CONTRACTS[:5]
    new_contracts = _TSLA_CONTRACTS[:10]
    persist_complete_chain_capture(
        db_path, ticker="TSLA", expiry=_TSLA_EXPIRY, contracts=old_contracts,
        spot=340.0, completeness_basis="strike_range=ALL", ts_utc=1000.0)
    persist_complete_chain_capture(
        db_path, ticker="TSLA", expiry=_TSLA_EXPIRY, contracts=new_contracts,
        spot=350.0, completeness_basis="strike_range=ALL", ts_utc=2000.0)

    cap = latest_complete_chain_capture(db_path, "TSLA", _TSLA_EXPIRY)
    assert cap["ts_utc"] == 2000.0
    assert cap["n_contracts"] == 10
    assert cap["spot"] == 350.0


def test_no_row_for_a_different_expiry(tmp_path):
    db_path = tmp_path / "cap.db"
    persist_complete_chain_capture(
        db_path, ticker="TSLA", expiry=_TSLA_EXPIRY, contracts=_TSLA_CONTRACTS,
        spot=350.0, completeness_basis="strike_range=ALL", ts_utc=1000.0)
    assert latest_complete_chain_capture(db_path, "TSLA", "2099-01-01") is None


def test_no_row_for_a_different_ticker(tmp_path):
    db_path = tmp_path / "cap.db"
    persist_complete_chain_capture(
        db_path, ticker="TSLA", expiry=_TSLA_EXPIRY, contracts=_TSLA_CONTRACTS,
        spot=350.0, completeness_basis="strike_range=ALL", ts_utc=1000.0)
    assert latest_complete_chain_capture(db_path, "SPY", _TSLA_EXPIRY) is None


def test_missing_db_file_reads_as_none_not_an_exception(tmp_path):
    assert latest_complete_chain_capture(tmp_path / "does_not_exist.db", "TSLA", _TSLA_EXPIRY) is None


def test_write_skips_empty_contracts_fail_closed(tmp_path):
    db_path = tmp_path / "cap.db"
    result = persist_complete_chain_capture(
        db_path, ticker="TSLA", expiry=_TSLA_EXPIRY, contracts=[],
        spot=350.0, completeness_basis="strike_range=ALL")
    assert result["status"] == "skipped"
    assert result["reason"] == "no_contracts"
    assert latest_complete_chain_capture(db_path, "TSLA", _TSLA_EXPIRY) is None


def test_write_skips_missing_completeness_basis_fail_closed(tmp_path):
    """A row with no stated basis for its completeness claim would be worse than no row —
    a caller trusts what THIS table alone claims."""
    db_path = tmp_path / "cap.db"
    result = persist_complete_chain_capture(
        db_path, ticker="TSLA", expiry=_TSLA_EXPIRY, contracts=_TSLA_CONTRACTS,
        spot=350.0, completeness_basis="")
    assert result["status"] == "skipped"
    assert result["reason"] == "no_completeness_basis"


def test_corrupt_json_row_reads_as_none_not_an_exception(tmp_path):
    db_path = tmp_path / "cap.db"
    persist_complete_chain_capture(
        db_path, ticker="TSLA", expiry=_TSLA_EXPIRY, contracts=_TSLA_CONTRACTS,
        spot=350.0, completeness_basis="strike_range=ALL", ts_utc=1000.0)
    con = sqlite3.connect(str(db_path))
    con.execute("UPDATE complete_chain_captures SET chain_json='{not valid json'")
    con.commit()
    con.close()
    assert latest_complete_chain_capture(db_path, "TSLA", _TSLA_EXPIRY) is None
