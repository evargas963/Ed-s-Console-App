"""One expiry stored for a test, through the daemon's own transaction."""

from __future__ import annotations

from calibration.complete_chain_capture import capture_transaction, persist_complete_chain_capture
from stream_spine import CaptureWriter


def store_capture(db, **row) -> dict:
    CaptureWriter(db)  # the database as the Recorder makes it at its start: its folder and tables
    with capture_transaction(db) as conn:
        return persist_complete_chain_capture(conn, **row)
