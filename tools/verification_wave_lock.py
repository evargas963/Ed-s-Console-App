"""RC-565: refuse a second concurrent HEAVY verification wave on this machine.

Successor to the prior `claude/institutional-e2e-enforcement` branch's concurrency-admission
work, which was retired unmerged (its lease/admission mechanism never landed on main, and its
own ticket rows exist only on that branch, not in this repo's governance/root_cause_log.md --
citing them here would be a pointer that resolves to nothing). See this repo's OWN RC-565 row
in governance/root_cause_log.md for the full, verified history: the original incident (a
rerun launched beside an already-running 8-worker pytest-full wave, producing 43 minutes of
blind waiting on buffered output and fifteen state-bound failures from concurrent worktree
mutation) and the operator's 2026-09-18 decision to pick this specific gap back up as fresh
work. This machine runs a dozen-plus linked worktrees against the SAME repository, so two
independent full-suite runs starting at once is a normal, repeatable operating pattern here,
not an edge case.

This is a NEW build against the current seams, not a port: the old branch's lease code hooked
into launch/admission seams (`admit_heavy_launch`, `evidence_identity_hash`) that no longer
exist on main (RC-522/523 replaced the delegation/runtime-root machinery it hung off of).

Design, deliberately simpler than the retired psutil-based classifier:
  - A single machine-wide lock file under the OS temp directory (shared across every worktree
    checkout on this machine/user, unlike each worktree's own private ED_RUNTIME_ROOT).
  - `filelock.FileLock` (already a repo dependency -- tests/conftest.py's repo_index/
    live_orphans caches use it) instead of a hand-rolled PID+psutil liveness check: an
    OS-level file lock is held only while the owning process is alive, and is released by the
    OS automatically if that process dies without cleanup -- exactly the "stale lease" case
    the old design needed psutil to detect manually.
  - Only a HEAVY wave (many xdist workers) takes the lock; a normal single-file or
    few-worker run (the overwhelming majority of runs during iterative development) never
    touches this mechanism at all.
  - Fail CLOSED by default (refuse the second wave with a loud, specific message) because the
    original incident was silent corruption, not a merely annoying warning that scrolls past
    in 8-way output. `ED_ALLOW_CONCURRENT_VERIFICATION_WAVES=1` is the documented override for
    an operator who is deliberately running two waves at once and accepts the risk.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

HEAVY_WORKER_THRESHOLD = 4

# ISOLATION (matches tests/test_terrain_ledger_isolation_v1.py's ED_TEST_TRACKED_TERRAIN_LEDGER
# pattern): this file's own isolation prover spawns REAL nested heavy waves and must not
# collide with the actual outer suite's own held lock if this test file happens to run inside
# a genuine `-n 8` invocation. Injectable, defaults to the real machine-wide path.
_WAVE_DIR = Path(os.environ.get("ED_TEST_VERIFICATION_WAVE_DIR") or tempfile.gettempdir())
WAVE_LOCK_PATH = _WAVE_DIR / "ed_console_verification_wave.lock"
WAVE_INFO_PATH = _WAVE_DIR / "ed_console_verification_wave.info.json"

_OVERRIDE_ENV = "ED_ALLOW_CONCURRENT_VERIFICATION_WAVES"


def override_requested() -> bool:
    return os.environ.get(_OVERRIDE_ENV, "").strip().lower() in ("1", "true", "yes")


def is_heavy_wave(numprocesses: object) -> bool:
    """`numprocesses` is pytest-xdist's own config.option.numprocesses value: None (no -n),
    an int (-n 4), or "auto"/"logical" (-n auto, sized to CPU count -- always treated heavy,
    since every host this runs on has more than HEAVY_WORKER_THRESHOLD logical cores)."""
    if numprocesses is None:
        return False
    if isinstance(numprocesses, str):
        return numprocesses.strip().lower() in ("auto", "logical")
    try:
        return int(numprocesses) >= HEAVY_WORKER_THRESHOLD
    except (TypeError, ValueError):
        return False


def _read_holder_info() -> Optional[dict]:
    try:
        return json.loads(WAVE_INFO_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def refusal_message(rootdir: str) -> str:
    holder = _read_holder_info()
    held_by = (
        f"pid {holder.get('pid')} in {holder.get('rootdir')}, started {holder.get('started_at')}"
        if holder else "another process (its info file was not readable)"
    )
    return (
        "VERIFICATION WAVE COLLISION (RC-565): a heavy (>= "
        f"{HEAVY_WORKER_THRESHOLD}-worker) pytest run is already in progress on this "
        f"machine -- held by {held_by}. Starting a second one here in {rootdir} is the exact "
        "incident this row's own history (governance/root_cause_log.md, RC-565) measured: "
        "43 minutes of blind waiting plus fifteen false failures from concurrent worktree "
        "mutation. Wait for the other run to finish, or set "
        f"{_OVERRIDE_ENV}=1 if you are deliberately running two waves at once and accept the "
        "risk of cross-run interference."
    )


class WaveLock:
    """Thin wrapper so conftest.py can hold one FileLock instance across the session
    without importing filelock at module scope (kept optional/lazy, matching the repo's
    existing repo_index/live_orphans fixtures)."""

    def __init__(self) -> None:
        self._lock = None

    def try_acquire(self) -> bool:
        from filelock import FileLock, Timeout

        lock = FileLock(str(WAVE_LOCK_PATH), timeout=0.1)
        try:
            lock.acquire()
        except Timeout:
            return False
        self._lock = lock
        WAVE_INFO_PATH.write_text(
            json.dumps({
                "pid": os.getpid(),
                "rootdir": os.getcwd(),
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }),
            encoding="utf-8",
        )
        return True

    def release(self) -> None:
        if self._lock is not None:
            try:
                WAVE_INFO_PATH.unlink(missing_ok=True)
            finally:
                self._lock.release()
                self._lock = None
