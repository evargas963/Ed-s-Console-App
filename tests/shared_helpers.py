"""Helpers more than one test file uses, each defined once."""

from __future__ import annotations

import asyncio
import json
import math
import subprocess
from datetime import datetime
from pathlib import Path

from time_et import ET

_FX = Path(__file__).resolve().parent / "fixtures"


class TimerCountingLoop(asyncio.SelectorEventLoop):
    """asyncio's own event loop, counting each timer scheduled on it (call_at); nothing else."""

    timers = 0

    def call_at(self, when, callback, *args, context=None):
        self.timers += 1
        return super().call_at(when, callback, *args, context=context)


def et_ts(s: str) -> float:
    """The epoch seconds of the ET wall time `s` (ISO format)."""
    return datetime.fromisoformat(s).replace(tzinfo=ET).timestamp()


def norm_cdf(x: float) -> float:
    """The standard normal distribution function at `x`."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def write(repo: Path, name: str, text: str) -> None:
    """Write `text` to the file `name` under `repo`, making its folders."""
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text, encoding="utf-8")


def fixture_json(name: str) -> dict:
    """The captured file tests/fixtures/`name`, parsed."""
    return json.loads((_FX / name).read_text(encoding="utf-8"))


def git(cwd: Path, *args: str) -> str:
    """Run git with `args` in `cwd`; return what it printed."""
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def sent(messages: list[dict], key: str) -> list[dict]:
    """`key`'s messages among the stream's `messages`, in receive order."""
    return [m for m in messages if m["item"]["key"] == key]
