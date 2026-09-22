"""TERRAIN LEDGER firewall — end-to-end proof of BOTH layers (operator-named hole, 2026-08-24).

Layer 1 — PREVENTION (env kill-switch): tests/conftest.py sets ED_TERRAIN_QUARANTINE_LEDGER
before any test module can import server, and server.py reads it at import time — so a lazy
mid-test ``import server`` can never bind the tracked reports/terrain_quarantine_ledger.jsonl
at all, regardless of import order or xdist distribution. (CI caught exactly this class on
2026-08-24: audit_client's lazy import wrote +479 bytes from a worker where nothing had
imported server yet.)

Layer 2 — DETECTION (byte firewall): the autouse ``_terrain_ledger_to_tmp`` fixture
snapshots the watched file's byte length before every test and, after the test, truncates
any growth back (restore FIRST — the tracked audit file must never stay polluted) and FAILS
the test naming the hole. With Layer 1 in place this backstop guards against EXTERNAL
writers (a spawned tool, a subprocess with a scrubbed env) rather than import order.

Both proofs run a REAL inner pytest against THIS repo's conftest (``-p tests.conftest``,
repo cwd/rootdir), so the mechanisms exercised are the real ones — not copies.

ISOLATION (RC-547, 2026-09-10): the inner run watches a PRIVATE COPY of the tracked file
(`ED_TEST_TRACKED_TERRAIN_LEDGER`), and the probe writes to that copy. Under xdist every
worker's fixture polices the same real file, so a probe on the shared path could be healed by
a neighbour before this prover's inner run observed it — a race that made the Layer-2 proof
fail under `-n 8` and pass alone. Nothing here touches the real tracked file any more.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


def _private_copy(tmp_path: Path) -> Path:
    watched = tmp_path / "watched" / "terrain_quarantine_ledger.jsonl"
    watched.parent.mkdir(parents=True)
    shutil.copy(TRACKED_LEDGER, watched)
    return watched


def _run_inner(test_file: Path, watched: Path) -> subprocess.CompletedProcess[str]:
    # RC-REHAB-1 (2026-09-22): --rootdir must be the TARGET FILE's own directory, not the
    # repo root. test_full_suite_output_sink_v1.py's _hermetic_args already proved this
    # exact mechanism (MEASURED 2026-09-08): --rootdir=ROOT with a target file under
    # %TEMP% makes pytest infer a common-ancestor rootdir far above both (often the user's
    # home directory), and its top-level Dir collector then WALKS every directory between
    # that ancestor and the target -- including %TEMP% itself, where concurrent xdist
    # workers are constantly creating/deleting their own ed-pytest-gw*-* runtime roots.
    # That walk is the collection-crash source this file's own _run_inner_with_crash_retry
    # was built around (RC-565/RC-565 follow-up): a sibling worker's directory vanishing
    # mid-listing raises FileNotFoundError during collection, unrelated to either firewall
    # layer. Pinning --rootdir to test_file.parent (tmp_path, where the synthetic test
    # already lives) means collection starts there directly and never walks %TEMP%'s
    # broader structure at all -- fixing the race at its source instead of only retrying
    # around it. cwd stays the repo root (`-p tests.conftest` resolves via sys.path/cwd,
    # not rootdir, so this does not affect which conftest loads).
    return subprocess.run(
        [
            sys.executable, "-m", "pytest", str(test_file), "-q",
            "-p", "tests.conftest",          # the REAL repo conftest, not a copy
            "-p", "no:cacheprovider",
            "--rootdir", str(test_file.parent),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=420,
        env={**os.environ, "ED_TEST_TRACKED_TERRAIN_LEDGER": str(watched)},
    )


def _run_inner_with_crash_retry(
    test_file: Path,
    watched: Path,
    bytes_before: bytes,
    *,
    unless_marker: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], str]:
    """RC-565 follow-up (2026-09-18): under heavy `-n 8` load this inner subprocess's OWN
    pytest collection can crash on unrelated cross-process filesystem noise (MEASURED: a
    FileNotFoundError lstat-ing a temp directory that belongs to a DIFFERENT, unrelated
    xdist worker's PID -- confirmed not a bug in either firewall layer, since it happens
    before collection ever reaches the synthetic test). When that happens the inner run
    never got a chance to exercise the real scenario at all, so retrying is honest: it is
    not hiding a real firewall result, only re-attempting a run that never actually tested
    anything. A genuine firewall result (the real scenario ran, whether it passed or failed
    for its own reason) is never this signature and is never retried. `unless_marker`, when
    given, is a second, stricter guard: a string that can ONLY appear once the real scenario
    ran, so its presence rules out a crash-retry even if the collection-error text also
    happens to appear somewhere in the same output. Shared by both layers below (this test
    and `test_external_writer_is_detected_truncated_back_and_failed`) so the retry
    semantics stay identical rather than drifting between two hand-written copies."""
    out = ""
    inner: subprocess.CompletedProcess[str]
    for attempt in range(3):
        inner = _run_inner(test_file, watched)
        out = (inner.stdout or "") + (inner.stderr or "")
        collection_crashed = (
            inner.returncode != 0
            and (unless_marker is None or unless_marker not in out)
            and "ERROR collecting test session" in out
        )
        if not collection_crashed:
            return inner, out
        assert watched.read_bytes() == bytes_before, (
            f"attempt {attempt + 1}: unrelated collection crash also left the watched "
            "ledger changed -- this is no longer safely retryable:\n" + out)
    pytest.fail(
        "the inner run's OWN pytest collection crashed on unrelated environment noise "
        f"3 times in a row (never reached the real scenario under test):\n{out}")


def test_late_server_import_is_prevented_by_the_env_kill_switch(tmp_path):
    """Layer 1: the late import binds the env override, the write lands in tmp, the
    watched file never changes, and the inner test PASSES (prevention, not detection)."""
    watched = _private_copy(tmp_path)
    bytes_before = watched.read_bytes()
    synthetic = tmp_path / "test_zz_late_import_synthetic.py"
    synthetic.write_text(_LATE_IMPORT_TEST, encoding="utf-8")

    inner, out = _run_inner_with_crash_retry(synthetic, watched, bytes_before)

    assert watched.read_bytes() == bytes_before, (
        "the watched terrain ledger changed — the env kill-switch did not bind:\n" + out)
    assert inner.returncode == 0, (
        "the inner run FAILED — with the kill-switch the late import must be harmless:\n"
        + out)
    assert b"ZZLATEIMPORT" not in watched.read_bytes()


def test_external_writer_is_detected_truncated_back_and_failed(tmp_path):
    """Layer 2: growth on the watched path from a writer the env override cannot reach
    is truncated back FIRST and the offending test FAILS naming the hole."""
    watched = _private_copy(tmp_path)
    bytes_before = watched.read_bytes()
    synthetic = tmp_path / "test_zz_external_writer_synthetic.py"
    synthetic.write_text(
        "from pathlib import Path\n\n\n"
        "def test_external_process_appends_to_the_watched_ledger():\n"
        f"    tracked = Path({str(watched)!r})\n"
        "    with tracked.open('a', encoding='utf-8') as fh:\n"
        "        fh.write('{\"event\": \"zz-external-writer-probe\"}\\n')\n",
        encoding="utf-8")

    inner, out = _run_inner_with_crash_retry(
        synthetic, watched, bytes_before, unless_marker="TERRAIN LEDGER LATE-IMPORT HOLE")

    assert watched.read_bytes() == bytes_before, (
        "the watched ledger was not restored byte-for-byte:\n" + out)
    assert inner.returncode != 0, (
        "the inner run PASSED — the byte firewall never fired on an external write:\n" + out)
    assert "TERRAIN LEDGER LATE-IMPORT HOLE" in out, (
        "the inner run failed for some other reason than the firewall:\n" + out)
    assert "truncated back" in out, (
        "the firewall's message must name the restore:\n" + out)
    assert b"zz-external-writer-probe" not in watched.read_bytes()


def test_the_provers_never_touch_the_real_tracked_file():
    """The race this suite once had: both provers wrote the REAL tracked file that every
    xdist worker polices. Structural: the probe path and the watched path are the same tmp
    copy, and the real path appears only as the copy's source."""
    src = Path(__file__).read_text(encoding="utf-8")
    body = src.split('"""', 2)[-1]
    token = "TRACKED_" + "LEDGER"                     # not a literal, so this line does not count
    uses = [ln.strip() for ln in body.splitlines() if token in ln]
    assert uses == [f"{token} = ROOT / \"reports\" / \"terrain_quarantine_ledger.jsonl\"",
                    f"shutil.copy({token}, watched)"], uses
    assert "ED_TEST_TRACKED_TERRAIN_LEDGER" in (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
