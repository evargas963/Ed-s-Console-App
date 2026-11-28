"""tools.census.command: a command's output; one GitHub answers with its server error runs again.

The server error is gh's own words when GitHub answered the census's `gh run list` with HTTP 500
(Census run 46074488564, its first attempt). INDUCED: a stand-in command prints them and fails
as many times as asked, then answers; each wait given is 0 s, so no test waits.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

from tools.census import command

pytestmark = pytest.mark.rail

#: what gh printed when GitHub answered with its server error
GH_SERVER_ERROR = (
    "failed to get runs: HTTP 500 (https://api.github.com/repositories/1161301446/actions/runs"
    "?exclude_pull_requests=true&per_page=100&page=5)"
)
#: fails as gh did, its first `argv[2]` runs, saying `argv[3]` with exit code `argv[4]`, then
#: answers `[]`; each run is counted in the file `argv[1]`
STAND_IN = (
    "import sys; from pathlib import Path; f = Path(sys.argv[1]); n = len(f.read_text()) + 1; "
    "f.write_text('x' * n); bad = n <= int(sys.argv[2]); "
    "(sys.stderr if bad else sys.stdout).write((sys.argv[3] if bad else '[]') + chr(10)); "
    "sys.exit(int(sys.argv[4]) if bad else 0)"
)


def _stand_in(tmp_path: Path, fails: int, said: str = GH_SERVER_ERROR) -> list[object]:
    """Return the stand-in command, failing its first `fails` runs saying `said`."""
    (tmp_path / "runs").write_text("")
    return [sys.executable, "-c", STAND_IN, tmp_path / "runs", fails, said, 1]


def _runs(tmp_path: Path) -> int:
    """Return how many times the stand-in ran."""
    return len((tmp_path / "runs").read_text())


def test_a_server_error_is_run_again_after_each_wait_until_answered(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="census"):
        out = command.run(_stand_in(tmp_path, 2), tmp_path, stdout_only=True, again=(0, 0, 0))
    assert out == "[]\n" and _runs(tmp_path) == 3
    warned = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warned) == 2 and all("the server failed; run again in 0.0 s" in w for w in warned)
    assert all(GH_SERVER_ERROR in w for w in warned)


def test_a_server_error_after_the_last_wait_stops_the_census(tmp_path, caplog):
    with caplog.at_level(logging.ERROR, logger="census"), pytest.raises(SystemExit):
        command.run(_stand_in(tmp_path, 5), tmp_path, again=(0, 0))
    assert _runs(tmp_path) == 3
    (error,) = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert "exited 1" in error and GH_SERVER_ERROR in error


def test_any_other_failure_stops_the_census_at_once(tmp_path):
    """INDUCED: GitHub's answer that a run is not there, in gh's words; it is not asked again."""
    not_found = "HTTP 404: Not Found (https://api.github.com/repos/o/r/actions/runs/1)"
    with pytest.raises(SystemExit):
        command.run(_stand_in(tmp_path, 1, not_found), tmp_path, again=(0, 0))
    assert _runs(tmp_path) == 1


def test_a_command_given_no_waits_is_run_once(tmp_path):
    """Every checker that is not GitHub's: its failure stops the census, whatever it says."""
    with pytest.raises(SystemExit):
        command.run(_stand_in(tmp_path, 1), tmp_path)
    assert _runs(tmp_path) == 1


def test_an_exit_code_the_tool_gives_when_it_ran_is_its_answer(tmp_path):
    """A checker's code for findings (ruff's 1) is an answer, its output read, never run again."""
    out = command.run(_stand_in(tmp_path, 1, "a finding"), tmp_path, ok=(0, 1), again=(0,))
    assert out == "a finding\n" and _runs(tmp_path) == 1


def test_the_command_line_prints_githubs_answer(tmp_path, capsys):
    command.main([str(c) for c in _stand_in(tmp_path, 1)], again=(0,))
    assert capsys.readouterr().out == "[]\n" and _runs(tmp_path) == 2


def test_githubs_waits_double_from_one_second_to_the_cap():
    """Google's client defaults: first 1 s, each wait twice the last, at most 30 s."""
    waits = command.GITHUB_WAITS
    assert waits[0] == 1 and waits[-1] == 30
    assert all(b == min(2 * a, 30) for a, b in zip(waits, waits[1:], strict=False))
