"""tools/check_no_new_patches.py (TEST-PATCHES) on real git repositories: a test, fixture or helper
a pull request adds or changes may not patch; a function the PR leaves as it was is not judged."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_no_new_patches as cnp  # noqa: E402

OLD_FILE = ('import calc\n\n\n'
            'def test_old_one(monkeypatch):\n    monkeypatch.setattr(calc, "spot", lambda row: 1)\n    assert calc.spot({}) == 1\n\n\n'
            'def test_old_two():\n    assert calc.spot({"last": 2}) == 2\n')
CONFTEST = ('import pytest\n\n\n'
            '@pytest.fixture\ndef pinned(monkeypatch):\n    monkeypatch.setattr("time.time", lambda: 1.0)\n')
BASE = {"calc.py": "def spot(row):\n    return row['last']\n", "tests/test_old.py": OLD_FILE,
        "tests/conftest.py": CONFTEST}


def _git(root: Path, *a: str) -> None:
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)


def _pr(tmp_path: Path, files: dict[str, str]) -> Path:
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
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    _git(root, "add", *files)
    _git(root, "commit", "-q", "-m", "pr")
    return root


def test_a_new_test_using_monkeypatch_is_refused(tmp_path):
    root = _pr(tmp_path, {"tests/test_new.py": (
        "import calc\n\n\ndef test_new(monkeypatch):\n    monkeypatch.setattr(calc, 'spot', lambda r: 3)\n")})
    assert cnp.violations(root, "main") == [
        "tests/test_new.py::test_new patches (monkeypatch, mock.patch or a fixture that does)"]


def test_a_new_test_using_mock_patch_is_refused(tmp_path):
    root = _pr(tmp_path, {"tests/test_new.py": (
        "from unittest import mock\n\n\ndef test_new():\n    with mock.patch('calc.spot', return_value=3):\n        pass\n")})
    assert cnp.violations(root, "main") == [
        "tests/test_new.py::test_new patches (monkeypatch, mock.patch or a fixture that does)"]


def test_a_new_test_that_requests_a_patching_fixture_is_refused(tmp_path):
    root = _pr(tmp_path, {"tests/test_new.py": "def test_new(pinned):\n    assert True\n"})
    assert cnp.violations(root, "main") == [
        "tests/test_new.py::test_new patches (monkeypatch, mock.patch or a fixture that does)"]


def test_a_new_test_in_a_file_with_a_patching_autouse_fixture_is_refused(tmp_path):
    root = _pr(tmp_path, {"tests/test_new.py": (
        "import pytest\n\n\n@pytest.fixture(autouse=True)\ndef _pin(monkeypatch):\n    monkeypatch.setattr('time.time', lambda: 1.0)\n\n\n"
        "def test_new():\n    assert True\n")})
    assert cnp.violations(root, "main") == [
        "tests/test_new.py::_pin patches (monkeypatch, mock.patch or a fixture that does)",
        "tests/test_new.py::test_new runs under the file's patching autouse fixture _pin"]


def test_a_changed_old_test_that_still_patches_is_refused(tmp_path):
    root = _pr(tmp_path, {"tests/test_old.py": OLD_FILE.replace("lambda row: 1)\n    assert calc.spot({}) == 1",
                                                                "lambda row: 5)\n    assert calc.spot({}) == 5")})
    assert cnp.violations(root, "main") == [
        "tests/test_old.py::test_old_one patches (monkeypatch, mock.patch or a fixture that does)"]


def test_an_untouched_old_patching_test_is_allowed_when_its_file_changes_elsewhere(tmp_path):
    root = _pr(tmp_path, {"tests/test_old.py": OLD_FILE.replace('{"last": 2}) == 2', '{"last": 7}) == 7')})
    assert cnp.violations(root, "main") == []


def test_a_new_test_that_patches_nothing_is_allowed(tmp_path):
    root = _pr(tmp_path, {"tests/test_new.py": "import calc\n\n\ndef test_new():\n    assert calc.spot({'last': 4}) == 4\n"})
    assert cnp.violations(root, "main") == []
