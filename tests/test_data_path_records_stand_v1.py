"""docs/DATA_FLOW.md §3.4 (chains): a stored chain capture is never replaced.

The chain history through the real code: the daemon's ChainSweep fetches Schwab's chain (the
captured SPY 2026-11-20 chain and its quotes, tests/fixtures/real_spy_2026_11_20_chain_and_quotes.json)
and writes it in a capture window; the console's startup reader (last_capture_per_day) reads it
back. STAND-INS: the host answering the sweep is the local stand-in for Schwab's
(test_data_path_rules_v1._LocalSchwab), and the chain envelope it serves is rebuilt from the
captured contracts (_spy_chain_payload), not the envelope as Schwab sent it.
"""
from __future__ import annotations

import sqlite3

import httpx
from schwab.client import Client

from calibration.complete_chain_capture import (CAPTURE_BASIS, ChainSweep, last_capture_per_day,
                                                persist_complete_chain_capture)
from tests.test_data_path_rules_v1 import _LocalSchwab

_IN_WINDOW = 1790863205.0          # 2026-10-01 10:00:05 ET, inside the 10:00 capture window


def test_a_stored_chain_capture_is_never_overwritten_by_a_second_write_of_its_key(tmp_path):
    """INSERT OR REPLACE replaced a stored capture whose (ticker, expiry, ts_utc) a second write
    repeated. STAND-IN: the second write (one contract of the same chain, with the stored
    capture's spot, on the same key) is a later write landing on that key."""
    db = tmp_path / "ed_console.db"
    schwab = _LocalSchwab()
    sweep = ChainSweep(db, ["SPY"], lambda topic, msg: None, clock=lambda: _IN_WINDOW)
    client = Client("k", httpx.Client(transport=schwab.transport), enforce_enums=False)
    try:
        assert sweep.fetch_one(client, "SPY") is True
    finally:
        schwab.close()
    (stored,) = last_capture_per_day(db, "SPY", 1)
    assert stored["ts_utc"] == _IN_WINDOW and stored["contracts"]
    expiry = stored["contracts"][0]["expirationDate"][:10]

    refused = None
    try:
        persist_complete_chain_capture(db, ticker="SPY", expiry=expiry,
                                       contracts=stored["contracts"][:1], spot=stored["spot"],
                                       completeness_basis=CAPTURE_BASIS, ts_utc=_IN_WINDOW)
    except sqlite3.IntegrityError as e:
        refused = e

    (after,) = last_capture_per_day(db, "SPY", 1)
    assert after == stored, "the capture Schwab sent was overwritten"
    assert isinstance(refused, sqlite3.IntegrityError), "the second write was not refused"
