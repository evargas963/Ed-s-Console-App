"""repair_canonical_1m_bars_for_outcomes fail-closed outcome refresh contract."""

from __future__ import annotations

import importlib

import pytest


def test_missing_eddb_fails_loudly_at_import_not_silently_at_runtime(monkeypatch):
    """RC-REHAB-1 (2026-09-23): the module used to wrap `from db import EdDB,
    configure_sqlite_connection` in try/except ImportError, then run degraded with EdDB=None
    and a no-op configure_sqlite_connection (so connections silently skipped WAL / busy_timeout),
    rolling back inserts at runtime. That was one of 16 identical silent no-op fallbacks found
    when the sqlite_wal_contract gate went repo-wide. The import is now direct: a missing EdDB
    is an ImportError the operator sees, not a degraded run that looks like it worked."""
    import db
    import calibration.repair_canonical_1m_bars_for_outcomes as rep

    real_edb = db.EdDB
    monkeypatch.delattr(db, "EdDB", raising=False)
    try:
        with pytest.raises(ImportError):
            importlib.reload(rep)
    finally:
        db.EdDB = real_edb
        importlib.reload(rep)
