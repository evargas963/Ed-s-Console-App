"""A command the census runs and its output; a command that fails stops the census.

    python -m tools.census.command gh <arguments>

A command whose output says the server failed (HTTP 5xx: GitHub's answer to `gh`) is run again
after each wait it is given, as a client asks again after a server error: longer each time, up
to a cap, each wait at random between half of it and all of it (docs/SOURCES.md
google-retry-strategy, aws-backoff-jitter). From the command line, one GitHub command (the
census job's, census.yml) is run with GITHUB_WAITS and its output printed.
"""

from __future__ import annotations

import logging
import random
import re
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

log = logging.getLogger("census")
SERVER_ERROR = re.compile(r"\bHTTP 5\d\d\b")
#: the waits before GitHub is asked again after its server error: from 1 s, doubled each time, to
#: 30 s (docs/SOURCES.md google-retry-strategy)
GITHUB_WAITS = (1, 2, 4, 8, 16, 30)


def run(
    cmd: Sequence[object],
    cwd: Path,
    stdout_only: bool = False,
    ok: Sequence[int] = (0,),
    again: Sequence[float] = (),
) -> str:
    """Return a command's output; an exit code outside `ok` stops the census.

    `ok` holds the codes the tool gives when it ran, with findings or without (ruff: 0, 1; vulture:
    0, 3; stylelint: 0, 2); any other code is the tool failing, and a checker that did not run
    would read as nothing found. `again` holds the waits, in seconds, before a command whose output
    says the server failed is run again; after the last, that failure stops the census too.
    """
    shown = " ".join(str(c) for c in cmd)[:200]
    for wait in (*again, None):
        r = subprocess.run(
            [str(c) for c in cmd],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
        )
        if r.returncode in ok or wait is None or not SERVER_ERROR.search(r.stdout + r.stderr):
            break
        waited = random.uniform(wait / 2, wait)
        log.warning(
            "census: %s: the server failed; run again in %.1f s:\n%s",
            shown,
            waited,
            (r.stdout + r.stderr)[-3000:],
        )
        time.sleep(waited)
    if r.returncode not in ok:
        log.error("census: %s exited %s:\n%s", shown, r.returncode, (r.stdout + r.stderr)[-3000:])
        raise SystemExit(1)
    return r.stdout if stdout_only else r.stdout + r.stderr


def main(argv: Sequence[str], again: Sequence[float] = GITHUB_WAITS) -> None:
    """Run one GitHub command, again after each of `again` while the server fails; print it."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.stdout.write(run(argv, Path.cwd(), stdout_only=True, again=again))


if __name__ == "__main__":
    main(sys.argv[1:])
