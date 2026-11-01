"""The one-way locks, on real git repositories and the repository's own rules."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from tools import check_locks

ROOT = Path(__file__).resolve().parent.parent


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(ROOT / "tools", repo / "tools", ignore=shutil.ignore_patterns("__pycache__"))
    (repo / "tests").mkdir()
    (repo / "docs").mkdir()
    shutil.copy(ROOT / "docs" / "schwab_fields.csv", repo / "docs")
    (repo / "ACTIVE_PROGRAM.md").write_text("| ONE | NEXT | a row |\n", encoding="utf-8")
    (repo / "product.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


def _counts(repo: Path):
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x", "--no-verify"],
        cwd=repo,
        check=True,
    )
    return check_locks.counts(repo, (ROOT / check_locks.RULES).read_text(encoding="utf-8"))


def test_a_line_a_row_or_a_finding_more_is_refused(tmp_path):
    repo = _repo(tmp_path)
    base = _counts(repo)
    (repo / "product.py").write_text(
        "import sqlite3\n\nVALUE = sqlite3\nOTHER = print('x')\n", encoding="utf-8"
    )
    (repo / "ACTIVE_PROGRAM.md").write_text(
        "| ONE | NEXT | a row |\n| TWO | QUEUED | a row |\n", encoding="utf-8"
    )
    refused = "\n".join(check_locks.rises(base, _counts(repo)))
    assert "lines of product code: 1 -> 3" in refused
    assert "open work rows: 1 -> 2" in refused
    assert "ruff TID251: 0 -> 1" in refused
    assert "ruff T201: 0 -> 1" in refused


def test_a_noqa_hides_nothing(tmp_path):
    repo = _repo(tmp_path)
    base = _counts(repo)
    (repo / "product.py").write_text("import time\n\nNOW = time.time()  # noqa\n", encoding="utf-8")
    assert "ruff TID251: 0 -> 1" in check_locks.rises(base, _counts(repo))


def test_a_patch_in_a_test_is_refused(tmp_path):
    repo = _repo(tmp_path)
    base = _counts(repo)
    (repo / "tests" / "test_x.py").write_text(
        "def test_x(monkeypatch):\n    assert monkeypatch\n", encoding="utf-8"
    )
    assert "patching lines in tests: 0 -> 2" in check_locks.rises(base, _counts(repo))


def test_a_change_that_only_removes_passes(tmp_path):
    repo = _repo(tmp_path)
    base = _counts(repo)
    (repo / "ACTIVE_PROGRAM.md").write_text("", encoding="utf-8")
    assert check_locks.rises(base, _counts(repo)) == []
