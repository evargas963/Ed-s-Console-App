"""The one-way locks, on real git repositories and the repository's own rules."""

from __future__ import annotations

import gzip
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from tests.shared_helpers import write
from tools import check_locks

pytestmark = pytest.mark.rail

ROOT = Path(__file__).resolve().parent.parent


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True
    )


def _repo(tmp_path: Path) -> Path:
    """Make a repository on main with the locks' rules, one module and one work row."""
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(ROOT / check_locks.RULES, repo)
    (repo / "ACTIVE_PROGRAM.md").write_text("- ONE (NEXT): an item\n", encoding="utf-8")
    (repo / "product.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo)
    _git(repo, "checkout", "-q", "-b", "change")
    return repo


def _commit(repo: Path) -> None:
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "x", "--no-verify", "--allow-empty")


def _refused(repo: Path) -> str:
    _commit(repo)
    return "\n".join(check_locks.judge(repo, "main"))


def test_a_finding_at_zero_is_refused_and_a_line_or_a_work_item_more_is_not(tmp_path):
    repo = _repo(tmp_path)
    write(repo, "product.py", "VALUE = 1\nOTHER = print('x')\n")
    write(repo, "ACTIVE_PROGRAM.md", "- ONE (NEXT): an item\n- TWO (QUEUED): an item\n- P-1 x\n")
    refused = _refused(repo)
    assert "lines of product code" not in refused
    assert "open work items" not in refused
    assert "ruff T201: 0 -> 1" in refused


def test_compressed_data_adds_no_lines(tmp_path):
    """A gzip file is data: its bytes split at a newline byte are no lines of code."""
    repo = _repo(tmp_path)
    rules = (repo / check_locks.RULES).read_text(encoding="utf-8")
    before = check_locks.counts(repo, rules)
    (repo / "tests").mkdir()
    (repo / "tests" / "capture.json.gz").write_bytes(gzip.compress(b'{"a": 1}\n' * 5000))
    _commit(repo)
    after = check_locks.counts(repo, rules)
    assert (after["lines of tests"], after["bytes of tests"]) == (
        before["lines of tests"],
        before["bytes of tests"],
    )


def test_every_item_of_the_work_list_is_counted_and_a_detail_under_one_is_not(tmp_path):
    repo = _repo(tmp_path)
    write(
        repo,
        "ACTIVE_PROGRAM.md",
        "# Work\n\nOne line per item.\n\n- ONE (NEXT): an item\n- STAND-INS (QUEUED; also P-1): x\n"
        "  - a detail of it\n- RESEARCH: still designed\n",
    )
    _commit(repo)
    rules = (repo / check_locks.RULES).read_text(encoding="utf-8")
    assert check_locks.counts(repo, rules)["open work items"] == 3


def test_only_size_may_rise_above_zero():
    for name in (
        "lines of tests",
        "bytes of product code",
        "open work items",
    ):
        assert check_locks.rises(Counter({name: 5}), Counter({name: 6})) == []
    for name in (
        "ruff D205",
        "banned in tests: `sqlite3` is banned: Only the Recorder uses a database.",
        "banned in server.py: `sqlite3` is banned",
        "banned in tests: `websockets` is banned: Only Feed talks to Schwab.",
        "format suppressions",
        "patching lines in tests",
        "ruff BLE001",
    ):
        assert check_locks.rises(Counter({name: 5}), Counter({name: 6})) == [f"{name}: 5 -> 6"]


def test_a_change_that_only_removes_passes(tmp_path):
    repo = _repo(tmp_path)
    write(repo, "ACTIVE_PROGRAM.md", "")
    assert _refused(repo) == ""


def test_no_comment_hides_a_finding(tmp_path):
    repo = _repo(tmp_path)
    write(repo, "a.py", "# ruff: noqa\nX = print(1)\n")
    write(repo, "b.py", "# ruff: disable[T201]\nX = print(1)\n")
    write(repo, "c.py", "X = print(1)  # noqa\n")
    assert "ruff T201: 0 -> 3" in _refused(repo)


def test_no_ignore_file_or_excluded_folder_hides_a_finding(tmp_path):
    repo = _repo(tmp_path)
    write(repo, ".ignore", "*.py\n")
    write(repo, "dist/a.py", "X = print(1)\n")
    assert "ruff T201: 0 -> 1" in _refused(repo)


