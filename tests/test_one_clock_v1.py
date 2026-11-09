"""One clock, repo wide (operator 2026-11-05: "fix the fucking clock ... REPO WIDE NO
EXCEPTIONS"): the computer's clock is read in time_et.py alone (time_et.now, time_et.elapsed);
every other file takes the time from it, and the page reads no clock at all (its time of day is
the program's, from the daemon's heartbeat).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
#: a clock read in page code
PAGE_CLOCK = re.compile(r"Date\.now\(|new Date\(\s*\)|performance\.now\(")


@pytest.mark.parametrize(
    "line",
    [
        "import time\nT = time.time()\n",
        "import time\nT = time.monotonic()\n",
        "import time\nT = time.perf_counter()\n",
        "from datetime import datetime\nT = datetime.now()\n",
        "from datetime import date\nT = date.today()\n",
    ],
)
def test_a_clock_read_outside_time_et_is_refused_in_any_file(line):
    for name in ("server.py", "tests/test_x.py", "tools/x.py", "app/x.py"):
        done = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--stdin-filename", name, "-"],
            input=line,
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        assert done.returncode == 1 and "TID251" in done.stdout, (name, done.stdout)


def test_time_et_is_the_one_producer_of_the_time():
    done = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "TID251", "time_et.py"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert done.returncode == 0, done.stdout


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
