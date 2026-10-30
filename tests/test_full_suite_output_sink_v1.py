"""The full-suite command never blocks on the caller's terminal pipe: scripts/run-pytest-full.mjs
(and the Playwright step in scripts/run-playwright-e2e.mjs) give the child file descriptors on a
log file, never the terminal, and echo only a bounded tail. One test drives it with a reader that
never drains and proves the child still completes; the others check, with an ordinary reader,
that the exit code is exact, the log is kept and the terminal output is bounded."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "scripts" / "run-pytest-full.mjs"
NODE = shutil.which("node")

#: Enough child output to overflow any OS pipe buffer (Windows anonymous pipes and Linux
#: pipes are both well under 1 MiB) so a non-draining reader is guaranteed to block a
#: writer that talks to the pipe directly.
_NOISY_LINES = 20_000
_NOISY_LINE = "x" * 100

#: Per-process runtime selectors exported by tests/conftest.py at import; a nested pytest
#: owns its own runtime root and never reads this session's (see _child_env).
_OUTER_SESSION_RUNTIME_SELECTORS = frozenset({"ED_RUNTIME_ROOT", "ED_ARTIFACTS_ROOT"})


def _child_env(log_dir: Path) -> dict[str, str]:
    """Env for the nested run: this suite's own pytest/xdist variables must not leak in,
    and the runner's log goes to a private directory, never the checkout's logs/.

    The runtime selectors tests/conftest.py exports (ED_RUNTIME_ROOT, ED_ARTIFACTS_ROOT)
    are dropped too, for the same reason the conftest states:
    every pytest process owns a fresh runtime root; the nested run must never read or
    write this session's.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("PYTEST_") and k not in _OUTER_SESSION_RUNTIME_SELECTORS
    }
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


def _hermetic_args(rootdir: Path) -> list[str]:
    """Pin pytest's rootdir to the temp directory that holds the target file: otherwise, with
    the target under %TEMP% and cwd at the repo, pytest takes their common ancestor as rootdir
    and walks %TEMP%, where other xdist workers create and delete their runtime roots."""
    return ["--rootdir", str(rootdir)]


def _runner_cmd(*pytest_args: str, rootdir: Path | None = None) -> list[str]:
    assert NODE, "node is required (the canonical runner is a Node script)"
    hermetic = _hermetic_args(rootdir) if rootdir is not None else []
    return [NODE, str(RUNNER), *pytest_args, *hermetic, "-n", "0", "-p", "no:cacheprovider"]


def _spawn_with_non_draining_reader(cmd: list[str], env: dict[str, str]) -> subprocess.Popen:
    """Start `cmd` with stdout+stderr on ONE pipe that nobody ever reads."""
    return subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def test_runner_completes_when_the_terminal_reader_never_drains(tmp_path):
    noisy = _noisy_test_file(tmp_path)
    env = _child_env(tmp_path / "logs")
    proc = _spawn_with_non_draining_reader(_runner_cmd(str(noisy), "-s", rootdir=tmp_path), env)
    try:
        rc = proc.wait(timeout=180)  # completes without the reader ever recovering
    except subprocess.TimeoutExpired:
        for child in psutil.Process(proc.pid).children(recursive=True):  # the pytest it started
            child.kill()
        proc.kill()
        proc.wait(timeout=30)
        raise AssertionError("the canonical runner froze behind a non-draining terminal reader")
    assert rc == 0, f"runner exit code {rc}"
    log = tmp_path / "logs" / "test_pytest_last.log"
    assert log.is_file(), "the full pytest output was not written to the log file"
    text = log.read_text(encoding="utf-8", errors="replace")
    assert "1 passed" in text
    assert text.count(_NOISY_LINE) == _NOISY_LINES, "the child's output was not fully captured"