@pytest.mark.parametrize(
    "name",
    [
        "windows.pyw",
        "book.ipynb",
        "upper.PY",
        "compiled.pyc",
        "native.pyd",
        "native.abi3.so",
        "two.dots.py",
        ".hidden.py",
        "not-a-name/__init__.py",
        "orphans/a.py",
    ],
)
def test_a_file_outside_the_import_contracts_is_refused(tmp_path, name):
    repo = _repo(tmp_path)
    write(repo, name, "#!/usr/bin/env python\nVALUE = 1\n")
    refused = _refused(repo)
    assert "files outside the import contracts: 0 -> 1" in refused


def test_a_module_in_a_package_is_inside_them(tmp_path):
    repo = _repo(tmp_path)
    write(repo, "part/__init__.py", "")
    write(repo, "part/inner/__init__.py", "")
    write(repo, "part/inner/module.py", "VALUE = 1\n")
    write(repo, "root_module.py", "VALUE = 1\n")
    assert _refused(repo) == ""


def test_a_type_stub_python_never_loads_is_not_counted(tmp_path):
    """A `.pyi` is read by type checkers alone: no loader of Python's takes it
    (importlib.machinery.all_suffixes), so it imports nothing when the program runs."""
    repo = _repo(tmp_path)
    write(repo, "typings/lib/__init__.pyi", "VALUE: int\n")
    write(repo, "typings/lib/Part.PYI", "VALUE: int\n")
    assert _refused(repo) == ""


def test_a_file_named_ruff_in_the_change_does_not_answer_for_ruff(tmp_path):
    repo = _repo(tmp_path)
    write(repo, "ruff.py", "print('[]')\n")
    assert "ruff T201: 0 -> 1" in _refused(repo)


def test_a_new_kind_of_file_and_a_foreign_name_are_counted(tmp_path, capsys):
    repo = _repo(tmp_path)
    write(repo, "módulo.py", "VALUE = 1\n")
    write(repo, "script.cmd", "echo hi\n")
    _refused(repo)
    reported = capsys.readouterr().out
    before, after = reported.split("bytes of product code: ")[1].split("\n")[0].split(" -> ")
    assert int(after) - int(before) == len("VALUE = 1\necho hi\n")


def test_a_banned_name_in_a_new_module_is_not_bought_by_removing_it_elsewhere(tmp_path):
    repo = _repo(tmp_path)
    write(repo, "product.py", "import sqlite3\n\nVALUE = sqlite3\n")
    _commit(repo)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-verify", "change")
    _git(repo, "checkout", "-q", "change")
    (repo / "product.py").unlink()
    write(repo, "other.py", "import sqlite3\n\nVALUE = sqlite3\n")
    refused = _refused(repo)
    assert "banned in other.py" in refused
    assert "Only the Recorder uses a database" in refused


def test_a_patch_in_a_test_is_refused(tmp_path):
    repo = _repo(tmp_path)
    write(repo, "tests/test_x.py", "def test_x(m):\n    m.MonkeyPatch()\n")
    assert "patching lines in tests: 0 -> 1" in _refused(repo)


def test_a_folder_in_another_case_is_the_same_folder(tmp_path):
    repo = _repo(tmp_path)
    write(repo, "Tests/test_y.py", "def test_y(m):\n    m.MonkeyPatch()\n")
    write(repo, "Tools/y.py", "VALUE = 1\n")
    refused = _refused(repo)
    assert "lines of tests" in refused
    assert "lines of tools" in refused
    assert "patching lines in tests: 0 -> 1" in refused


def test_a_file_named_as_an_option_is_not_read_as_one(tmp_path):
    repo = _repo(tmp_path)
    write(repo, "--config=lint.ignore=['ALL']#.py", "X = print(1)\n")
    assert "ruff T201: 0 -> 1" in _refused(repo)


def test_a_format_suppression_is_refused(tmp_path):
    repo = _repo(tmp_path)
    write(
        repo, "product.py", "VALUE = [1, 2]  # fmt: skip\n# isort: skip_file\n# ruff: isort: off\n"
    )
    assert "format suppressions: 0 -> 3" in _refused(repo)


def test_loading_code_from_a_data_file_is_refused(tmp_path):
    repo = _repo(tmp_path)
    write(repo, "product.py", "import importlib.util\n\nVALUE = importlib.util\n")
    assert "No code runs from a data file" in _refused(repo)


def test_a_refused_change_exits_3_and_a_clean_one_0(tmp_path):
    repo = _repo(tmp_path)
    tool = [sys.executable, str(ROOT / "tools" / "check_locks.py"), "--base", "main"]
    assert subprocess.run(tool, cwd=repo, capture_output=True, check=False).returncode == 0
    write(repo, "product.py", "VALUE = 1\nOTHER = print(2)\n")
    _commit(repo)
    assert subprocess.run(tool, cwd=repo, capture_output=True, check=False).returncode == 3
