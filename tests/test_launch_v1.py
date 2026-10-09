"""The launcher (launch.py): whether a port is in use, against real local listeners on free ports.
It stops nothing: a port in use is reported and the console in it opened. Before it starts either
process it brings the checkout to origin/main: local changes stop it; an origin out of reach
starts it with the check unknown, never passed.

STAND-INS: local git repositories for GitHub's origin and the production checkout.
"""
from __future__ import annotations

import socket
import subprocess
from pathlib import Path

import launch


def test_a_port_with_a_listener_is_in_use_and_a_free_one_is_not():
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = held.getsockname()[1]
        assert launch.in_use(port) is True
    assert launch.in_use(port) is False


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _merge(work: Path, name: str) -> str:
    """A commit merged on origin's main; its id."""
    (work / name).write_text(name, encoding="utf-8")
    _git(work, "add", name)
    _git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", name)
    _git(work, "push", "-q", "origin", "HEAD:main")
    return _git(work, "rev-parse", "HEAD")


def test_each_start_brings_the_checkout_to_origin_main_or_says_why_it_cannot(tmp_path):
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", "origin.git")
    _git(tmp_path, "clone", "-q", "origin.git", "work")
    first = _merge(tmp_path / "work", "first")
    _git(tmp_path, "clone", "-q", "origin.git", "prod")
    prod = tmp_path / "prod"

    assert launch.bring_to_origin_main(prod) == (launch.COMMIT_CURRENT, first, "at origin/main")

    merged = _merge(tmp_path / "work", "merged")                      # production one commit behind
    assert launch.bring_to_origin_main(prod) == (launch.COMMIT_MOVED, merged, f"fast-forwarded from {first}")
    assert _git(prod, "rev-parse", "HEAD") == merged
    assert launch.bring_to_origin_main(prod)[0] == launch.COMMIT_CURRENT     # the run after it starts

    (prod / "first").write_text("edited in production", encoding="utf-8")
    _merge(tmp_path / "work", "later")
    check, at, why = launch.bring_to_origin_main(prod)
    assert (check, at) == (launch.COMMIT_REFUSED, merged) and why.startswith("local changes")
    assert _git(prod, "rev-parse", "HEAD") == merged, "a checkout with local changes was moved"

    (prod / "first").write_text("first", encoding="utf-8")
    _git(prod, "remote", "set-url", "origin", str(tmp_path / "unreachable.git"))
    check, at, why = launch.bring_to_origin_main(prod)
    assert (check, at) == (launch.COMMIT_UNKNOWN, merged) and why.startswith("origin could not be fetched")
