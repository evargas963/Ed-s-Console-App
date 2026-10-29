"""tools/check_no_new_patches.py (TEST-PATCHES) on real git repositories, each PR's suite run by
pytest with tools/patch_record.py: a test whose code a pull request adds or changes may not run with
a patch applied, and no unit it adds or changes may apply one; one whose docstrings and comments
alone change, or that the PR leaves as it was, is not judged."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import check_no_new_patches as cnp  # noqa: E402

OLD_FILE = ('import calc\n\n\n'
            'def test_old_one(monkeypatch):\n    monkeypatch.setattr(calc, "spot", lambda row: 1)\n    assert calc.spot({}) == 1\n\n\n'
            'def test_old_two():\n    assert calc.spot({"last": 2}) == 2\n')
CONFTEST = ('import pytest\n\n\n'
            '@pytest.fixture\ndef pinned(monkeypatch):\n    monkeypatch.setattr("time.time", lambda: 1.0)\n')
BASE = {"calc.py": "def spot(row):\n    return row['last']\n", "tests/test_old.py": OLD_FILE,
        "tests/conftest.py": CONFTEST}
RAN = cnp.PATCHED


def _git(root: Path, *a: str) -> None:
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)


def _line(text: str, needle: str) -> int:
    return text[:text.index(needle)].count("\n") + 1


def _check(tmp_path: Path, files: dict[str, str | None], base: dict[str, str] = BASE, encoding: str = "utf-8") -> list[str]:
    """The check's verdict on a PR of `files` (None deletes one; written in `encoding`) over `base`,
    after the PR's suite ran with the recorder."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    for commit in (base, files):
        for name, text in commit.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            if text is None:
                (root / name).unlink()
            else:
                (root / name).write_text(text, encoding="utf-8" if commit is base else encoding)
        _git(root, "add", *commit)
        _git(root, "commit", "-q", "-m", "pr" if commit is files else "base")
        if commit is base:
            _git(root, "checkout", "-q", "-b", "pr")
    record = tmp_path / "record"
    env = {**os.environ, "ED_PATCH_RECORD": str(record), "PYTHONPATH": os.pathsep.join([str(root), str(REPO)])}
    subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist",
                    "-p", "tools.patch_record", "--rootdir", str(root), "tests"], cwd=root, env=env, capture_output=True)
    return cnp.violations(root, "main", record)


def test_a_new_test_using_monkeypatch_is_refused(tmp_path):
    new = "import calc\n\n\ndef test_new(monkeypatch):\n    monkeypatch.setattr(calc, 'spot', lambda r: 3)\n"
    assert _check(tmp_path, {"tests/test_new.py": new}) == [
        f"tests/test_new.py::test_new patches: {RAN}, line {_line(new, 'monkeypatch.setattr')} applies one"]


def test_a_test_in_a_nested_class_patched_by_its_class_decorator_is_refused(tmp_path):
    new = ("from unittest import mock\n\n\nclass TestOuter:\n    @mock.patch('calc.spot', return_value=3)\n"
           "    class TestInner:\n        def test_new(self, spot):\n            assert spot() == 3\n")
    assert _check(tmp_path, {"tests/test_new.py": new}) == [
        f"tests/test_new.py::TestOuter.TestInner.test_new patches: {RAN}, line {_line(new, 'def test_new')} applies one"]


def test_an_aliased_patch_dict_is_refused(tmp_path):
    new = "from unittest.mock import patch as p\n\n\ndef test_new():\n    with p.dict('os.environ', {'X': '1'}):\n        pass\n"
    assert _check(tmp_path, {"tests/test_new.py": new}) == [
        f"tests/test_new.py::test_new patches: {RAN}, line {_line(new, 'with p.dict')} applies one"]


def test_a_new_test_under_an_if_beside_a_patching_autouse_fixture_is_refused(tmp_path):
    was = ("import pytest\n\n\n@pytest.fixture(autouse=True)\ndef _pin(monkeypatch):\n    monkeypatch.setenv('X', '1')\n\n\n"
           "def test_one():\n    assert True\n")
    assert _check(tmp_path, {"tests/test_pin.py": was + "\n\nif True:\n    def test_new():\n        assert True\n"},
                  base={**BASE, "tests/test_pin.py": was}) == [f"tests/test_pin.py::test_new patches: {RAN}"]


