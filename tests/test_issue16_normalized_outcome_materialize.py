"""Issue 16 — snapshots_1m_normalized must carry outcome_15c/outcome_60c after materialize."""
from __future__ import annotations

from pathlib import Path

import pytest

from db import (
    EdDB,
)



@pytest.fixture
def tmp_db(tmp_path: Path) -> EdDB:
    return EdDB(tmp_path / "t16.db")


def test_normalized_table_has_horizon_schema_column(tmp_db: EdDB):
    with tmp_db._connect() as conn:
        names = {r[1] for r in conn.execute("PRAGMA table_info(snapshots_1m_normalized)").fetchall()}
    assert "horizon_outcome_schema_version" in names
    assert "outcome_15c" in names
    assert "outcome_60c" in names


# ── Incremental live materialize (console usability slice, 2026-07-03) ───────
# The live base path must not re-read the multi-GB snapshots history and rewrite
# every trio row each cycle (5-22s write-lock holds = the DB DEGRADED incident).
