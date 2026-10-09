"""Production is never behind: its checkout (runtime_layout.RUNTIME_ROOT, git's primary worktree)
is at origin/main, and the capture daemon running from it started from that commit (the
`start_commit` of its heartbeat on its browser socket). Run at the start of every Claude session
(.claude/settings.json, SessionStart, through tools/hook_chain.py): exit 1, with each way it is
behind, when it is; a daemon that does not answer is reported, not a failure.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runtime_layout import RUNTIME_ROOT  # noqa: E402

DAEMON = "ws://127.0.0.1:8800"
#: the longest the daemon's heartbeat is waited for (it beats every second, live_ui.HEARTBEAT_SEC)
BEAT_WAIT_SEC = 10.0


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True,
                          timeout=60).stdout.strip()


def check(repo: Path, daemon: str) -> "list[str]":
    """Each way `repo` and the daemon at `daemon` are behind origin/main; none when neither is."""
    try:
        _git(repo, "fetch", "--quiet", "origin", "main")
    except subprocess.SubprocessError as e:
        return [f"origin could not be fetched ({type(e).__name__}: {e})"]
    head, main = _git(repo, "rev-parse", "HEAD"), _git(repo, "rev-parse", "origin/main")
    behind = [] if head == main else [f"the checkout {repo} is at {head[:12]}, origin/main at {main[:12]}"]
    deadline = time.monotonic() + BEAT_WAIT_SEC
    try:
        with connect(daemon, open_timeout=BEAT_WAIT_SEC) as ws:
            while (beat := json.loads(ws.recv(timeout=deadline - time.monotonic()))).get("type") != "feed" \
                    or beat["feed"] is None:
                pass
    except (OSError, TimeoutError, ValueError, WebSocketException) as e:
        print(f"capture daemon: no heartbeat at {daemon} ({type(e).__name__}: {e})")
        return behind
    if beat["feed"].get("start_commit") != head:
        behind.append(f"the capture daemon started from {beat['feed'].get('start_commit')}, "
                      f"the checkout is at {head[:12]}")
    return behind


def main() -> int:
    """The hook: its payload on stdin, refused (2) when it is not a JSON object, as every hook
    member refuses it; then the check of production."""
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        print("NEVER BEHIND: the hook payload is not a JSON object", file=sys.stderr)
        return 2
    behind = check(RUNTIME_ROOT, DAEMON)
    for line in behind:
        print(f"BEHIND: {line}", file=sys.stderr)
    return 1 if behind else 0


if __name__ == "__main__":
    sys.exit(main())
