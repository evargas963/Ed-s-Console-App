"""tools/check_fails_before.py (AGENTS.md Before writing code) on real git repositories: a product change is
proven only by a changed test that fails on the old code."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import check_fails_before as cfb  # noqa: E402
from tests.test_check_end_to_end_v1 import deletions_pr  # noqa: E402

BASE = {"calc.py": "def spot(row):\n    return row['bid']\n",
        "tests/test_calc.py": "from calc import spot\n\n\ndef test_spot_reads_a_row():\n    assert spot({'bid': 1, 'last': 2}) in (1, 2)\n"}
SPEC = "const { test, expect } = require('@playwright/test');\nconst { spot } = require('../../calc.js');\n\n"
JS_BASE = {"calc.js": "exports.spot = (row) => row.bid;\n",
           "playwright.config.mjs": ("import { defineConfig } from '@playwright/test';\n\n"
                                     "export default defineConfig({ testDir: 'tests/e2e' });\n"),
           "tests/e2e/calc.spec.js": SPEC + "test('spot reads a row', () => {\n  expect([1, 2]).toContain(spot({ bid: 1, last: 2 }));\n});\n"}
JS_FIX = "exports.spot = (row) => row.last;\n"


def _git(root: Path, *a: str) -> None:
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)


def _repo(tmp_path: Path, pr: dict[str, str], base: dict[str, str] = BASE) -> Path:
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


@pytest.fixture
def page_repo(tmp_path):
    """A repository of page code and Playwright specs, run with this repository's Playwright."""
    links = []

    def make(pr: dict[str, str]) -> Path:
        root = _repo(tmp_path, pr, JS_BASE)
        link = root / "node_modules"
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(REPO / "node_modules")],
                           check=True, capture_output=True)
        else:
            link.symlink_to(REPO / "node_modules", target_is_directory=True)
        links.append(link)
        return root

    yield make
    for link in links:
        os.rmdir(link) if os.name == "nt" else link.unlink()


def test_a_page_fix_with_a_spec_that_fails_on_the_old_code_is_proven(page_repo, capsys):
    root = page_repo({"calc.js": JS_FIX, "tests/e2e/calc.spec.js": (
        SPEC + "test('spot is the last trade', () => {\n  expect(spot({ bid: 1, last: 2 })).toBe(2);\n});\n")})
    assert cfb.violations(root, "main") == []
    assert capsys.readouterr().out == ("proven: 1 of 1 changed tests fail on the old code: "
                                       "calc.spec.js::spot is the last trade\n")


def test_a_page_fix_whose_spec_already_passed_before_is_refused(page_repo):
    root = page_repo({"calc.js": JS_FIX, "tests/e2e/calc.spec.js": (
        JS_BASE["tests/e2e/calc.spec.js"] + "\ntest('nothing', () => {\n  expect(true).toBe(true);\n});\n")})
    assert cfb.violations(root, "main") == [
        "every changed test passes on the old code (2 run: tests/e2e/calc.spec.js): none of them proves this change"]


def test_a_page_fix_with_no_test_change_is_refused(page_repo):
    root = page_repo({"calc.js": JS_FIX})
    assert cfb.violations(root, "main") == ["product code changed (calc.js) but no test under tests/ changed"]


def test_real_deletions_that_only_delete_tests_have_nothing_to_fail_before(tmp_path, capsys):
    """251b945c's product deletions with its test deletion in test_options_order_flow_semantics_v1.py
    and without its test edit: no product line and no test line added."""
    root = deletions_pr(tmp_path, leave_out="tests/test_liquidity_engine.py")
    assert cfb.violations(root, "main") == []
    assert capsys.readouterr().out == (
        "product code only removed (schwab_client.py, server.py, stream_spine.py) and no test added to or "
        "changed: nothing to fail before; the existing tests its End-to-end test: names are checked by "
        "check_end_to_end.py\n")


def test_real_deletions_that_edit_a_test_keep_the_rule(tmp_path):
    """251b945c's product deletions with its edit of test_liquidity_engine.py (a parameter dropped from a
    helper): the edited test passes on the old code, so the change is refused as before."""
    root = deletions_pr(tmp_path, leave_out="tests/test_options_order_flow_semantics_v1.py")
    assert cfb.violations(root, "main") == [
        "every changed test passes on the old code (19 run: tests/test_liquidity_engine.py): "
        "none of them proves this change"]