def test_a_new_test_under_a_conftest_fixture_patching_through_another_conftest_is_refused(tmp_path):
    base = {**BASE, "tests/sub/conftest.py": "import pytest\n\n\n@pytest.fixture(autouse=True)\ndef held(pinned):\n    yield\n"}
    assert _check(tmp_path, {"tests/sub/test_new.py": "def test_new():\n    assert True\n"}, base=base) == [
        f"tests/sub/test_new.py::test_new patches: {RAN}"]


def test_a_new_test_calling_a_patching_helper_by_attribute_is_refused(tmp_path):
    was = ("import pytest\n\n\nclass TestHeld:\n    def _pin(self):\n        self.mp = pytest.MonkeyPatch()\n"
           "        self.mp.setenv('X', '1')\n\n    def teardown_method(self):\n        self.mp.undo()\n\n"
           "    def test_one(self):\n        self._pin()\n")
    now = was + "\n    def test_two(self):\n        self._pin()\n"
    assert _check(tmp_path, {"tests/test_held.py": now}, base={**BASE, "tests/test_held.py": was}) == [
        f"tests/test_held.py::TestHeld.test_two patches: {RAN}, line {now.count(chr(10))} applies one"]


def test_a_new_test_beside_a_patching_setup_function_is_refused(tmp_path):
    was = OLD_FILE + "\n\ndef setup_function(_fn):\n    import os\n    import pytest\n    pytest.MonkeyPatch().setenv('X', '1')\n"
    assert _check(tmp_path, {"tests/test_old.py": was + "\n\ndef test_beside():\n    assert True\n"},
                  base={**BASE, "tests/test_old.py": was}) == [f"tests/test_old.py::test_beside patches: {RAN}"]


def test_a_patch_added_outside_the_functions_is_refused(tmp_path):
    """No test's code changes, yet every test in the file now runs under the patch."""
    now = OLD_FILE.replace("import calc\n", "import pytest\n\nimport calc\n\npytest.MonkeyPatch().setenv('X', '1')\n")
    line = _line(now, "pytest.MonkeyPatch()")
    assert _check(tmp_path, {"tests/test_old.py": now}) == [f"tests/test_old.py::line {line} patches: line {line} applies one"]


def test_a_fixture_changed_to_patch_is_refused_though_its_tests_are_unchanged(tmp_path):
    plain = "\n\n@pytest.fixture\ndef plain():\n    return 1\n"
    base = {**BASE, "tests/conftest.py": CONFTEST + plain, "tests/test_plain.py": "def test_plain(plain):\n    assert plain == 1\n"}
    now = CONFTEST + plain.replace("def plain():\n", "def plain(monkeypatch):\n    monkeypatch.setenv('X', '1')\n")
    assert _check(tmp_path, {"tests/conftest.py": now}, base=base) == [
        f"tests/conftest.py::plain patches: line {_line(now, 'monkeypatch.setenv')} applies one"]


def test_an_old_patching_test_whose_docstring_and_comments_alone_change_passes(tmp_path):
    """A patching test may change in its docstrings and comments; its code may not."""
    assert _check(tmp_path, {"tests/test_old.py": OLD_FILE.replace(
        "def test_old_one(monkeypatch):\n", 'def test_old_one(monkeypatch):\n    """The spot reader."""\n').replace(
        "    assert calc.spot({}) == 1", "    assert calc.spot({}) == 1  # the patched value")}) == []


def test_an_old_patching_test_whose_code_changes_is_refused(tmp_path):
    now = OLD_FILE.replace("lambda row: 1)\n    assert calc.spot({}) == 1", "lambda row: 5)\n    assert calc.spot({}) == 5")
    assert _check(tmp_path, {"tests/test_old.py": now}) == [
        f"tests/test_old.py::test_old_one patches: {RAN}, line {_line(now, 'monkeypatch.setattr')} applies one"]


def test_an_untouched_old_patching_test_is_allowed_when_its_file_changes_elsewhere(tmp_path):
    assert _check(tmp_path, {"tests/test_old.py": OLD_FILE.replace('{"last": 2}) == 2', '{"last": 7}) == 7')}) == []


