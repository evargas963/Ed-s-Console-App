"""One clock, repo wide.

Operator 2026-11-05: "fix the fucking clock ... REPO WIDE NO EXCEPTIONS". The computer's clock
is read in time_et.py alone (time_et.now, time_et.elapsed); every other file takes the time from
it, and the page reads no clock at all (its time of day is the program's, from the daemon's
heartbeat). The clock's readers are banned names in locks.ruff.toml, the base's rules
tools/check_locks.py counts per product file with every `noqa` ignored: time_et.py's count is the
one above 0, so no other file may start.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tools import check_locks

pytestmark = pytest.mark.rail

REPO = Path(__file__).resolve().parent.parent
#: a clock read in page code
PAGE_CLOCK = re.compile(r"Date\.now\(|new Date\(\s*\)|performance\.now\(")
#: what ruff says of a read of the computer's clock under the locks' rules
CLOCK = re.compile(r"One clock: |No clock time is typed")


def _clock_reads(*args: str, source: str | None = None) -> list[str]:
    """The file of each clock read ruff finds under the locks' rules, every `noqa` ignored."""
    done = subprocess.run(
        [
            *(sys.executable, "-P", "-m", "ruff", "check", "--config", check_locks.RULES),
            *("--ignore-noqa", "--select", "TID251", "--output-format", "json", "--no-cache"),
            *args,
        ],
        input=source,
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    return [f["filename"] for f in json.loads(done.stdout) if CLOCK.search(f["message"])]


@pytest.mark.parametrize(
    "line",
    [
        "import time\nT = time.time()\n",
        "import time\nT = time.time()  # noqa: TID251\n",
        "import time\nT = time.monotonic()\n",
        "import time\nT = time.perf_counter()\n",
        "from datetime import datetime\nT = datetime.now()\n",
        "from datetime import date\nT = date.today()\n",
        "from datetime import time\nT = time(9, 30)\n",
    ],
)
def test_a_clock_read_outside_time_et_is_refused_in_any_file(line):
    for name in ("server.py", "tests/test_x.py", "tools/x.py", "app/x.py"):
        assert len(_clock_reads("--stdin-filename", name, "-", source=line)) == 1, (name, line)


def test_time_et_is_the_one_producer_of_the_time(tracked_files):
    python = [p for p in tracked_files if p.endswith(check_locks.PYTHON)]
    readers = {
        Path(f).resolve().relative_to(REPO).as_posix()
        for start in range(0, len(python), 200)  # a command line under Windows' limit
        for f in _clock_reads("--", *python[start : start + 200])
    }
    assert readers == {"time_et.py"}


def test_the_page_reads_no_clock(tracked_files):
    page = [
        p
        for p in tracked_files
        if p.startswith("static/") and not p.startswith("static/vendor/")
        if p.endswith((".js", ".mjs", ".html"))
    ]
    assert page, "git lists no page code"
    found = [
        f"{p}:{n}: {line.strip()}"
        for p in page
        for n, line in enumerate((REPO / p).read_text(encoding="utf-8").splitlines(), 1)
        if PAGE_CLOCK.search(line)
    ]
    assert found == []