def test_failure_exit_code_is_exact_and_the_log_is_retained(tmp_path):
    failing = tmp_path / "test_rc535_fails.py"
    failing.write_text(
        "def test_boom():\n    assert 1 == 2, 'deliberate RC-535 failure'\n", encoding="utf-8"
    )
    r = subprocess.run(
        _runner_cmd(str(failing), rootdir=tmp_path),
        cwd=str(ROOT),
        env=_child_env(tmp_path / "logs"),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert r.returncode == 1, f"expected pytest's exit code 1, got {r.returncode}\n{r.stdout}"
    log = (tmp_path / "logs" / "test_pytest_last.log").read_text(encoding="utf-8", errors="replace")
    assert "deliberate RC-535 failure" in log and "1 failed" in log
    # bounded terminal echo: the tail, not the stream — and the failure is visible in it.
    # The bound is BYTES: Windows anonymous pipes hold 4 KiB, and the whole `test:all`
    # footprint (npm banner + E2E step + this step) must fit so a dead reader cannot hold
    # the exit code hostage.
    assert "1 failed" in r.stdout and "exit code 1" in r.stdout
    assert len(r.stdout.encode("utf-8")) <= 2300, (
        f"terminal output is not bounded: {len(r.stdout.encode('utf-8'))} bytes"
    )


def test_success_is_visible_and_exit_code_zero(tmp_path):
    r = subprocess.run(
        _runner_cmd("tests/test_time_et_authority.py"),
        cwd=str(ROOT),
        env=_child_env(tmp_path / "logs"),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert r.returncode == 0, r.stdout
    assert "passed" in r.stdout and "exit code 0" in r.stdout
    assert (tmp_path / "logs" / "test_pytest_last.log").is_file()


def test_forwarded_selection_arguments_reach_the_native_playwright_cli(tmp_path):
    """run-playwright-e2e.mjs spawns Playwright's own CLI with no shell
    (`runWithFileSink(..., shell: false)`), so the caller's selection arguments arrive as sent:
    arguments a shell would change (a space, an embedded double quote, `$(...)` and backtick
    substitution, a Windows `%VAR%`, and `;`, `|`, `&`) reach the child byte for byte, in
    order, each as its own argv entry."""
    marker = tmp_path / "argv_dump.json"
    log_path = tmp_path / "probe.log"
    dangerous_args = [
        "tests/e2e/some.spec.js",
        "-g",
        "shell structure",
        "failed additional-contracts request (RC-UI-3)",
        'a "quoted" name',
        "$(touch PWNED_POSIX)",
        "`touch PWNED_BACKTICK`",
        "%WINDIR%",
        "a;b|c&d",
        "a^b",
    ]
    # The child just dumps the argv it actually received (everything after the `--`
    # separator `node -e` uses to distinguish its own script from forwarded args) to a
    # file -- proving receipt without relying on runWithFileSink's own log-file plumbing.
    child_code = (
        "const fs = require('fs');"
        "fs.writeFileSync(process.env.ARGV_MARKER, JSON.stringify(process.argv.slice(1)));"
    )
    script = (
        "import(" + json.dumps(RUNNER.as_uri()) + ").then(m => {\n"
        "  const code = m.runWithFileSink(\n"
        "    'argv-probe', process.execPath,\n"
        "    ['-e', " + json.dumps(child_code) + ", '--', ..." + json.dumps(dangerous_args) + "],\n"
        "    { logPath: " + json.dumps(str(log_path)) + ", shell: false,\n"
        "      env: { ...process.env, ARGV_MARKER: " + json.dumps(str(marker)) + " } }\n"
        "  );\n"
        "  process.exit(code);\n"
        "});\n"
    )
    r = subprocess.run(
        [NODE, "-e", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert marker.exists(), (
        "child process never ran / never received its ARGV_MARKER env var\n" + r.stdout + r.stderr
    )
    got = json.loads(marker.read_text(encoding="utf-8"))
    assert got == dangerous_args, (
        f"an argument was reinterpreted in transit: got {got!r}, expected {dangerous_args!r}"
    )
    # No POSIX command substitution actually ran (would prove a real shell reparsed
    # `$(touch ...)` / `` `touch ...` `` instead of forwarding it as an inert string).
    assert not (ROOT / "PWNED_POSIX").exists(), (
        "a shell executed $(...) inside a forwarded argument"
    )
    assert not (ROOT / "PWNED_BACKTICK").exists(), (
        "a shell executed a backtick substitution inside a forwarded argument"
    )
