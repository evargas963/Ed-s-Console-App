"""tools/check_no_new_patches.py (TEST-PATCHES) on real git repositories: a test, fixture or helper
whose code a pull request adds or changes may not patch; one whose docstrings and comments alone
change, or that the PR leaves as it was, is not judged."""
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


def _pr(tmp_path: Path, files: dict[str, str], base: dict[str, str] = BASE) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    for name, text in base.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    _git(root, "add", *base)
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


def test_an_old_patching_test_whose_docstring_and_comments_alone_change_passes(tmp_path):
    """Operator 2026-10-28: a patching test may change in its docstrings and comments; its code may not."""
    root = _pr(tmp_path, {"tests/test_old.py": OLD_FILE.replace(
        "def test_old_one(monkeypatch):\n", 'def test_old_one(monkeypatch):\n    """The spot reader."""\n').replace(
        "    assert calc.spot({}) == 1", "    assert calc.spot({}) == 1  # the patched value")})
    assert cnp.violations(root, "main") == []


def test_an_old_patching_test_whose_code_changes_is_refused(tmp_path):
    root = _pr(tmp_path, {"tests/test_old.py": OLD_FILE.replace(
        "lambda row: 1)\n    assert calc.spot({}) == 1", "lambda row: 5)\n    assert calc.spot({}) == 5")})
    assert cnp.violations(root, "main") == [
        "tests/test_old.py::test_old_one patches (monkeypatch, mock.patch or a fixture that does)"]


def test_a_patching_fixture_made_autouse_is_refused(tmp_path):
    root = _pr(tmp_path, {"tests/conftest.py": CONFTEST.replace("@pytest.fixture\n", "@pytest.fixture(autouse=True)\n")})
    assert cnp.violations(root, "main") == [
        "tests/conftest.py::pinned patches (monkeypatch, mock.patch or a fixture that does)"]


def test_an_old_test_given_another_patch_is_refused(tmp_path):
    root = _pr(tmp_path, {"tests/test_old.py": OLD_FILE.replace(
        '    assert calc.spot({}) == 1', '    monkeypatch.setattr(calc, "bid", lambda row: 2)\n    assert calc.spot({}) == 1')})
    assert cnp.violations(root, "main") == [
        "tests/test_old.py::test_old_one patches (monkeypatch, mock.patch or a fixture that does)"]


def test_an_old_test_whose_patch_becomes_another_kind_is_refused(tmp_path):
    root = _pr(tmp_path, {"tests/test_old.py": OLD_FILE.replace(
        'monkeypatch.setattr(calc, "spot", lambda row: 1)', 'monkeypatch.setenv("SPOT", "1")')})
    assert cnp.violations(root, "main") == [
        "tests/test_old.py::test_old_one patches (monkeypatch, mock.patch or a fixture that does)"]


def test_an_old_unpatched_test_given_a_patching_fixture_is_refused(tmp_path):
    root = _pr(tmp_path, {"tests/test_old.py": OLD_FILE.replace("def test_old_two():", "def test_old_two(pinned):")})
    assert cnp.violations(root, "main") == [
        "tests/test_old.py::test_old_two patches (monkeypatch, mock.patch or a fixture that does)"]


def test_an_untouched_old_patching_test_is_allowed_when_its_file_changes_elsewhere(tmp_path):
    root = _pr(tmp_path, {"tests/test_old.py": OLD_FILE.replace('{"last": 2}) == 2', '{"last": 7}) == 7')})
    assert cnp.violations(root, "main") == []


def test_a_test_class_patched_by_its_decorator_is_refused(tmp_path):
    root = _pr(tmp_path, {"tests/test_new.py": (
        "from unittest import mock\n\n\n@mock.patch('calc.spot', return_value=3)\nclass TestSpot:\n"
        "    def test_new(self, spot):\n        assert spot() == 3\n")})
    assert cnp.violations(root, "main") == [
        "tests/test_new.py::TestSpot.test_new patches (monkeypatch, mock.patch or a fixture that does)"]


def test_a_test_class_given_a_patching_fixture_by_usefixtures_is_refused(tmp_path):
    root = _pr(tmp_path, {"tests/test_new.py": (
        "import pytest\n\n\n@pytest.mark.usefixtures('pinned')\nclass TestSpot:\n"
        "    def test_new(self):\n        assert True\n")})
    assert cnp.violations(root, "main") == [
        "tests/test_new.py::TestSpot.test_new patches (monkeypatch, mock.patch or a fixture that does)"]


def test_a_patch_added_outside_the_functions_is_refused(tmp_path):
    """No test's code changes, yet every test in the file now runs under the patch."""
    root = _pr(tmp_path, {"tests/test_old.py": OLD_FILE.replace(
        "import calc\n", "from unittest import mock\n\nimport calc\n\nmock.patch('calc.spot', return_value=3).start()\n")})
    assert cnp.violations(root, "main") == [
        "tests/test_old.py patches outside a function (a patch tool, or a pytestmark or test that patches)"]


def test_a_new_test_under_a_pytestmark_using_a_patching_fixture_is_refused(tmp_path):
    root = _pr(tmp_path, {"tests/test_new.py": (
        "import pytest\n\npytestmark = pytest.mark.usefixtures('pinned')\n\n\ndef test_new():\n    assert True\n")})
    assert cnp.violations(root, "main") == [
        "tests/test_new.py patches outside a function (a patch tool, or a pytestmark or test that patches)",
        "tests/test_new.py::test_new runs under the file's patch outside a function"]


