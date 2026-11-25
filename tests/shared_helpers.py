"""Helpers more than one test file uses, each defined once."""

from __future__ import annotations

import asyncio
import json
import math
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import time_et
from time_et import ET

_FX = Path(__file__).resolve().parent / "fixtures"


async def until(ok: Callable[[], object], seconds: float = 30.0, state=lambda: None):
    """Return `ok()`'s first true value, looked at every 0.02 s; fail after `seconds`.

    The wait on state that announces no event (a thread's count, a row in a file): a poll with a
    time-out, never a bare sleep (Fowler, "Eradicating Non-Determinism in Tests"). The failure
    says `state()`. Where the code announces the moment (a task's end, a queue, an event), a test
    awaits that instead.
    """
    end = time_et.elapsed() + seconds
    while not (seen := ok()):
        assert time_et.elapsed() < end, f"not reached in {seconds} s: {state()}"
        await asyncio.sleep(0.02)
    return seen


class TimerCountingLoop(asyncio.SelectorEventLoop):
    """asyncio's own event loop, counting each timer scheduled on it (call_at); nothing else."""

    timers = 0

    def call_at(self, when, callback, *args, context=None):
        self.timers += 1
        return super().call_at(when, callback, *args, context=context)


def et_ts(s: str) -> float:
    """Return the epoch seconds of the ET wall time `s` (ISO format)."""
    return datetime.fromisoformat(s).replace(tzinfo=ET).timestamp()


def norm_cdf(x: float) -> float:
    """Return the standard normal distribution function at `x`."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def write(repo: Path, name: str, text: str) -> None:
    """Write `text` to the file `name` under `repo`, making its folders."""
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text, encoding="utf-8")


def fixture_json(name: str) -> dict:
    """Return the captured file tests/fixtures/`name`, parsed."""
    return json.loads((_FX / name).read_text(encoding="utf-8"))


def git(cwd: Path, *args: str) -> str:
    """Run git with `args` in `cwd`; return what it printed."""
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def node_json(script: str, cwd: Path, env: dict[str, str]):
    """Run the ES module `script` in node in `cwd` with `env`; return the last line it printed.

    The line is read as JSON. The run must succeed.
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def sent(messages: list[dict], key: str) -> list[dict]:
    """`key`'s messages among the stream's `messages`, in receive order."""
    return [m for m in messages if m["item"]["key"] == key]


def rail_levels(body: dict) -> list[dict]:
    """Every level a Confluence answer serves: each row's tags, then the levels past the rows."""
    tags = [tag for row in body["rows"] for tag in row["tags"]]
    return [*tags, *body["levels_above"], *body["levels_below"]]
