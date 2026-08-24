"""TERRAIN LEDGER LATE-IMPORT firewall — end-to-end proof (operator-named hole, 2026-08-24).

tests/conftest.py's autouse ``_terrain_ledger_to_tmp`` redirects
server.TERRAIN_QUARANTINE_LEDGER to tmp — but only when ``server`` is already imported at
fixture SETUP. A test that imports server inside its own body used to write quarantine rows
into the real tracked reports/terrain_quarantine_ledger.jsonl with nothing detecting it.

The hardened fixture snapshots the tracked file's byte length before every test and, after
the test, truncates any growth back (restore first — the tracked file must never stay
polluted) and FAILS the test naming the hole. This file proves that mechanism with a REAL
inner pytest run: a synthetic test (written to tmp) imports server only inside the test
body and drives server._note_terrain_failure to a permanent quarantine (3 hard failures =
TERRAIN_QUARANTINE_HARD_FAILS), which appends to the unpatched tracked ledger. The inner
run must FAIL with the guard's message, and the tracked ledger must be byte-identical
before and after the whole exercise.

The inner run loads THIS repo's tests/conftest.py (via ``-p tests.conftest`` with the repo
as cwd and rootdir), so the fixture exercised is the real one — not a copy.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACKED_LEDGER = ROOT / "reports" / "terrain_quarantine_ledger.jsonl"

#: The synthetic offender. Imports server ONLY inside the test body — after the autouse
#: fixture's setup ran with `server` absent from sys.modules — then earns a permanent
#: quarantine, whose ledger append lands in the real tracked file (the hole).
_SYNTHETIC_TEST = '''\
def test_mid_test_server_import_writes_the_real_ledger():
    import server                                     # LATE import: after fixture setup

    for _ in range(server.TERRAIN_QUARANTINE_HARD_FAILS):
        server._note_terrain_failure(
            "ZZLATEIMPORT", "synthetic hard rejection (isolation prover)", "hard")
    entry = server.terrain_quarantine_state("ZZLATEIMPORT")
    assert entry.get("permanent") is True, entry      # the write that must NOT stick
'''


def test_late_server_import_is_caught_and_the_tracked_ledger_is_restored(tmp_path):
    bytes_before = TRACKED_LEDGER.read_bytes()

    synthetic = tmp_path / "test_zz_late_import_synthetic.py"
    synthetic.write_text(_SYNTHETIC_TEST, encoding="utf-8")

    inner = subprocess.run(
        [
            sys.executable, "-m", "pytest", str(synthetic), "-q",
            "-p", "tests.conftest",          # the REAL repo conftest, not a copy
            "-p", "no:cacheprovider",
            "--rootdir", str(ROOT),
        ],
        cwd=str(ROOT),                       # repo cwd → `tests.conftest` imports from here
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=420,
    )
    out = (inner.stdout or "") + (inner.stderr or "")

    bytes_after = TRACKED_LEDGER.read_bytes()
    assert bytes_after == bytes_before, (
        "the tracked terrain ledger changed across the exercise — the fixture failed to "
        f"restore it (before {len(bytes_before)} bytes, after {len(bytes_after)} bytes)"
    )

    assert inner.returncode != 0, (
        "the inner pytest run PASSED — the late-import guard never fired:\n" + out
    )
    assert "TERRAIN LEDGER LATE-IMPORT HOLE" in out, (
        "the inner run failed for some other reason than the late-import guard:\n" + out
    )
    assert "GREW by" in out and "truncated back" in out, (
        "the guard's message must name the offending growth and the restore:\n" + out
    )
    # The offending row itself must not survive anywhere in the tracked file. (The file
    # still carries pre-hardening ZZTEST*/ZZQ residue from before this firewall existed;
    # cleaning THAT is an operator-reviewed act on a tracked audit file, not a test's.)
    assert b"ZZLATEIMPORT" not in bytes_after