def test_a_new_test_under_a_conftest_patching_autouse_fixture_is_refused(tmp_path):
    """The conftest's autouse fixture runs for every test in its directory and those below it."""
    root = _pr(tmp_path, {
        "tests/sub/conftest.py": CONFTEST.replace("@pytest.fixture\ndef pinned", "@pytest.fixture(autouse=True)\ndef held"),
        "tests/sub/deeper/test_new.py": "def test_new():\n    assert True\n",
        "tests/test_beside.py": "def test_beside():\n    assert True\n"})
    assert cnp.violations(root, "main") == [
        "tests/sub/conftest.py::held patches (monkeypatch, mock.patch or a fixture that does)",
        "tests/sub/deeper/test_new.py::test_new runs under tests/sub/conftest.py's patching autouse fixture held"]


def test_a_test_in_a_nested_class_using_monkeypatch_is_refused(tmp_path):
    root = _pr(tmp_path, {"tests/test_new.py": (
        "class TestOuter:\n    class TestInner:\n        def test_new(self, monkeypatch):\n"
        "            monkeypatch.setattr('calc.spot', lambda r: 3)\n")})
    assert cnp.violations(root, "main") == [
        "tests/test_new.py::TestOuter.TestInner.test_new patches (monkeypatch, mock.patch or a fixture that does)"]


def test_a_test_defined_under_an_if_using_monkeypatch_is_refused(tmp_path):
    root = _pr(tmp_path, {"tests/test_new.py": (
        "if True:\n    def test_new(monkeypatch):\n        monkeypatch.setattr('calc.spot', lambda r: 3)\n")})
    assert cnp.violations(root, "main") == [
        "tests/test_new.py patches outside a function (a patch tool, or a pytestmark or test that patches)"]


def test_each_spelling_of_a_patch_is_refused(tmp_path):
    """An alias of unittest.mock's patch, patch.multiple, pytest.MonkeyPatch and getfixturevalue."""
    root = _pr(tmp_path, {"tests/test_new.py": (
        "import pytest\nimport unittest.mock as um\nfrom unittest.mock import patch as p\n\n\n"
        "def test_alias():\n    with p('calc.spot'):\n        pass\n\n\n"
        "def test_multiple():\n    with um.patch.multiple('calc', spot=1):\n        pass\n\n\n"
        "def test_monkeypatch_class():\n    with pytest.MonkeyPatch.context() as m:\n        m.setattr('calc.spot', 1)\n\n\n"
        "def test_fixture_by_name(request):\n    request.getfixturevalue('pinned')\n")})
    assert cnp.violations(root, "main") == [
        f"tests/test_new.py::{t} patches (monkeypatch, mock.patch or a fixture that does)"
        for t in ("test_alias", "test_multiple", "test_monkeypatch_class", "test_fixture_by_name")]


def test_a_monkeypatch_outside_the_functions_is_refused(tmp_path):
    root = _pr(tmp_path, {"tests/test_new.py": (
        "import pytest\n\nimport calc\n\npytest.MonkeyPatch().setattr(calc, 'spot', lambda r: 3)\n\n\n"
        "def test_new():\n    assert calc.spot({}) == 3\n")})
    assert cnp.violations(root, "main") == [
        "tests/test_new.py patches outside a function (a patch tool, or a pytestmark or test that patches)",
        "tests/test_new.py::test_new runs under the file's patch outside a function"]


def test_a_new_test_beside_a_patching_setup_function_is_refused(tmp_path):
    setup = "\n\ndef setup_function(_fn):\n    import unittest.mock\n    unittest.mock.patch('calc.spot').start()\n"
    root = _pr(tmp_path, {"tests/test_old.py": OLD_FILE + setup + "\n\ndef test_beside():\n    assert True\n"},
               base={**BASE, "tests/test_old.py": OLD_FILE + setup})
    assert cnp.violations(root, "main") == [
        "tests/test_old.py::test_beside runs under the file's patching setup_function"]


def test_a_conftest_autouse_fixture_patching_through_another_conftest_is_seen(tmp_path):
    """tests/sub/conftest.py's autouse fixture requests tests/conftest.py's patching `pinned`."""
    base = {**BASE, "tests/sub/conftest.py": (
        "import pytest\n\n\n@pytest.fixture(autouse=True)\ndef held(pinned):\n    yield\n")}
    root = _pr(tmp_path, {"tests/sub/test_new.py": "def test_new():\n    assert True\n"}, base=base)
    assert cnp.violations(root, "main") == [
        "tests/sub/test_new.py::test_new runs under tests/sub/conftest.py's patching autouse fixture held"]


def test_a_file_with_a_patch_outside_its_functions_may_change_elsewhere(tmp_path):
    """Its class docstring and its imports change; its patch and its tests stay as they were."""
    was = ("from unittest import mock\n\nmock.patch('calc.spot', return_value=3).start()\n\n\n"
           "class TestSpot:\n    \"\"\"The spot.\"\"\"\n\n    def test_one(self):\n        assert True\n")
    root = _pr(tmp_path, {"tests/test_held.py": "import calc\n" + was.replace('"""The spot."""', '"""The spot reader."""')},
               base={**BASE, "tests/test_held.py": was})
    assert cnp.violations(root, "main") == []


def test_a_local_name_patch_is_not_a_patch(tmp_path):
    root = _pr(tmp_path, {"tests/test_new.py": (
        "import calc\n\n\ndef test_new():\n    for patch in ({'last': 4},):\n        assert calc.spot(patch) == 4\n")})
    assert cnp.violations(root, "main") == []


def test_a_new_test_that_patches_nothing_is_allowed(tmp_path):
    root = _pr(tmp_path, {"tests/test_new.py": "import calc\n\n\ndef test_new():\n    assert calc.spot({'last': 4}) == 4\n"})
    assert cnp.violations(root, "main") == []
