"""The one-way locks, on real git repositories and the repository's own rules."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

from tools import check_locks

ROOT = Path(__file__).resolve().parent.parent


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True
    )


def _repo(tmp_path: Path) -> Path:
    """A repository on main with the locks' rules, one module and one work row."""
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(ROOT / check_locks.RULES, repo)
    (repo / "ACTIVE_PROGRAM.md").write_text("| ONE | NEXT | a row |\n", encoding="utf-8")
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


def _write(repo: Path, name: str, text: str) -> None:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text, encoding="utf-8")


def test_a_finding_at_zero_is_refused_and_a_line_or_a_work_item_more_is_not(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "product.py", "VALUE = 1\nOTHER = print('x')\n")
    _write(repo, "ACTIVE_PROGRAM.md", "| ONE | NEXT | a row |\n| TWO | LATER | a row |\n- P-1 x\n")
    refused = _refused(repo)
    assert "lines of product code" not in refused
    assert "open work items" not in refused
    assert "ruff T201: 0 -> 1" in refused


def test_only_size_may_rise_above_zero():
    for name in ("lines of tests", "bytes of product code", "open work items", "ruff D205"):
        assert check_locks.rises(Counter({name: 5}), Counter({name: 6})) == []
    for name in (
        "banned in server.py: `sqlite3` is banned",
        "format suppressions",
        "patching lines in tests",
        "ruff BLE001",
    ):
        assert check_locks.rises(Counter({name: 5}), Counter({name: 6})) == [f"{name}: 5 -> 6"]


def test_a_change_that_only_removes_passes(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "ACTIVE_PROGRAM.md", "")
    assert _refused(repo) == ""


def test_no_comment_hides_a_finding(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "a.py", "# ruff: noqa\nX = print(1)\n")
    _write(repo, "b.py", "# ruff: disable[T201]\nX = print(1)\n")
    _write(repo, "c.py", "X = print(1)  # noqa\n")
    assert "ruff T201: 0 -> 3" in _refused(repo)


def test_no_ignore_file_or_excluded_folder_hides_a_finding(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, ".ignore", "*.py\n")
    _write(repo, "dist/a.py", "X = print(1)\n")
    assert "ruff T201: 0 -> 1" in _refused(repo)


def test_a_file_named_ruff_in_the_change_does_not_answer_for_ruff(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "ruff.py", "print('[]')\n")
    assert "ruff T201: 0 -> 1" in _refused(repo)


def test_a_new_kind_of_file_and_a_foreign_name_are_counted(tmp_path, capsys):
    repo = _repo(tmp_path)
    _write(repo, "módulo.py", "VALUE = 1\n")
    _write(repo, "script.cmd", "echo hi\n")
    _refused(repo)
    reported = capsys.readouterr().out
    before, after = reported.split("bytes of product code: ")[1].split("\n")[0].split(" -> ")
    assert int(after) - int(before) == len("VALUE = 1\necho hi\n")


def test_a_banned_name_in_a_new_module_is_not_bought_by_removing_it_elsewhere(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "product.py", "import sqlite3\n\nVALUE = sqlite3\n")
    _commit(repo)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-verify", "change")
    _git(repo, "checkout", "-q", "change")
    (repo / "product.py").unlink()
    _write(repo, "other.py", "import sqlite3\n\nVALUE = sqlite3\n")
    refused = _refused(repo)
    assert "banned in other.py" in refused
    assert "Only the Recorder uses a database" in refused


def test_a_patch_in_a_test_is_refused(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "tests/test_x.py", "def test_x(m):\n    m.MonkeyPatch()\n")
    assert "patching lines in tests: 0 -> 1" in _refused(repo)


def test_a_folder_in_another_case_is_the_same_folder(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "Tests/test_y.py", "def test_y(m):\n    m.MonkeyPatch()\n")
    _write(repo, "Tools/y.py", "VALUE = 1\n")
    refused = _refused(repo)
    assert "lines of tests" in refused
    assert "lines of tools" in refused
    assert "patching lines in tests: 0 -> 1" in refused


def test_a_lock_file_changes_only_on_approval(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "tools/x.py", "\n")
    _write(repo, ".github/workflows/x.yml", "\n")
    _write(repo, ".cursor/hooks.json", "{}\n")
    _write(repo, "sub/conftest.py", "\n")
    _write(repo, "sub/ruff.toml", "\n")
    _write(repo, "pytest.toml", "\n")
    _write(repo, "sub/.gitattributes", "\n")
    _write(repo, "other/Conftest.py", "\n")
    _write(repo, "AGENTS.md", "\n")
    refused = _refused(repo)
    assert "lock file: AGENTS.md" in refused
    assert "lock file: pytest.toml" in refused
    assert "lock file: sub/.gitattributes" in refused
    assert "lock file: other/Conftest.py" in refused
    assert "lock file: tools/x.py" in refused
    assert "lock file: .github/workflows/x.yml" in refused
    assert "lock file: .cursor/hooks.json" in refused
    assert "lock file: sub/conftest.py" in refused
    assert "lock file: sub/ruff.toml" in refused


def test_removing_or_renaming_the_rules_is_refused(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "mv", check_locks.RULES, "other.toml")
    assert f"lock file: {check_locks.RULES}" in _refused(repo)


def test_a_file_named_as_an_option_is_not_read_as_one(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "--config=lint.ignore=['ALL']#.py", "X = print(1)\n")
    assert "ruff T201: 0 -> 1" in _refused(repo)


def test_a_format_suppression_is_refused(tmp_path):
    repo = _repo(tmp_path)
    _write(
        repo, "product.py", "VALUE = [1, 2]  # fmt: skip\n# isort: skip_file\n# ruff: isort: off\n"
    )
    assert "format suppressions: 0 -> 3" in _refused(repo)


def test_loading_code_from_a_data_file_is_refused(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "product.py", "import importlib.util\n\nVALUE = importlib.util\n")
    assert "No code runs from a data file" in _refused(repo)


def test_a_refused_change_exits_3_and_a_clean_one_0(tmp_path):
    repo = _repo(tmp_path)
    tool = [sys.executable, str(ROOT / "tools" / "check_locks.py"), "--base", "main"]
    assert subprocess.run(tool, cwd=repo, capture_output=True, check=False).returncode == 0
    _write(repo, "product.py", "VALUE = 1\nOTHER = print(2)\n")
    _commit(repo)
    assert subprocess.run(tool, cwd=repo, capture_output=True, check=False).returncode == 3
