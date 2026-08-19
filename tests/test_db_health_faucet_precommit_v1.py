"""RC-407: ordinary commits/tests stay off the ~34 GB production DB.

Locks the two fixes:
  1. tools/data_faucet_audit.measure_ages must NOT create-on-connect (a read-age measurement
     that planted an empty data/ed_console.db is how a 0-byte DB failed db-health and blocked a
     commit this session — Cursor #9).
  2. tools/check_db_health.py --precommit is change-aware: it classifies DB/schema/Collect files
     and skips (exit 0) when none are staged, so a docs/code commit never opens the DB (Cursor #7).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_TOOLS = str(ROOT / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)


def test_measure_ages_does_not_create_the_db_at_an_absent_path():
    from data_faucet_audit import measure_ages

    d = tempfile.mkdtemp()
    p = os.path.join(d, "ed_console.db")
    assert not os.path.exists(p)
    ages = measure_ages(p)
    assert not os.path.exists(p), "RC-407: measure_ages create-on-connected an empty DB"
    assert all(v is None for v in ages.values())


def test_db_health_precommit_regex_classifies_db_relevant_vs_unrelated():
    from check_db_health import _DB_RELEVANT_RE as r

    for db_file in (
        "db.py", "db_authority.py", "desk_store.py", "base_money_path_capture.py",
        "calibration/repair_canonical_1m_shared.py", "some/schema_migration.py",
    ):
        assert r.search(db_file), f"{db_file} must be DB-relevant (db-health should run)"
    for other in (
        "server.py", "README.md", "static/chart.html", "tools/precommit_institutional.py",
        "governance/root_cause_log.md", ".github/workflows/pytest.yml",
    ):
        assert not r.search(other), f"{other} must NOT be DB-relevant (db-health should skip)"


def test_db_health_precommit_skips_when_no_db_file_staged(monkeypatch):
    import check_db_health as m

    monkeypatch.setattr(m, "_staged_db_relevant_files", lambda: [])
    assert m.main(["--precommit"]) == 0  # skipped fast, no DB opened
