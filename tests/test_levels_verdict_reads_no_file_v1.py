"""The levels verdict every panel and route serves reads no file (server.terrain_staleness).

It read the Schwab token file on every call (its creation_timestamp, for a token age no screen,
tool or route reader shows since the 2026-09-14 cutover), and with it re-resolved the runtime
root (runtime_layout.runtime_root: the .git marker, its commondir): about 2 to 3 ms and three
file opens per verdict, on every panel of every page. The token file has one reader, the
program's Schwab client (schwab_client.OneRefreshSession), which holds the sign-in.

Run in a fresh interpreter, whose every file open after the imports Python's audit hook records.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

VERDICT = (
    "import json, sys, server, time_et; opened = []; "
    "sys.addaudithook(lambda ev, a: opened.append(str(a[0])) if ev == 'open' else None); "
    "v = server.terrain_staleness(None, 'SPY', now=time_et.now()); "
    "print(json.dumps({'opened': opened, 'keys': sorted(v)}))"
)


def test_a_levels_verdict_opens_no_file_and_serves_no_token_age():
    done = subprocess.run(
        [sys.executable, "-c", VERDICT],
        cwd=REPO,
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    )
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["opened"] == []
    assert out["keys"] == [
        "levels_age_text",
        "levels_stale_reason",
        "levels_state",
        "levels_time_ct",
    ]
