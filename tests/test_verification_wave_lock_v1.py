"""RC-565: a second concurrent HEAVY verification wave on this machine must be refused, not
silently allowed to corrupt a sibling worktree's run the way this row's own history measured
(43 minutes of blind waiting + fifteen state-bound failures). A LIGHT run (no -n, or a small
-n) must never be gated at all -- that is the overwhelming majority of runs during iterative
development.

ISOLATION: every subprocess spawned here is pinned to a PRIVATE, per-test wave directory via
ED_TEST_VERIFICATION_WAVE_DIR (tools/verification_wave_lock.py's own injection point) --
matching tests/test_terrain_ledger_isolation_v1.py's ED_TEST_TRACKED_TERRAIN_LEDGER pattern.
Without this, this file running INSIDE a genuine `-n 8` outer suite would collide with the
outer run's own real, machine-wide lock and hang or false-fail on its own test infrastructure.

These are real subprocess mutation controls (matching the discipline already established by
tests/test_terrain_ledger_isolation_v1.py): a plugin hook is not proven by unit-testing its
pure helper functions in isolation, only by two real overlapping pytest invocations.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.verification_wave_lock import HEAVY_WORKER_THRESHOLD, is_heavy_wave, override_requested

ROOT = Path(__file__).resolve().parent.parent
_LIGHT_TARGET = "tests/test_verification_wave_lock_v1.py::test_is_heavy_wave_classification"


def test_is_heavy_wave_classification():
    assert is_heavy_wave(None) is False
    assert is_heavy_wave(1) is False
    assert is_heavy_wave(HEAVY_WORKER_THRESHOLD - 1) is False
    assert is_heavy_wave(HEAVY_WORKER_THRESHOLD) is True
    assert is_heavy_wave(HEAVY_WORKER_THRESHOLD + 4) is True
    assert is_heavy_wave("auto") is True
    assert is_heavy_wave("logical") is True
    assert is_heavy_wave("not-a-number") is False


def test_override_requested_reads_the_documented_env_var(monkeypatch):
    monkeypatch.delenv("ED_ALLOW_CONCURRENT_VERIFICATION_WAVES", raising=False)
    assert override_requested() is False
    monkeypatch.setenv("ED_ALLOW_CONCURRENT_VERIFICATION_WAVES", "1")
    assert override_requested() is True
    monkeypatch.setenv("ED_ALLOW_CONCURRENT_VERIFICATION_WAVES", "0")
    assert override_requested() is False


def _spawn_heavy(wave_dir: Path, extra_env: dict | None = None) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "pytest", _LIGHT_TARGET, "-n", "8", "-q",
         "-p", "no:cacheprovider"],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        env={**os.environ, "ED_TEST_VERIFICATION_WAVE_DIR": str(wave_dir), **(extra_env or {})},
    )


def _run(wave_dir: Path, args: list[str], extra_env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args, "-p", "no:cacheprovider"],
        cwd=str(ROOT), capture_output=True, text=True,
        # RC-REHAB-1 (2026-09-22): this spawns its OWN 8-worker pytest run, nested inside
        # an outer suite that is itself already `-n 8` -- 16+ concurrent workers competing
        # for CPU is genuinely slower to get scheduled than a quiet machine, and 60s was a
        # tight margin (MEASURED: test_the_override_env_var_lets_a_second_wave_through
        # failed once under full-suite load, passed cleanly on every other run including a
        # second full-suite run immediately after -- consistent with a timing margin issue,
        # not a logic defect in the override path itself).
        timeout=150,
        env={**os.environ, "ED_TEST_VERIFICATION_WAVE_DIR": str(wave_dir), **(extra_env or {})},
    )


def _wait_for_heavy_to_start(proc: subprocess.Popen, wave_dir: Path, timeout: float = 60.0) -> None:
    """Poll until the (isolated) wave lock's info file exists, rather than a fixed sleep --
    avoids a flaky race on a loaded machine."""
    info_path = wave_dir / "ed_console_verification_wave.info.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if info_path.is_file():
            return
        if proc.poll() is not None:
            pytest.fail(f"heavy wave exited before acquiring the lock:\n{proc.stdout.read()}")
        time.sleep(0.1)
    pytest.fail("heavy wave never acquired the lock within the timeout")


def test_a_second_heavy_wave_is_refused_while_the_first_runs(tmp_path):
    wave_dir = tmp_path / "wave"
    wave_dir.mkdir()
    first = _spawn_heavy(wave_dir)
    try:
        _wait_for_heavy_to_start(first, wave_dir)
        second = _run(wave_dir, [_LIGHT_TARGET, "-n", "8", "-q"])
        out = second.stdout + second.stderr
        assert second.returncode == 2, f"the second wave was not refused:\n{out}"
        assert "VERIFICATION WAVE COLLISION" in out, out
        # 2026-09-21: was "RC-517" -- that citation pointed at a never-merged sibling
        # branch's own ticket rows (fixed as a phantom-pointer defect this session); the
        # refusal message now points at this repo's own RC-565 row, which carries the
        # full incident history in governance/root_cause_log.md.
        assert "RC-565" in out, out
    finally:
        # RC-REHAB-1 (2026-09-22): matches _run's timeout increase -- this "first" process is
        # itself an 8-worker pytest run, nested inside an already-heavy outer suite.
        first.wait(timeout=150)
    assert first.returncode == 0, first.stdout.read() if first.stdout else ""  # caps-ok: assertion-message text only: prints captured stdout when a pipe exists


def test_the_override_env_var_lets_a_second_wave_through(tmp_path):
    wave_dir = tmp_path / "wave"
    wave_dir.mkdir()
    first = _spawn_heavy(wave_dir)
    try:
        _wait_for_heavy_to_start(first, wave_dir)
        second = _run(wave_dir, [_LIGHT_TARGET, "-n", "8", "-q"],
                      extra_env={"ED_ALLOW_CONCURRENT_VERIFICATION_WAVES": "1"})
        assert second.returncode == 0, second.stdout + second.stderr
    finally:
        # RC-REHAB-1 (2026-09-22): matches _run's timeout increase -- this "first" process is
        # itself an 8-worker pytest run, nested inside an already-heavy outer suite.
        first.wait(timeout=150)


def test_a_light_run_is_never_gated_even_beside_a_live_heavy_wave(tmp_path):
    wave_dir = tmp_path / "wave"
    wave_dir.mkdir()
    first = _spawn_heavy(wave_dir)
    try:
        _wait_for_heavy_to_start(first, wave_dir)
        light = _run(wave_dir, [_LIGHT_TARGET, "-q"])
        assert light.returncode == 0, light.stdout + light.stderr
        assert "VERIFICATION WAVE COLLISION" not in (light.stdout + light.stderr)
    finally:
        # RC-REHAB-1 (2026-09-22): matches _run's timeout increase -- this "first" process is
        # itself an 8-worker pytest run, nested inside an already-heavy outer suite.
        first.wait(timeout=150)


def test_the_lock_releases_so_a_later_heavy_wave_can_proceed(tmp_path):
    wave_dir = tmp_path / "wave"
    wave_dir.mkdir()
    first = _spawn_heavy(wave_dir)
    # RC-REHAB-1 (2026-09-22): matches _run's timeout increase -- this "first" process is
    # itself an 8-worker pytest run, nested inside an already-heavy outer suite.
    first.wait(timeout=150)
    assert first.returncode == 0

    second = _run(wave_dir, [_LIGHT_TARGET, "-n", "8", "-q"])
    assert second.returncode == 0, second.stdout + second.stderr
