"""One expiry stored for a test, through the daemon's own transaction."""

from __future__ import annotations

from calibration.complete_chain_capture import capture_transaction, persist_complete_chain_capture


def store_capture(db, **row) -> dict:
    with capture_transaction(db) as conn:
        return persist_complete_chain_capture(conn, **row)
