"""tools/check_fails_before.py (CLAUDE.md rule 8) on real git repositories: a product change is
proven only by a changed test that fails on the old code."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_fails_before as cfb  # noqa: E402

BASE = {"calc.py": "def spot(row):\n    return row['bid']\n",
        "tests/test_calc.py": "from calc import spot\n\n\ndef test_spot_reads_a_row():\n    assert spot({'bid': 1, 'last': 2}) in (1, 2)\n"}


def _git(root: Path, *a: str) -> None:
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)


def _repo(tmp_path: Path, pr: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    for name, text in BASE.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    _git(root, "add", *BASE)
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "pr")
    for name, text in pr.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    _git(root, "add", *pr)
    _git(root, "commit", "-q", "-m", "pr")
    return root


FIX = "def spot(row):\n    return row['last']\n"


def test_a_fix_with_a_test_that_fails_on_the_old_code_is_proven(tmp_path):
    root = _repo(tmp_path, {"calc.py": FIX, "tests/test_calc.py": (
        "from calc import spot\n\n\ndef test_spot_is_the_last_trade():\n    assert spot({'bid': 1, 'last': 2}) == 2\n")})
    assert cfb.violations(root, "main") == []


def test_a_fix_whose_test_already_passed_before_is_refused(tmp_path):
    root = _repo(tmp_path, {"calc.py": FIX, "tests/test_calc.py": (
        "from calc import spot\n\n\ndef test_spot_reads_a_row():\n    assert spot({'bid': 1, 'last': 2}) in (1, 2)\n\n"
        "def test_nothing():\n    assert True\n")})
    found = cfb.violations(root, "main")
    assert len(found) == 1 and found[0].startswith("every changed test passes on the old code (2 run")


def test_a_fix_with_no_test_change_is_refused(tmp_path):
    root = _repo(tmp_path, {"calc.py": FIX})
    assert cfb.violations(root, "main") == ["product code changed (calc.py) but no test under tests/ changed"]


def test_a_test_of_new_code_that_cannot_import_on_the_old_code_counts_as_failing_before(tmp_path):
    root = _repo(tmp_path, {"calc.py": FIX + "\n\ndef mid(row):\n    return (row['bid'] + row['ask']) / 2\n",
                            "tests/test_mid.py": "from calc import mid\n\n\ndef test_mid():\n    assert mid({'bid': 1, 'ask': 3}) == 2\n"})
    assert cfb.violations(root, "main") == []


def test_a_change_with_no_product_code_needs_no_test(tmp_path):
    root = _repo(tmp_path, {"docs/notes.md": "words\n"})
    assert cfb.violations(root, "main") == []
