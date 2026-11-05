"""tools/check_integrity.py on throwaway repositories: what a change may not take from its tests.
The inputs are the shapes the check judges, not market data."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools import check_integrity as ci

SURVIVES = "def test_x():\n    assert 1 == 1\n    assert 2 == 2\n"
MARK_SKIP = "@pytest.mark.skip"
SKIP_LINE = "pytest.skip('later')"
DEFERRED = "# TODO: later"
SPEC = "test('a page', async () => {\n  expect(a).toBe(1);\n  expect(b).toBe(2);\n});\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _commit(repo: Path) -> None:
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x", "--no-verify")


def _write(repo: Path, name: str, text: str) -> None:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _write(root, "tests/test_a.py", SURVIVES)
    _write(root, "tests/test_gone.py", "def test_gone():\n    assert 3 == 3\n")
    _write(root, "tests/e2e/page.spec.js", SPEC)
    _write(root, "product.py", "VALUE = 1\n")
    _write(root, "AGENTS.md", "# rules\n")
    _commit(root)
    _git(root, "checkout", "-q", "-b", "change")
    return root


def _found(repo: Path) -> list[str]:
    _commit(repo)
    return ci.violations(repo, "main")


def test_code_deleted_with_its_tests_passes(repo):
    (repo / "tests/test_gone.py").unlink()
    _write(repo, "product.py", "")
    assert _found(repo) == []


def test_an_assertion_gone_with_the_function_it_names_passes(repo):
    _write(repo, "product.py", "def old():\n    return 1\n")
    _write(repo, "tests/test_a.py", SURVIVES + "    assert product.old() == 1\n")
    _commit(repo)
    _git(repo, "branch", "-f", "main")
    _write(repo, "product.py", "VALUE = 1\n")
    _write(repo, "tests/test_a.py", SURVIVES)
    assert _found(repo) == []


def test_an_assertion_lost_while_the_function_it_names_lives_is_refused(repo):
    _write(repo, "product.py", "def old():\n    return 1\n")
    _write(repo, "tests/test_a.py", SURVIVES + "    assert product.old() == 1\n")
    _commit(repo)
    _git(repo, "branch", "-f", "main")
    _write(repo, "product.py", "def old():\n    return 2\n")
    _write(repo, "tests/test_a.py", SURVIVES)
    assert _found(repo) == ["test_x: assertion lost: product.old() == 1"]


def test_an_assertion_taken_from_a_surviving_test_is_refused(repo):
    _write(repo, "tests/test_a.py", "def test_x():\n    assert 1 == 1\n")
    assert _found(repo) == ["test_x: assertion lost: 2 == 2"]


def test_an_expect_taken_from_a_surviving_spec_test_is_refused(repo):
    _write(repo, "tests/e2e/page.spec.js", SPEC.replace("  expect(b).toBe(2);\n", ""))
    assert _found(repo) == ["a page: assertion lost: expect(b).toBe(2);"]


def test_a_test_moved_to_another_file_with_its_assertions_passes(repo):
    (repo / "tests/test_a.py").unlink()
    _write(repo, "tests/test_b.py", SURVIVES)
    assert _found(repo) == []


def test_a_test_deleted_beside_a_new_one_sharing_a_line_is_not_judged(repo):
    """One shared assertion does not make a new test the old one renamed, so a deletion beside a
    new test passes."""
    _write(repo, "tests/test_gone.py", "def test_gone():\n    assert 3 == 3\n    assert 4 == 4\n")
    _commit(repo)
    _git(repo, "branch", "-f", "main")
    (repo / "tests/test_gone.py").unlink()
    _write(repo, "tests/test_new.py", "def test_new():\n    assert 3 == 3\n")
    assert _found(repo) == []


def test_the_same_test_body_calling_different_code_is_no_duplicate(repo):
    body = "def test_help():\n    assert main(['--help']) == 0\n"
    _write(repo, "tests/test_p.py", "from tools.a import main\n\n\n" + body)
    _write(repo, "tests/test_q.py", "from tools.b import main\n\n\n" + body)
    assert _found(repo) == []


def test_the_same_test_body_on_different_data_is_no_duplicate(repo):
    body = "def test_rows():\n    assert len(DATA) > 0\n"
    _write(repo, "tests/test_p.py", "DATA = load('a.json')\n\n\n" + body)
    _write(repo, "tests/test_q.py", "DATA = load('b.json')\n\n\n" + body)
    fixture = "@pytest.fixture\ndef rows():\n    return load('{}')\n\n\n"
    test = "def test_some(rows):\n    assert rows\n"
    _write(repo, "tests/test_r.py", fixture.format("a.json") + test)
    _write(repo, "tests/test_s.py", fixture.format("b.json") + test)
    assert _found(repo) == []


def test_two_files_alike_but_for_their_docstring_are_duplicates(repo):
    body = "def test_rows():\n    assert len(DATA) > 0\n"
    _write(repo, "tests/test_p.py", '"""One."""\nDATA = load("a.json")\n\n\n' + body)
    _write(repo, "tests/test_q.py", '"""Two."""\nDATA = load("a.json")\n\n\n' + body)
    assert _found(repo) == [
        "a test duplicated: tests/test_p.py::test_rows, tests/test_q.py::test_rows"
    ]


def test_a_test_renamed_with_its_assertions_passes(repo):
    _write(repo, "tests/test_a.py", SURVIVES.replace("test_x", "test_y"))
    assert _found(repo) == []


def test_a_test_that_is_another_test_again_is_refused(repo):
    _write(repo, "tests/test_b.py", SURVIVES.replace("test_x", "test_again"))
    assert _found(repo) == [
        "a test duplicated: tests/test_a.py::test_x, tests/test_b.py::test_again"
    ]


def test_a_test_rewritten_with_its_assertions_restated_passes(repo):
    rewritten = "def test_x():\n    one = 1\n    assert 2  ==  2\n    assert (1 == 1)\n"
    _write(repo, "tests/test_a.py", rewritten + "    assert one\n")
    assert _found(repo) == []


def test_an_assertion_corrected_one_for_one_passes(repo):
    _write(repo, "tests/test_a.py", "def test_x():\n    assert 1 == 1\n    assert 2 == 3\n")
    assert _found(repo) == []


def test_a_binary_file_is_read_past(repo):
    (repo / "picture.png").write_bytes(b"\x89PNG\xff\xfe\x00\xd8")
    assert _found(repo) == []


def test_a_marker_in_a_file_with_a_space_in_its_name_is_read(repo):
    _write(repo, "a page.js", f"{DEFERRED}\n")
    found = _found(repo)
    assert len(found) == 1 and "marker added" in found[0]


@pytest.mark.parametrize("line", [MARK_SKIP, SKIP_LINE, DEFERRED, "pytest.mark.xfail"])
def test_an_added_skip_or_deferred_work_marker_is_refused(repo, line):
    _write(repo, "page.js", f"{line}\n")
    found = _found(repo)
    assert len(found) == 1 and "marker added" in found[0]


def test_a_diff_line_that_reads_like_a_header_does_not_hide_a_marker(repo):
    _write(repo, "page.js", f"++ x\n{DEFERRED}\n")
    found = _found(repo)
    assert len(found) == 1 and found[0].startswith("page.js:")


def test_a_marker_after_a_bare_carriage_return_is_read(repo):
    (repo / "page.js").write_bytes(b"var a = 1;\rtest.skip('x', run);\n")
    found = _found(repo)
    assert len(found) == 1 and "marker added" in found[0]


def test_a_marker_in_a_document_is_not_code(repo):
    _write(repo, "notes.md", f"{DEFERRED}\n")
    assert _found(repo) == []


def test_a_rules_change_passes(repo):
    _write(repo, "AGENTS.md", "# rules, changed\n")
    assert _found(repo) == []


def test_a_product_change_needs_no_record(repo):
    _write(repo, "product.py", "VALUE = 2\n")
    assert _found(repo) == []


def test_a_broken_test_file_is_the_checks_failure_not_a_pass(repo):
    _write(repo, "tests/test_a.py", "def test_x(:\n")
    _commit(repo)
    run = subprocess.run(
        [sys.executable, ci.__file__, "--base", "main"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 2 and "tests/test_a.py" in run.stderr
