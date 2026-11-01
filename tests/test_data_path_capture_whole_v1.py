"""Schwab's chain -> the stored capture. A capture is found whole or not at all. MRVL's real chain,
every expiry."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

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


def test_a_capture_the_database_refuses_partway_is_kept_and_leaves_nothing_stored(tmp_path):
    """Induced test condition: a trigger refuses MRVL's last expiry, as a locked or full database
    would, the chain delivered at an instant it was not taken. The expiries before it are not left
    standing as the day's capture, and the chain still reaches the console and the failure log."""
    db = tmp_path / "ed_console.db"
    by_expiry: dict[str, list[dict]] = {}
    for ct in _MRVL:
        by_expiry.setdefault(ct["expirationDate"][:10], []).append({**ct, "greeksTime": None})
    assert len(by_expiry) > 1
    chain = cch._Chain("MRVL", _BEGUN, dict.fromkeys(by_expiry), by_expiry=by_expiry)
    conn = sqlite3.connect(db)
    cch.ensure_schema(conn)
    conn.execute(
        "CREATE TRIGGER refuse BEFORE INSERT ON complete_chain_captures "
        f"WHEN NEW.expiry = '{list(by_expiry)[-1]}' "
        "BEGIN SELECT RAISE(ABORT, 'refused'); END"
    )
    conn.commit()
    conn.close()
    published: list = []
    failures = CaptureWriter(tmp_path / "stream_capture.db")
    sweep = cch.ChainSweep(
        db,
        ["MRVL"],
        lambda topic, _msg: published.append(topic),
        clock=lambda: _BEGUN,
        failures=failures,
        streamed=lambda symbol: None,
    )
    sweep.deliver(chain)
    assert published
    assert cch.last_capture_per_day(db, "MRVL", 1) == []
    assert cch.newest_capture_ts(db, "MRVL") is None
    with sqlite3.connect(tmp_path / "stream_capture.db") as read:
        topics = [r[0] for r in read.execute("SELECT topic FROM stream_write_failures")]
    assert topics == ["chain_history.MRVL"]
