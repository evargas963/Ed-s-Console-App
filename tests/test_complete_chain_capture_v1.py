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

import calibration.complete_chain_capture as ccc
from calibration.complete_chain_capture import (
    latest_complete_chain_capture,
    nearest_complete_chain_capture,
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


def test_nearest_memoizes_within_the_ttl_so_repeated_calls_never_touch_the_db(monkeypatch, tmp_path):
    """MEASURED live via py-spy (2026-09-14, spot/gamma-360-audit): the streamed-greeks hook
    calls this once PER CANDIDATE CONTRACT on every tick with zero caching -- opening a fresh
    sqlite3 connection and json.loads()-ing the whole chain every single time, for data that
    only changes when a NEW complete capture lands. The memo must make every call after the
    first, for the same (db_path, ticker, cutoff), a pure cache hit -- zero DB opens."""
    ccc._nearest_capture_memo.clear()
    db_path = tmp_path / "cap.db"
    persist_complete_chain_capture(
        db_path, ticker="TSLA", expiry=_TSLA_EXPIRY, contracts=_TSLA_CONTRACTS,
        spot=350.0, completeness_basis="strike_range=ALL", ts_utc=1000.0)

    calls = {"n": 0}
    real_connect = sqlite3.connect

    def _counting_connect(*a, **k):
        calls["n"] += 1
        return real_connect(*a, **k)

    monkeypatch.setattr(sqlite3, "connect", _counting_connect)
    try:
        first = nearest_complete_chain_capture(db_path, "TSLA", on_or_after_expiry="2000-01-01")
        second = nearest_complete_chain_capture(db_path, "TSLA", on_or_after_expiry="2000-01-01")
        third = nearest_complete_chain_capture(db_path, "TSLA", on_or_after_expiry="2000-01-01")
    finally:
        ccc._nearest_capture_memo.clear()
    assert first is not None and second is not None and third is not None
    assert first == second == third
    assert calls["n"] == 1, f"expected exactly ONE real DB open across 3 calls, got {calls['n']}"


def test_nearest_memo_self_heals_after_the_ttl_expires(monkeypatch, tmp_path):
    """The memo must not wedge a stale answer forever -- once the TTL window elapses, the
    next call re-reads the DB (picking up a NEW complete capture that landed meanwhile)."""
    ccc._nearest_capture_memo.clear()
    db_path = tmp_path / "cap.db"
    persist_complete_chain_capture(
        db_path, ticker="TSLA", expiry=_TSLA_EXPIRY, contracts=_TSLA_CONTRACTS,
        spot=350.0, completeness_basis="strike_range=ALL", ts_utc=1000.0)

    fake_now = [1_000_000.0]
    monkeypatch.setattr(ccc.time, "monotonic", lambda: fake_now[0])
    try:
        first = nearest_complete_chain_capture(db_path, "TSLA", on_or_after_expiry="2000-01-01")
        fake_now[0] += ccc._NEAREST_CAPTURE_MEMO_TTL_SEC + 1.0
        real_connect = sqlite3.connect
        calls = {"n": 0}

        def _counting_connect(*a, **k):
            calls["n"] += 1
            return real_connect(*a, **k)

        monkeypatch.setattr(sqlite3, "connect", _counting_connect)
        second = nearest_complete_chain_capture(db_path, "TSLA", on_or_after_expiry="2000-01-01")
    finally:
        ccc._nearest_capture_memo.clear()
    assert first is not None and second is not None
    assert calls["n"] == 1, "expected the DB to be re-read once the TTL window elapsed"


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


def test_a_pre_migration_plain_json_row_still_reads_back_correctly(tmp_path):
    """A row written before this codec existed is plain JSON TEXT, not gzip. Both
    latest_complete_chain_capture and nearest_complete_chain_capture must keep reading it
    correctly with no backfill required -- this is the whole transition-safety guarantee
    the codec is built around, proven here at the real table-function level, not just
    inside json_blob_codec's own unit tests."""
    db_path = tmp_path / "cap.db"
    con = sqlite3.connect(str(db_path))
    try:
        ccc.ensure_schema(con)
        con.execute(
            "INSERT INTO complete_chain_captures "
            "(ticker, expiry, ts_utc, spot, n_contracts, completeness_basis, chain_json, source) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("TSLA", _TSLA_EXPIRY, 1000.0, 350.0, len(_TSLA_CONTRACTS), "strike_range=ALL",
             json.dumps(_TSLA_CONTRACTS, default=str), "legacy_pre_compression"),
        )
        con.commit()
    finally:
        con.close()

    latest = latest_complete_chain_capture(db_path, "TSLA", _TSLA_EXPIRY)
    assert latest is not None
    assert latest["contracts"] == _TSLA_CONTRACTS

    nearest = nearest_complete_chain_capture(db_path, "TSLA", on_or_after_expiry="2000-01-01")
    ccc._nearest_capture_memo.clear()
    assert nearest is not None
    assert nearest["contracts"] == _TSLA_CONTRACTS