def test_names_that_only_look_like_patches_are_not_patches(tmp_path):
    """A client's `patch` method, a local named `patch`, and a fixture fetched by name that patches nothing."""
    new = ("class Client:\n    def patch(self, url):\n        return url\n\n\n"
           "def test_new(request):\n    request.getfixturevalue('tmp_path')\n    patch = Client().patch('/x')\n    assert patch == '/x'\n")
    assert _check(tmp_path, {"tests/test_new.py": new}) == []


def test_a_patch_dict_decorator_under_a_patch_decorator_is_refused(tmp_path):
    new = ("import os\nfrom unittest import mock\n\n\n@mock.patch('calc.spot', return_value=3)\n"
           "@mock.patch.dict(os.environ, {'X': '1'})\ndef test_new(spot):\n    assert os.environ['X'] == '1'\n")
    assert _check(tmp_path, {"tests/test_new.py": new}) == [
        f"tests/test_new.py::test_new patches: {RAN}, line {_line(new, '@mock.patch(')} applies one"]


def test_a_patch_applied_when_the_conftest_is_imported_is_refused(tmp_path):
    now = CONFTEST.replace("import pytest\n", "import pytest\nfrom unittest import mock\n\nmock.patch('time.time', lambda: 1.0).start()\n")
    line = _line(now, "mock.patch(")
    assert _check(tmp_path, {"tests/conftest.py": now}) == [f"tests/conftest.py::line {line} patches: line {line} applies one"]


def test_a_new_test_that_did_not_run_is_refused(tmp_path):
    """Skipped here, it would patch where it runs; what it runs under is unknown."""
    new = "import pytest\n\n\n@pytest.mark.skipif(True, reason='elsewhere')\ndef test_new(monkeypatch):\n    monkeypatch.setenv('X', '1')\n"
    assert _check(tmp_path, {"tests/test_new.py": new}) == [f"tests/test_new.py::test_new patches: {cnp.UNRUN}"]


def test_a_new_test_fetching_a_patching_fixture_by_name_is_refused(tmp_path):
    new = "def test_new(request):\n    request.getfixturevalue('pinned')\n"
    assert _check(tmp_path, {"tests/test_new.py": new}) == [
        f"tests/test_new.py::test_new patches: {RAN}, line 2 applies one"]


def test_a_renamed_file_keeps_its_old_patching_test_unjudged(tmp_path):
    assert _check(tmp_path, {"tests/test_moved.py": OLD_FILE, "tests/test_old.py": None}) == []


def test_an_unchanged_patching_function_in_a_changed_block_is_not_judged(tmp_path):
    was = "import os\n\nif True:\n    def test_one(monkeypatch):\n        monkeypatch.setenv('X', '1')\n"
    assert _check(tmp_path, {"tests/test_block.py": was + "\n    def test_two():\n        assert True\n"},
                  base={**BASE, "tests/test_block.py": was}) == []


def test_a_patch_applied_when_another_file_is_imported_judges_a_new_test(tmp_path):
    """Every worker imports every test file before any test runs, so the patch reaches every test."""
    base = {**BASE, "tests/test_a_leak.py": "import pytest\n\npytest.MonkeyPatch().setenv('X', '1')\n\n\ndef test_a():\n    assert True\n"}
    assert _check(tmp_path, {"tests/test_new.py": "def test_new():\n    assert True\n"}, base=base) == [
        f"tests/test_new.py::test_new patches: {RAN}"]


def test_a_patch_another_files_test_left_applied_does_not_judge_a_new_test(tmp_path):
    """It reaches a test only by the order a worker runs files in; it is judged where it was applied."""
    base = {**BASE, "tests/test_a_leak.py": "import pytest\n\n\ndef test_a():\n    pytest.MonkeyPatch().setenv('X', '1')\n"}
    assert _check(tmp_path, {"tests/test_new.py": "def test_new():\n    assert True\n"}, base=base) == []


