"""Schwab's chain -> the stored capture -> the console. A capture is found whole or not at all, and
it is stored before the console hears of its chain. MRVL's real chain, every expiry."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

import calibration.complete_chain_capture as cch
import schwab_client as sc
from stream_spine import CaptureWriter
from time_et import ET

_BEGUN = datetime(2026, 9, 30, 15, 31, 57, tzinfo=ET).timestamp()
_MRVL = sc.flatten_chain_contracts(
    json.loads(
        (
            Path(__file__).resolve().parent
            / "fixtures"
            / "real_mrvl_full_chain_vs_strike_window.json"
        ).read_text(encoding="utf-8")
    )["full"]
)


def _chain() -> cch._Chain:
    """Inside a capture window, each contract with the sweep's mark that no quote came back."""
    by_expiry: dict[str, list[dict]] = {}
    for ct in _MRVL:
        by_expiry.setdefault(ct["expirationDate"][:10], []).append({**ct, "greeksTime": None})
    assert len(by_expiry) > 1
    return cch._Chain("MRVL", _BEGUN, dict.fromkeys(by_expiry), by_expiry=by_expiry)


def _sweep(tmp_path, publish) -> cch.ChainSweep:
    sqlite3.connect(tmp_path / "ed_console.db").close()  # the daemon's database exists
    return cch.ChainSweep(
        tmp_path / "ed_console.db",
        ["MRVL"],
        publish,
        clock=lambda: _BEGUN,
        failures=CaptureWriter(tmp_path / "stream_capture.db"),
        streamed=lambda symbol: None,
    )


def _stored(db) -> list:
    return [c for capture in cch.last_capture_per_day(db, "MRVL", 1) for c in capture["contracts"]]


def test_a_capture_the_database_refuses_partway_leaves_nothing_stored(tmp_path):
    """Induced test condition: a trigger refuses MRVL's last expiry, as a locked or full database
    would. The expiries before it are not left standing as the day's capture."""
    db = tmp_path / "ed_console.db"
    sweep = _sweep(tmp_path, lambda _topic, _msg: None)
    chain = _chain()
    conn = sqlite3.connect(db)
    cch.ensure_schema(conn)
    conn.execute(
        "CREATE TRIGGER refuse BEFORE INSERT ON complete_chain_captures "
        f"WHEN NEW.expiry = '{list(chain.by_expiry)[-1]}' "
        "BEGIN SELECT RAISE(ABORT, 'refused'); END"
    )
    conn.commit()
    conn.close()
    with pytest.raises(sqlite3.IntegrityError):
        sweep._write_history(chain)
    assert cch.last_capture_per_day(db, "MRVL", 1) == []
    assert cch.newest_capture_ts(db, "MRVL") is None


def test_the_console_hears_of_a_chain_after_its_capture_is_stored(tmp_path):
    """A read on the chain's arrival finds the capture it belongs to, whole."""
    db = tmp_path / "ed_console.db"
    stored_at_each_message: list = []
    sweep = _sweep(tmp_path, lambda _topic, _msg: stored_at_each_message.append(len(_stored(db))))
    chain = _chain()
    sweep.deliver(chain)
    assert set(stored_at_each_message) == {len(chain.contracts())}
