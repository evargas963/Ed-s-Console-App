"""TERRAIN LEDGER firewall — end-to-end proof of BOTH layers (operator-named hole, 2026-08-24).

Layer 1 — PREVENTION (env kill-switch): tests/conftest.py sets ED_TERRAIN_QUARANTINE_LEDGER
before any test module can import server, and server.py reads it at import time — so a lazy
mid-test ``import server`` can never bind the tracked reports/terrain_quarantine_ledger.jsonl
at all, regardless of import order or xdist distribution. (CI caught exactly this class on
2026-08-24: audit_client's lazy import wrote +479 bytes from a worker where nothing had
imported server yet.)

Layer 2 — DETECTION (byte firewall): the autouse ``_terrain_ledger_to_tmp`` fixture
snapshots the tracked file's byte length before every test and, after the test, truncates
any growth back (restore FIRST — the tracked audit file must never stay polluted) and FAILS
the test naming the hole. With Layer 1 in place this backstop guards against EXTERNAL
writers (a spawned tool, a subprocess with a scrubbed env) rather than import order.

Both proofs run a REAL inner pytest against THIS repo's conftest (``-p tests.conftest``,
repo cwd/rootdir), so the mechanisms exercised are the real ones — not copies.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACKED_LEDGER = ROOT / "reports" / "terrain_quarantine_ledger.jsonl"

#: Layer-1 prover: imports server ONLY inside the test body (after fixture setup ran with
#: `server` absent from sys.modules) and earns a permanent quarantine. With the env
#: kill-switch, the append lands in the env-pointed tmp file — the inner test PASSES and
#: asserts so itself.
_LATE_IMPORT_TEST = '''\
import os
from pathlib import Path


def test_mid_test_server_import_cannot_bind_the_tracked_ledger():
    import server                                     # LATE import: after fixture setup

    override = os.environ.get("ED_TERRAIN_QUARANTINE_LEDGER")
    assert override, "conftest must set the ledger kill-switch before any server import"
    assert str(server.TERRAIN_QUARANTINE_LEDGER) == override, (
        f"server bound {server.TERRAIN_QUARANTINE_LEDGER}, not the env override")
    for _ in range(server.TERRAIN_QUARANTINE_HARD_FAILS):
        server._note_terrain_failure(
            "ZZLATEIMPORT", "synthetic hard rejection (isolation prover)", "hard")
    entry = server.terrain_quarantine_state("ZZLATEIMPORT")
    assert entry.get("permanent") is True, entry
    text = Path(override).read_text(encoding="utf-8") if Path(override).exists() else ""
    assert "ZZLATEIMPORT" in text, "the quarantine write did not land in the override file"
'''

def _run_inner(test_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable, "-m", "pytest", str(test_file), "-q",
            "-p", "tests.conftest",          # the REAL repo conftest, not a copy
            "-p", "no:cacheprovider",
            "--rootdir", str(ROOT),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=420,
    )


def test_late_server_import_is_prevented_by_the_env_kill_switch(tmp_path):
    """Layer 1: the late import binds the env override, the write lands in tmp, the
    tracked file never changes, and the inner test PASSES (prevention, not detection)."""
    bytes_before = TRACKED_LEDGER.read_bytes()
    synthetic = tmp_path / "test_zz_late_import_synthetic.py"
    synthetic.write_text(_LATE_IMPORT_TEST, encoding="utf-8")

    inner = _run_inner(synthetic)
    out = (inner.stdout or "") + (inner.stderr or "")

    assert TRACKED_LEDGER.read_bytes() == bytes_before, (
        "the tracked terrain ledger changed — the env kill-switch did not bind:\n" + out)
    assert inner.returncode == 0, (
        "the inner run FAILED — with the kill-switch the late import must be harmless:\n"
        + out)
    assert b"ZZLATEIMPORT" not in TRACKED_LEDGER.read_bytes()


def test_external_writer_is_detected_truncated_back_and_failed(tmp_path):
    """Layer 2: growth on the tracked path from a writer the env override cannot reach
    is truncated back FIRST and the offending test FAILS naming the hole."""
    bytes_before = TRACKED_LEDGER.read_bytes()
    synthetic = tmp_path / "test_zz_external_writer_synthetic.py"
    synthetic.write_text(
        "from pathlib import Path\n\n\n"
        "def test_external_process_appends_to_the_tracked_ledger():\n"
        f"    tracked = Path({str(TRACKED_LEDGER)!r})\n"
        "    with tracked.open('a', encoding='utf-8') as fh:\n"
        "        fh.write('{\"event\": \"zz-external-writer-probe\"}\\n')\n",
        encoding="utf-8")

    inner = _run_inner(synthetic)
    out = (inner.stdout or "") + (inner.stderr or "")

    assert TRACKED_LEDGER.read_bytes() == bytes_before, (
        "the tracked ledger was not restored byte-for-byte:\n" + out)
    assert inner.returncode != 0, (
        "the inner run PASSED — the byte firewall never fired on an external write:\n" + out)
    assert "TERRAIN LEDGER LATE-IMPORT HOLE" in out, (
        "the inner run failed for some other reason than the firewall:\n" + out)
    assert "truncated back" in out, (
        "the firewall's message must name the restore:\n" + out)
    assert b"zz-external-writer-probe" not in TRACKED_LEDGER.read_bytes()
