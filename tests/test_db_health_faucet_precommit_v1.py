"""RC-407: ordinary commits/tests stay off the ~34 GB production DB.

Locks the fix: tools/data_faucet_audit.measure_ages must NOT create-on-connect (a read-age
measurement that planted an empty data/ed_console.db is how a 0-byte DB failed db-health and
blocked a commit this session — Cursor #9).
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