def test_a_new_test_under_a_module_scoped_fixture_from_a_helper_is_refused(tmp_path):
    """The fixture applies its patch for the first test only; every test requesting it runs under it."""
    helper = ("import pytest\n\n\n@pytest.fixture(scope='module')\ndef held():\n    mp = pytest.MonkeyPatch()\n"
              "    mp.setenv('X', '1')\n    yield\n    mp.undo()\n")
    was = "from helpers_fx import held  # noqa: F401\n\n\ndef test_a(held):\n    assert True\n"
    base = {**BASE, "tests/helpers_fx.py": helper, "tests/test_h.py": was}
    assert _check(tmp_path, {"tests/test_h.py": was + "\n\ndef test_b(held):\n    assert True\n"}, base=base) == [
        f"tests/test_h.py::test_b patches: {RAN}"]


def test_a_new_test_in_a_file_skipped_at_collection_is_refused(tmp_path):
    new = "import pytest\n\npytest.importorskip('no_such_module')\n\n\ndef test_new(monkeypatch):\n    monkeypatch.setenv('X', '1')\n"
    assert _check(tmp_path, {"tests/test_new.py": new}) == [f"tests/test_new.py::test_new patches: {cnp.UNRUN}"]


def test_a_new_test_that_skips_partway_is_refused(tmp_path):
    """The code after its skip never ran here; what it runs under is unknown."""
    new = "import pytest\n\n\ndef test_new(monkeypatch):\n    pytest.skip('elsewhere')\n    monkeypatch.setenv('X', '1')\n"
    assert _check(tmp_path, {"tests/test_new.py": new}) == [f"tests/test_new.py::test_new patches: {cnp.UNRUN}"]


def test_a_new_unittest_test_that_skips_partway_is_refused(tmp_path):
    """pytest reports a unittest skipTest() after the call returns, not as an exception from it."""
    new = ("import os\nimport unittest\n\n\nclass Spot(unittest.TestCase):\n    def test_new(self):\n"
           "        self.skipTest('elsewhere')\n        os.environ['X'] = '1'\n")
    assert _check(tmp_path, {"tests/test_new.py": new}) == [f"tests/test_new.py::Spot.test_new patches: {cnp.UNRUN}"]


def test_a_new_test_in_a_file_pytest_ignores_is_refused(tmp_path):
    files = {"tests/conftest.py": CONFTEST + "\ncollect_ignore = ['test_new.py']\n",
             "tests/test_new.py": "def test_new(monkeypatch):\n    monkeypatch.setenv('X', '1')\n"}
    assert _check(tmp_path, files) == [f"tests/test_new.py::test_new patches: {cnp.UNRUN}"]


def test_a_new_test_in_a_package_that_skips_is_refused(tmp_path):
    files = {"tests/sub/__init__.py": "import pytest\n\npytest.importorskip('no_such_module')\n",
             "tests/sub/test_new.py": "def test_new(monkeypatch):\n    monkeypatch.setenv('X', '1')\n"}
    assert _check(tmp_path, files) == [f"tests/sub/test_new.py::test_new patches: {cnp.UNRUN}"]


def test_an_inherited_test_is_judged_as_the_code_that_defines_it(tmp_path):
    """TestHeld runs test_x, defined in _Base, under its patching autouse fixture."""
    was = ("import pytest\n\n\nclass _Base:\n    def test_x(self):\n        assert True\n\n\n"
           "class TestHeld(_Base):\n    @pytest.fixture(autouse=True)\n    def _pin(self, monkeypatch):\n"
           "        monkeypatch.setenv('X', '1')\n")
    now = was.replace("        assert True\n", "        assert 1 == 1\n")
    assert _check(tmp_path, {"tests/test_held.py": now}, base={**BASE, "tests/test_held.py": was}) == [
        f"tests/test_held.py::_Base.test_x patches: {RAN}"]


def test_a_new_test_under_a_decorator_that_does_not_wrap_is_refused(tmp_path):
    was = ("from unittest import mock\n\n\ndef pinned(f):\n    def wrapper(*a, **k):\n"
           "        with mock.patch('calc.spot', return_value=3):\n            return f(*a, **k)\n    return wrapper\n\n\n"
           "@pinned\ndef test_old():\n    pass\n")
    assert _check(tmp_path, {"tests/test_deco.py": was + "\n\n@pinned\ndef test_new():\n    pass\n"},
                  base={**BASE, "tests/test_deco.py": was}) == [f"tests/test_deco.py::test_new patches: {RAN}"]


