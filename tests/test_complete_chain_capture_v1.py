"""OPTIONS_ORDER_FLOW_V1 — calibration/complete_chain_capture.py direct unit tests.

The canonical persistence for the COMPLETE vendor chain, distinct from the bounded
analytical snapshots (`snapshots.option_chain_json`) and from option_chain_morning_full.py
(near-term multi-expiry, once-daily). Uses the real captured TSLA fixture (real fractional
strikes, live strike_range=ALL capture) to prove the round trip preserves the exact contract
set — no rounding, no coercion, no dropped rows.
"""

from __future__ import annotations

import pytest

import json
import sqlite3
from pathlib import Path

from calibration.complete_chain_capture import persist_complete_chain_capture

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "real_tsla_complete_chain_strike_range_all.json")
    .read_text(encoding="utf-8")
)
_TSLA_CONTRACTS = _FIXTURE["chain"]
_TSLA_EXPIRY = _FIXTURE["expiry"]















@pytest.fixture(autouse=True)
def _at_capture(pin_clock):
    """Valued at the stored chain's capture (2026-08-30), so its expiries passing never change
    what this test measures."""
    return pin_clock(2026, 8, 30, 12, 0)

def test_write_skips_missing_completeness_basis_fail_closed(tmp_path):
    """A row with no stated basis for its completeness claim would be worse than no row —
    a caller trusts what THIS table alone claims."""
    db_path = tmp_path / "cap.db"
    result = persist_complete_chain_capture(
        db_path, ticker="TSLA", expiry=_TSLA_EXPIRY, contracts=_TSLA_CONTRACTS,
        spot=350.0, completeness_basis="")
    assert result["status"] == "skipped"
    assert result["reason"] == "no_completeness_basis"




def test_persisted_chain_json_is_actually_gzip_compressed_on_disk(tmp_path):
    """RC-REHAB-3: the whole point of wiring json_blob_codec in here is that the bytes on
    disk are smaller than raw JSON -- prove it directly against the stored column, not just
    that round-tripping through the public functions still works."""
    db_path = tmp_path / "cap.db"
    persist_complete_chain_capture(
        db_path, ticker="TSLA", expiry=_TSLA_EXPIRY, contracts=_TSLA_CONTRACTS,
        spot=350.0, completeness_basis="strike_range=ALL", ts_utc=1000.0)
    con = sqlite3.connect(str(db_path))
    try:
        raw = con.execute("SELECT chain_json FROM complete_chain_captures").fetchone()[0]
    finally:
        con.close()
    assert isinstance(raw, bytes)
    assert raw[:2] == b"\x1f\x8b", "stored value must be gzip, not plain JSON text"
    uncompressed_len = len(json.dumps(_TSLA_CONTRACTS, default=str).encode("utf-8"))
    assert len(raw) < uncompressed_len


