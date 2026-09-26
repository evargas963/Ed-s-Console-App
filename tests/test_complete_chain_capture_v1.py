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
    nearest_complete_chain_capture,
    persist_complete_chain_capture,
)

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "real_tsla_complete_chain_strike_range_all.json")
    .read_text(encoding="utf-8")
)
_TSLA_CONTRACTS = _FIXTURE["chain"]
_TSLA_EXPIRY = _FIXTURE["expiry"]














def test_write_skips_missing_completeness_basis_fail_closed(tmp_path):
    """A row with no stated basis for its completeness claim would be worse than no row —
    a caller trusts what THIS table alone claims."""
    db_path = tmp_path / "cap.db"
    result = persist_complete_chain_capture(
        db_path, ticker="TSLA", expiry=_TSLA_EXPIRY, contracts=_TSLA_CONTRACTS,
        spot=350.0, completeness_basis="")
    assert result["status"] == "skipped"
    assert result["reason"] == "no_completeness_basis"




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