def test_a_new_test_made_inside_a_function_is_judged_as_that_function(tmp_path):
    was = ("import pytest\n\n\n@pytest.fixture(autouse=True)\ndef _pin(monkeypatch):\n    monkeypatch.setenv('X', '1')\n\n\n"
           "def make():\n    def test_x():\n        assert True\n    return test_x\n\n\ntest_made = make()\n")
    now = was.replace("        assert True\n", "        assert 1 == 1\n")
    assert _check(tmp_path, {"tests/test_made.py": now}, base={**BASE, "tests/test_made.py": was}) == [
        f"tests/test_made.py::make patches: {RAN}"]


def test_an_old_patching_test_bound_under_a_new_name_is_refused(tmp_path):
    now = OLD_FILE + "\n\ntest_again = test_old_one\n"
    assert _check(tmp_path, {"tests/test_old.py": now}) == [
        f"tests/test_old.py::line {_line(now, 'test_again =')} patches: {RAN}"]


def test_a_changed_fixture_named_like_a_test_is_not_taken_for_one(tmp_path):
    """pytest collects no fixture, so one named test_* is judged only by the patches it applies."""
    new = "import pytest\n\n\n@pytest.fixture\ndef test_data():\n    return 1\n\n\ndef test_new(test_data):\n    assert test_data == 1\n"
    assert _check(tmp_path, {"tests/test_new.py": new}) == []


def test_a_new_test_marked_not_to_run_is_refused(tmp_path):
    new = "import pytest\n\n\n@pytest.mark.xfail(run=False)\ndef test_new(monkeypatch):\n    monkeypatch.setenv('X', '1')\n"
    assert _check(tmp_path, {"tests/test_new.py": new}) == [f"tests/test_new.py::test_new patches: {cnp.UNRUN}"]


def test_a_test_file_in_another_encoding_is_judged(tmp_path):
    root_files = {"tests/test_new.py": "# -*- coding: latin-1 -*-\ndef test_new(monkeypatch):\n    monkeypatch.setenv('X', '\xe9')\n"}
    assert _check(tmp_path, root_files, encoding="latin-1") == [
        f"tests/test_new.py::test_new patches: {RAN}, line 3 applies one"]


def test_a_patch_left_applied_by_its_own_file_judges_a_new_test(tmp_path):
    was = "import pytest\n\npytest.MonkeyPatch().setenv('X', '1')\n\n\ndef test_a():\n    assert True\n"
    assert _check(tmp_path, {"tests/test_held.py": was + "\n\ndef test_new():\n    assert True\n"},
                  base={**BASE, "tests/test_held.py": was}) == [f"tests/test_held.py::test_new patches: {RAN}"]


def test_a_new_test_that_patches_nothing_is_allowed(tmp_path):
    assert _check(tmp_path, {"tests/test_new.py": "import calc\n\n\ndef test_new():\n    assert calc.spot({'last': 4}) == 4\n"}) == []


def test_a_pytest_that_a_test_starts_does_not_write_to_the_record(tmp_path):
    """The recorder's folder is not in a running test's environment, so a pytest it starts (the
    full-suite runner's own test does) cannot clear or add to the run's record."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_env.py").write_text(
        "import os\n\n\ndef test_env(tmp_path_factory):\n"
        "    open(os.environ['SEEN'], 'w').write(repr(os.environ.get('ED_PATCH_RECORD')))\n", encoding="utf-8")
    seen = tmp_path / "seen.txt"
    env = {**os.environ, "ED_PATCH_RECORD": str(tmp_path / "record"), "SEEN": str(seen), "PYTHONPATH": str(REPO)}
    subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", "-p", "tools.patch_record",
                    "--rootdir", str(tmp_path), "tests"], cwd=tmp_path, env=env, capture_output=True)
    assert seen.read_text(encoding="utf-8") == "None"


def test_no_record_of_the_run_fails_the_check(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    with pytest.raises(cnp.ToolError, match="no patch record"):
        cnp.violations(root, "main", tmp_path / "never-recorded")
