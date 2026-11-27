"""One expiry stored for a test, on the Recorder's own connection, in one transaction."""

from __future__ import annotations

from contextlib import closing

from stream_spine import CaptureWriter, Persisted, persist_complete_chain_capture


def store_capture(db, **row) -> Persisted:
    writer = CaptureWriter(db)  # the database as the Recorder makes it at its start
    with closing(writer._open()) as conn, conn:  # commits, or rolls back on an error
        return persist_complete_chain_capture(conn, **row)
