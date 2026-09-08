"""RC-535 — the canonical full-suite command cannot block on the caller's terminal pipe.

MEASURED 2026-09-08: `npm run test:all` ran `python -m pytest -n auto ...` with stdout/stderr
inherited from an agent terminal. When that reader stopped draining, the xdist controller
blocked inside `_pytest/_io/terminalwriter.py:write_raw`, every worker idled in
`xdist/remote.py run_one_test -> get` waiting for its next item, all five processes stayed
alive at ~0 CPU, and the suite sat frozen for 72 minutes at 94% executed while the screen
showed 36%. Reproduced on demand by piping pytest into a reader that never reads.

The repair: scripts/run-pytest-full.mjs (and the Playwright step in
scripts/run-playwright-e2e.mjs) give the child file descriptors on a log file — never the
terminal — and echo only a bounded tail. These tests drive that seam with a reader that
never drains and prove the child still completes, the exit code is exact, the log is
retained, and the terminal output is bounded. The first test carries its own negative
control: the pre-repair path (pytest straight into the same non-draining pipe) must still
freeze, or the control proves nothing.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "scripts" / "run-pytest-full.mjs"
E2E_RUNNER = ROOT / "scripts" / "run-playwright-e2e.mjs"
NODE = shutil.which("node")

#: Enough child output to overflow any OS pipe buffer (Windows anonymous pipes and Linux
#: pipes are both well under 1 MiB) so a non-draining reader is guaranteed to block a
#: writer that talks to the pipe directly.
_NOISY_LINES = 20_000
_NOISY_LINE = "x" * 100

#: The direct-pipe negative control is given this long to prove it is stuck. pytest on the
#: noisy file starts writing within ~3 s; the pipe fills in well under a second after that.
_CONTROL_STALL_SECONDS = 20


def _child_env(log_dir: Path) -> dict[str, str]:
    """Env for the nested run: this suite's own pytest/xdist variables must not leak in,
    and the runner's log goes to a private directory, never the checkout's logs/."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env["ED_TEST_LOG_DIR"] = str(log_dir)
    return env


def _noisy_test_file(tmp_path: Path) -> Path:
    p = tmp_path / "test_rc535_noisy.py"
    p.write_text(
        "import sys\n"
        "def test_noisy():\n"
        f"    for _ in range({_NOISY_LINES}):\n"
        f"        sys.stdout.write({_NOISY_LINE!r} + '\\n')\n",
        encoding="utf-8",
    )
    return p


def _runner_cmd(*pytest_args: str) -> list[str]:
    assert NODE, "node is required (the canonical runner is a Node script)"
    return [NODE, str(RUNNER), *pytest_args, "-n", "0", "-p", "no:cacheprovider"]


def _spawn_with_non_draining_reader(cmd: list[str], env: dict[str, str]) -> subprocess.Popen:
    """Start `cmd` with stdout+stderr on ONE pipe that nobody ever reads."""
    return subprocess.Popen(
        cmd, cwd=str(ROOT), env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def test_runner_completes_when_the_terminal_reader_never_drains(tmp_path):
    noisy = _noisy_test_file(tmp_path)
    env = _child_env(tmp_path / "logs")

    # NEGATIVE CONTROL — the pre-repair canonical path. Same noisy target, same
    # non-draining pipe, output straight from pytest into it: must NOT finish.
    control = _spawn_with_non_draining_reader(
        [sys.executable, "-m", "pytest", str(noisy), "-s", "-n", "0", "-p", "no:cacheprovider", "-q"],
        env,
    )
    try:
        try:
            control.wait(timeout=_CONTROL_STALL_SECONDS)
            raise AssertionError(
                "negative control did not freeze: pytest writing directly into a pipe nobody "
                "reads exited with %r — the control cannot detect the defect" % control.returncode
            )
        except subprocess.TimeoutExpired:
            pass                                   # frozen, as the defect predicts
    finally:
        control.kill()
        control.wait(timeout=30)

    # THE REPAIR — same target, same non-draining pipe, through the canonical runner.
    proc = _spawn_with_non_draining_reader(_runner_cmd(str(noisy), "-s"), env)
    try:
        rc = proc.wait(timeout=180)              # completes without the reader ever recovering
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError("the canonical runner froze behind a non-draining terminal reader")
    assert rc == 0, f"runner exit code {rc}"
    log = tmp_path / "logs" / "test_pytest_last.log"
    assert log.is_file(), "the full pytest output was not written to the log file"
    text = log.read_text(encoding="utf-8", errors="replace")
    assert "1 passed" in text
    assert text.count(_NOISY_LINE) == _NOISY_LINES, "the child's output was not fully captured"


def test_failure_exit_code_is_exact_and_the_log_is_retained(tmp_path):
    failing = tmp_path / "test_rc535_fails.py"
    failing.write_text("def test_boom():\n    assert 1 == 2, 'deliberate RC-535 failure'\n", encoding="utf-8")
    r = subprocess.run(
        _runner_cmd(str(failing)), cwd=str(ROOT), env=_child_env(tmp_path / "logs"),
        capture_output=True, text=True, timeout=180,
    )
    assert r.returncode == 1, f"expected pytest's exit code 1, got {r.returncode}\n{r.stdout}"
    log = (tmp_path / "logs" / "test_pytest_last.log").read_text(encoding="utf-8", errors="replace")
    assert "deliberate RC-535 failure" in log and "1 failed" in log
    # bounded terminal echo: the tail, not the stream — and the failure is visible in it.
    # The bound is BYTES: Windows anonymous pipes hold 4 KiB, and the whole `test:all`
    # footprint (npm banner + E2E step + this step) must fit so a dead reader cannot hold
    # the exit code hostage. MEASURED: a 6 KB tail blocked the runner behind a dead reader.
    assert "1 failed" in r.stdout and "exit code 1" in r.stdout
    assert len(r.stdout.encode("utf-8")) <= 2300, (
        f"terminal output is not bounded: {len(r.stdout.encode('utf-8'))} bytes"
    )


def test_success_is_visible_and_exit_code_zero(tmp_path):
    r = subprocess.run(
        _runner_cmd("tests/test_atomic_io.py"), cwd=str(ROOT), env=_child_env(tmp_path / "logs"),
        capture_output=True, text=True, timeout=180,
    )
    assert r.returncode == 0, r.stdout
    assert "passed" in r.stdout and "exit code 0" in r.stdout
    assert (tmp_path / "logs" / "test_pytest_last.log").is_file()


def test_the_canonical_commands_route_through_the_sink():
    """package.json and the Makefile are the two spellings of the canonical command; neither
    may hand pytest or Playwright the terminal pipe again."""
    scripts = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
    assert scripts["test:all"] == "npm run test:e2e && node scripts/run-pytest-full.mjs"
    assert "python -m pytest" not in scripts["test:all"]
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("test-all:", 1)[1]
    assert "node scripts/run-pytest-full.mjs" in recipe
    assert "\tpython -m pytest" not in recipe

    runner = RUNNER.read_text(encoding="utf-8")
    assert 'stdio: ["ignore", fd, fd]' in runner, "the child must write to file descriptors, not the terminal"
    assert '"-m", "pytest", "-n", "auto", "--dist", "loadfile", "--durations=20"' in runner

    e2e = E2E_RUNNER.read_text(encoding="utf-8")
    assert 'runWithFileSink("test:e2e", "npx", ["playwright", "test"]' in e2e
    assert 'stdio: "inherit"' not in e2e.split("ensurePlaywrightReady();", 1)[1], (
        "the Playwright run itself must not inherit the terminal pipe"
    )
