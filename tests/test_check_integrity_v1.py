"""tools/check_integrity.py on throwaway repositories: what a change may not take from its tests,
and the review record it must carry. The inputs are the shapes the check judges, not market data."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools import check_integrity as ci

HEAD = "a" * 40
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
    _write(root, "tests/test_gone.py", SURVIVES.replace("test_x", "test_gone"))
    _write(root, "tests/e2e/page.spec.js", SPEC)
    _write(root, "product.py", "VALUE = 1\n")
    _write(root, "AGENTS.md", "# rules\n")
    _commit(root)
    _git(root, "checkout", "-q", "-b", "change")
    return root


def _found(repo: Path, body: str = "") -> list[str]:
    _commit(repo)
    return ci.violations(repo, "main", body, HEAD)


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


def test_a_test_rewritten_with_its_assertions_restated_passes(repo):
    rewritten = "def test_x():\n    one = 1\n    assert 2  ==  2\n    assert (1 == 1)\n"
    _write(repo, "tests/test_a.py", rewritten + "    assert one\n")
    assert _found(repo) == []


def test_an_assertion_corrected_one_for_one_passes(repo):
    _write(repo, "tests/test_a.py", "def test_x():\n    assert 1 == 1\n    assert 2 == 3\n")
    assert _found(repo) == []


def test_a_template_left_unfilled_is_no_record(repo):
    _write(repo, "product.py", "VALUE = 2\n")
    assert _found(repo, "## Review\n<!-- how:\nCommit: <head>\nVerdict: PASS or FAIL\n-->\n") == []


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


def test_two_verdicts_are_both_read(repo):
    _write(repo, "AGENTS.md", "# rules, changed\n")
    record = f"## Review\nCommit: {HEAD}\nVerdict: PASS\nVerdict: FAIL\nEvidence: read.\n"
    assert _found(repo, record) == ["the ## Review record's Verdict is not PASS"]


def test_a_marker_after_a_bare_carriage_return_is_read(repo):
    (repo / "page.js").write_bytes(b"var a = 1;\rtest.skip('x', run);\n")
    found = _found(repo)
    assert len(found) == 1 and "marker added" in found[0]


@pytest.mark.parametrize(
    "record", ["Verdict: FAIL, a guard at x", "**Verdict:** FAIL", "verdict - FAIL"]
)
def test_a_fail_in_another_shape_is_read(repo, record):
    _write(repo, "product.py", "VALUE = 2\n")
    found = _found(repo, f"## Review\nCommit: {HEAD}\n{record}\nEvidence: read.\n")
    assert found == ["the ## Review record's Verdict is not PASS"]


def test_a_record_with_no_evidence_is_refused(repo):
    _write(repo, "AGENTS.md", "# rules, changed\n")
    found = _found(repo, f"## Review\nCommit: {HEAD}\nVerdict: PASS\nEvidence:\n")
    assert found == ["the ## Review record gives no Evidence"]


def test_a_marker_in_a_document_is_not_code(repo):
    _write(repo, "notes.md", f"{DEFERRED}\n")
    assert _found(repo) == []


def test_a_rules_change_with_no_review_record_is_refused(repo):
    _write(repo, "AGENTS.md", "# rules, changed\n")
    assert _found(repo) == ["no ## Review record, and the change touches AGENTS.md"]


def test_a_rules_change_with_a_passing_record_of_the_head_passes(repo):
    _write(repo, "AGENTS.md", "# rules, changed\n")
    assert _found(repo, f"## Review\nCommit: {HEAD}\nVerdict: PASS\nEvidence: read.\n") == []


def test_a_record_of_an_older_commit_is_refused(repo):
    _write(repo, "AGENTS.md", "# rules, changed\n")
    found = _found(repo, f"## Review\nCommit: {'b' * 40}\nVerdict: PASS\nEvidence: read.\n")
    assert found == [f"the ## Review record does not name the head {HEAD}"]


def test_a_fail_verdict_is_refused_whatever_the_change_touches(repo):
    _write(repo, "product.py", "VALUE = 2\n")
    found = _found(repo, f"## Review\nCommit: {HEAD}\nVerdict: FAIL\nEvidence: a guard.\n")
    assert found == ["the ## Review record's Verdict is not PASS"]


def test_a_product_change_needs_no_record(repo):
    _write(repo, "product.py", "VALUE = 2\n")
    assert _found(repo) == []


@pytest.mark.parametrize(
    "path",
    [
        "AGENTS.md",
        "docs/DATA_FLOW.md",
        "ACTIVE_PROGRAM.md",
        "locks.ruff.toml",
        ".github/workflows/locks.yml",
        ".claude/settings.json",
        ".cursor/hooks.json",
        "tools/hook_chain.py",
        "tools/check_locks.py",
        "tools/after_deploy_check.py",
        "tests/test_governing_docs_v1.py",
        "tests/test_test_rules_v1.py",
        "tests/test_hook_chain_v1.py",
    ],
)
def test_what_governs_a_change_is_named(path):
    assert ci.GOVERNING.match(path)


def test_a_broken_test_file_is_the_checks_failure_not_a_pass(repo):
    _write(repo, "tests/test_a.py", "def test_x(:\n")
    _commit(repo)
    body = repo / "body.md"
    body.write_text("", encoding="utf-8")
    run = subprocess.run(
        [sys.executable, ci.__file__, "--base", "main", "--body-file", body, "--head-sha", HEAD],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 2 and "tests/test_a.py" in run.stderr
