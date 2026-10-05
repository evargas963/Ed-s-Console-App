"""tools/check_fails_before.py's exemption for a PR that only removes (AGENTS.md Before writing code), on real
files from 26ddc457 and, where no real file has the form, a test module written here (MODULE): a change
to what the surviving tests run is not a deletion of tests.

Induced in every case: the PR's product change is one comment line removed from server.py (a product
change that adds no line), so that only the test-tree change decides the exemption."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import check_fails_before as cfb  # noqa: E402
from tests.test_check_end_to_end_v1 import _real_repo  # noqa: E402

BARS = "tests/test_bars_from_stream_v1.py"
WRITTEN = "tests/test_written_v1.py"
#: a test module written for these tests: no real test file has a `name=` fixture, setUpModule, a
#: side-effect assignment, a fixture built by a call or a registration decorator
MODULE = '''import atexit
import os

import pytest

_ = os.environ.setdefault("ED_WRITTEN_FLAG", "1")


def _impl():
    yield


_auto = pytest.fixture(autouse=True)(_impl)


@atexit.register
def _cleanup():
    pass


@pytest.fixture(name="db")
def _db_fixture():
    return {"rows": 1}


def setUpModule():
    pass


def tearDownModule():
    pass


def test_db(db):
    assert db["rows"] == 1
'''


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
    assert cfb.violations(root, "main") == [
        "product code changed (server.py) but no test file (tests/**/test_*.py, tests/e2e/*.spec.js) was added or changed"]
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
        f"no changed test ran on the old code ({BARS}): a module that cannot be imported there, "
        "or a run with no result, proves nothing about this change"]
    assert "nothing to fail before" not in capsys.readouterr().out


def _written_pr(tmp_path: Path, removed: str) -> Path:
    """A base of 26ddc457's server.py and the written MODULE; the PR removes server.py's "App directory"
    comment line and `removed` from the module."""
    def git(*a: str) -> None:
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    git("config", "core.autocrlf", "false")
    text = subprocess.run(["git", "show", "26ddc457:server.py"], cwd=REPO, check=True, capture_output=True).stdout
    (tmp_path / "server.py").write_bytes(text)
    (tmp_path / "tests").mkdir()
    (tmp_path / WRITTEN).write_bytes(MODULE.encode())
    git("add", "server.py", WRITTEN)
    git("commit", "-q", "-m", "base")
    git("checkout", "-q", "-b", "pr")
    start = text.index("# ── App directory".encode())
    (tmp_path / "server.py").write_bytes(text[:start] + text[text.index(b"\n", start) + 1:])
    assert removed in MODULE
    (tmp_path / WRITTEN).write_bytes(MODULE.replace(removed, "", 1).encode())
    git("commit", "-q", "-am", "pr")
    return tmp_path


@pytest.mark.parametrize("removed", [
    '@pytest.fixture(name="db")\ndef _db_fixture():\n    return {"rows": 1}\n\n\n',
    "def setUpModule():\n    pass\n\n\n",
    "def tearDownModule():\n    pass\n\n\n",
    '_ = os.environ.setdefault("ED_WRITTEN_FLAG", "1")\n',
    "_auto = pytest.fixture(autouse=True)(_impl)\n",
    "@atexit.register\ndef _cleanup():\n    pass\n\n\n",
], ids=["fixture-named-db", "setUpModule", "tearDownModule", "side-effect-assignment", "fixture-built-by-a-call",
        "registration-decorator"])
def test_removing_what_the_remaining_test_runs_keeps_the_rule(tmp_path, capsys, removed):
    """A fixture registered as name="db", which the remaining test takes as `db`; setUpModule /
    tearDownModule, which pytest calls by name (_pytest/python.py, beside setup_module); an assignment
    whose value runs code at import; an autouse fixture built by calling pytest.fixture; a def with a
    decorator that is not pytest's (it runs at import): removing any of them changes what runs, so it
    is not a deletion of tests."""
    root = _written_pr(tmp_path, removed)
    assert cfb.numstat(root, "main")[WRITTEN] == 0
    assert cfb.only_deletes_whole_tests(root, "main", WRITTEN) is False
    cfb.violations(root, "main")
    assert "nothing to fail before" not in capsys.readouterr().out
