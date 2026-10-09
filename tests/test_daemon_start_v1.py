"""The capture daemon starts only from origin/main: each start fetches origin and fast-forwards
the production checkout first; local changes stop it; an origin out of reach starts it with the
check unknown, never passed. Its log keeps a file a day for LOG_DAYS_KEPT days.

STAND-INS: local git repositories for GitHub's origin and the production checkout.
"""
from __future__ import annotations

import logging
import subprocess
from datetime import date, timedelta
from pathlib import Path

from app.market_data.schwab.streaming import capture


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

    assert capture.bring_to_origin_main(prod) == (capture.COMMIT_CURRENT, first, "at origin/main")

    merged = _merge(tmp_path / "work", "merged")                      # production one commit behind
    assert capture.bring_to_origin_main(prod) == (capture.COMMIT_MOVED, merged, f"fast-forwarded from {first}")
    assert _git(prod, "rev-parse", "HEAD") == merged
    assert capture.bring_to_origin_main(prod)[0] == capture.COMMIT_CURRENT    # the next start runs

    (prod / "first").write_text("edited in production", encoding="utf-8")
    _merge(tmp_path / "work", "later")
    check, at, why = capture.bring_to_origin_main(prod)
    assert (check, at) == (capture.COMMIT_REFUSED, merged) and why.startswith("local changes")
    assert _git(prod, "rev-parse", "HEAD") == merged, "a checkout with local changes was moved"

    (prod / "first").write_text("first", encoding="utf-8")
    _git(prod, "remote", "set-url", "origin", str(tmp_path / "unreachable.git"))
    check, at, why = capture.bring_to_origin_main(prod)
    assert (check, at) == (capture.COMMIT_UNKNOWN, merged) and why.startswith("origin could not be fetched")


def test_the_daemon_log_keeps_a_file_a_day_for_45_days(tmp_path):
    """50 earlier days' files beside the log; at the next midnight's rollover the 45 newest stay."""
    days = [date(2026, 8, 1) + timedelta(days=i) for i in range(50)]
    for d in days:
        (tmp_path / f"stream_capture.log.{d:%Y-%m-%d}").write_text(f"{d}\n", encoding="utf-8")
    handler = capture.log_file(tmp_path / "stream_capture.log")
    handler.emit(logging.LogRecord("capture", logging.INFO, __file__, 0, "today", None, None))
    handler.doRollover()
    handler.close()
    kept = sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("stream_capture.log."))
    assert len(kept) == capture.LOG_DAYS_KEPT == 45 and f"stream_capture.log.{days[0]:%Y-%m-%d}" not in kept
