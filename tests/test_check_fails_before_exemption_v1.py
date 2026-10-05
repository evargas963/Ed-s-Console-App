"""tools/check_fails_before.py's exemption for a PR that only removes (AGENTS.md Before writing code), on real
files from 26ddc457: a change to what the surviving tests run is not a deletion of tests.

Induced in every case: the PR's product change is one comment line removed from server.py (a product
change that adds no line), so that only the test-tree change decides the exemption."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import check_fails_before as cfb  # noqa: E402
from tests.test_check_end_to_end_v1 import _real_repo  # noqa: E402

BARS = "tests/test_bars_from_stream_v1.py"


def _pr(tmp_path: Path, change) -> Path:
    """server.py, tests/conftest.py and tests/test_bars_from_stream_v1.py as they are at 26ddc457; the PR
    removes server.py's "App directory" comment line and makes `change`."""
    root = _real_repo(tmp_path, "26ddc457", ["server.py", "tests/conftest.py", BARS])
    server = root / "server.py"
    text = server.read_bytes()
    start = text.index("# ── App directory".encode())
    server.write_bytes(text[:start] + text[text.index(b"\n", start) + 1:])
    change(root)
    subprocess.run(["git", "commit", "-q", "-am", "pr"], cwd=root, check=True, capture_output=True)
    return root


def test_deleting_conftest_whole_keeps_the_rule(tmp_path, capsys):
    """tests/conftest.py deleted whole: its three autouse fixtures no longer run for any test, so it is
    not a deletion of tests; with no test file changed, the change is refused."""
    root = _pr(tmp_path, lambda r: subprocess.run(["git", "rm", "-q", "tests/conftest.py"], cwd=r, check=True))
    assert cfb.only_deletes_whole_tests(root, "main", "tests/conftest.py") is False
    assert cfb.violations(root, "main") == ["product code changed (server.py) but no test under tests/ changed"]
    assert "nothing to fail before" not in capsys.readouterr().out


def test_removing_setup_function_keeps_the_rule_and_a_run_with_no_result_is_refused(tmp_path, capsys):
    """setup_function removed from tests/test_bars_from_stream_v1.py: pytest calls it by name before each
    test (it clears server._bars), so the tests left run differently. The file's tests then run on the
    base, where this few-file copy's conftest.py cannot load: no test runs, and that is refused, not
    reported as passing."""
    def remove(root: Path) -> None:
        f = root / BARS
        text = f.read_bytes()
        f.write_bytes(text.replace(b"def setup_function(_fn):\n    _clear()\n\n\n", b"", 1))
        assert f.read_bytes() != text
    root = _pr(tmp_path, remove)
    assert cfb.numstat(root, "main")[BARS] == 0
    assert cfb.only_deletes_whole_tests(root, "main", BARS) is False
    assert cfb.violations(root, "main") == [
        f"no changed test ran on the old code ({BARS}): the run gave no result, so nothing proves this change"]
    assert "nothing to fail before" not in capsys.readouterr().out
