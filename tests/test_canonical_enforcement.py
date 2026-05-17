"""calibration.canonical_enforcement import fallback visibility."""

from __future__ import annotations

import importlib
import logging


def test_configure_sqlite_connection_import_fallback_warns(monkeypatch, caplog):
    import db
    import calibration.canonical_enforcement as ce

    real = db.configure_sqlite_connection
    monkeypatch.delattr(db, "configure_sqlite_connection", raising=False)
    try:
        with caplog.at_level(logging.WARNING):
            importlib.reload(ce)
        assert any("configure_sqlite_connection" in r.message for r in caplog.records)

        conn = object()
        ce.configure_sqlite_connection(conn)  # no-op stub must not raise
    finally:
        db.configure_sqlite_connection = real
        importlib.reload(ce)
