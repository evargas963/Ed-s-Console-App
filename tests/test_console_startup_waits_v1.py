"""The console's start, as its window shows it: while it waits for the capture daemon's
heartbeat, it says what it waits for and for how long. The real console (uvicorn server:app) on
a free port, with no daemon to reach (ports 1, as the browser tests)."""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_the_console_says_what_it_waits_for_and_for_how_long(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}   # its loops start
    env.update(ED_RUNTIME_ROOT=str(tmp_path), ED_ARTIFACTS_ROOT=str(tmp_path / "artifacts"),
               ED_LIVE_PUSH_PORT="1", ED_LIVE_UI_PORT="1",
               SCHWAB_TOKEN_PATH=str(tmp_path / "missing_schwab_token.json"), PYTHONIOENCODING="utf-8")
    console = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
                                "--port", str(port)], cwd=REPO, env=env, text=True, encoding="utf-8",
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    lines: list = []
    threading.Thread(target=lambda: lines.extend(console.stdout), daemon=True).start()
    waited = "waiting for the capture daemon's heartbeat (it says what the board is) ("
    try:
        end = time.monotonic() + 120
        while sum(waited in ln for ln in list(lines)) < 2:
            assert console.poll() is None and time.monotonic() < end, "".join(lines)
            time.sleep(0.25)
    finally:
        console.kill()
        console.wait(30)
    text = "".join(lines)
    assert "stored bars" not in text, "nothing is loaded from a database at the start"
    seconds =[int(s) for s in re.findall(re.escape(waited) + r"(\d+) s so far\)", text)]
    assert seconds[0] == 0 and seconds[1] >= 5, text
