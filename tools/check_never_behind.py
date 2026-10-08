"""Production is never behind: its checkout is at origin/main, and the capture daemon running
from it started from that commit.

    python tools/check_never_behind.py --repo PATH [--daemon ws://127.0.0.1:8800]
    python tools/hook_chain.py tools/check_never_behind.py      (a hook: the payload on stdin)

The checkout is production's (runtime_layout.RUNTIME_ROOT, git's primary worktree) from any
worktree, unless --repo names another. Fetches origin, then compares its HEAD with origin/main, and reads the running
daemon's start commit from its heartbeat (the `start_commit` of the daemon's status on its
browser socket, capture.Daemon.status). Prints all three. Exit 1 when HEAD is not origin/main, or
a running daemon started from another commit; a daemon that does not answer is reported, not a
failure (it is not running). Run at the start of every Claude session (.claude/settings.json,
SessionStart, through the one hook executor); a failure reaches the operator on screen.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runtime_layout import RUNTIME_ROOT  # noqa: E402  (production: git's primary worktree)

DAEMON = "ws://127.0.0.1:8800"
#: seconds to wait for the daemon's heartbeat (it beats every second, live_ui.HEARTBEAT_SEC)
BEAT_WAIT_SEC = 5.0


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True,
                          timeout=60).stdout.strip()


def daemon_start_commit(url: str) -> "tuple[str | None, str | None]":
    """(the running daemon's start commit, None), or (None, why it could not be read)."""
    from websockets.exceptions import WebSocketException
    from websockets.sync.client import connect
    try:
        with connect(url, open_timeout=BEAT_WAIT_SEC) as ws:
            while True:
                frame = json.loads(ws.recv(timeout=BEAT_WAIT_SEC))
                if frame.get("type") == "feed" and frame.get("feed") is not None:
                    return frame["feed"].get("start_commit"), None
    except (OSError, TimeoutError, WebSocketException) as e:
        return None, f"no daemon heartbeat at {url} ({type(e).__name__}: {e})"


def main(argv: "list[str] | None" = None) -> int:
    """`argv` None: run as a hook (tools/hook_chain.py), its payload on stdin and every default;
    a payload that is not a JSON object is refused (2), as every hook member refuses it."""
    if argv is None:
        try:
            payload = json.loads(sys.stdin.read())
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            print("NEVER BEHIND: the hook payload is not a JSON object", file=sys.stderr)
            return 2
        argv = []
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=RUNTIME_ROOT)
    ap.add_argument("--daemon", default=DAEMON)
    args = ap.parse_args(argv)
    _git(args.repo, "fetch", "--quiet", "origin", "main")
    head, main_ = _git(args.repo, "rev-parse", "HEAD"), _git(args.repo, "rev-parse", "origin/main")
    started, why = daemon_start_commit(args.daemon)
    behind = _git(args.repo, "rev-list", "--count", f"HEAD..{main_}")
    print(f"checkout {args.repo}: HEAD {head[:12]}, origin/main {main_[:12]}, {behind} commits behind")
    if why is not None:
        print(f"capture daemon: {why}")
    else:
        print(f"capture daemon: started from {started}" if started is not None else
              "capture daemon: running, and its heartbeat does not say which commit it started from")
    failed = head != main_ or (why is None and started != head)
    if head != main_:
        print("FAIL: the checkout is not at origin/main", file=sys.stderr)
    if why is None and started != head:
        print("FAIL: the running daemon did not start from the checkout's commit", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
