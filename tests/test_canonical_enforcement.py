"""calibration.canonical_enforcement: configure_sqlite_connection is imported directly."""

from __future__ import annotations

import importlib

import pytest


def test_missing_configure_sqlite_connection_fails_loudly_at_import(monkeypatch):
    """RC-REHAB-1 (2026-09-23): this module used to catch the ImportError and install a no-op
    configure_sqlite_connection, so every connection it opened silently skipped WAL /
    busy_timeout while the run looked healthy -- one of 16 identical silent fallbacks found
    when the sqlite_wal_contract gate went repo-wide. The import is now direct from
    db_sqlite_utils (the one definition): a missing helper is an ImportError, not a degraded
    connection."""
    import db_sqlite_utils
    import calibration.canonical_enforcement as ce

    real = db_sqlite_utils.configure_sqlite_connection
    monkeypatch.delattr(db_sqlite_utils, "configure_sqlite_connection", raising=False)
    try:
        with pytest.raises(ImportError):
            importlib.reload(ce)
    finally:
        db_sqlite_utils.configure_sqlite_connection = real
        importlib.reload(ce)
