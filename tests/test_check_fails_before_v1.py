"""tools/check_fails_before.py (AGENTS.md rule 1, Before writing code) on real git repositories: a product
change is proven only by a changed end-to-end path test that fails on the old code."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import check_fails_before as cfb  # noqa: E402

BASE = {"calc.py": "def spot(row):\n    return row['bid']\n",
        "tests/test_data_path_calc.py": "from calc import spot\n\n\ndef test_spot_reads_a_row():\n    assert spot({'bid': 1, 'last': 2}) in (1, 2)\n"}
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
    root = _repo(tmp_path, {"calc.py": FIX, "tests/test_data_path_calc.py": (
        "from calc import spot\n\n\ndef test_spot_is_the_last_trade():\n    assert spot({'bid': 1, 'last': 2}) == 2\n")})
    assert cfb.violations(root, "main") == []


def test_a_fix_whose_test_already_passed_before_is_refused(tmp_path):
    root = _repo(tmp_path, {"calc.py": FIX, "tests/test_data_path_calc.py": (
        "from calc import spot\n\n\ndef test_spot_reads_a_row():\n    assert spot({'bid': 1, 'last': 2}) in (1, 2)\n\n"
        "def test_nothing():\n    assert True\n")})
    found = cfb.violations(root, "main")
    assert len(found) == 1 and found[0].startswith("every changed test passes on the old code (2 run")


def test_a_fix_with_no_test_change_is_refused(tmp_path):
    root = _repo(tmp_path, {"calc.py": FIX})
    assert cfb.violations(root, "main") == ["product code changed (calc.py) but no end-to-end path test (tests/test_data_path_*.py or tests/e2e/*.spec.js) changed"]


def test_a_fix_proven_only_by_a_test_that_is_not_an_end_to_end_path_test_is_refused(tmp_path):
    """AGENTS.md rule 1: every fix is end to end. A unit test that fails on the old code does not prove it."""
    root = _repo(tmp_path, {"calc.py": FIX, "tests/test_calc_unit.py": (
        "from calc import spot\n\n\ndef test_spot_is_the_last_trade():\n    assert spot({'bid': 1, 'last': 2}) == 2\n")})
    assert cfb.violations(root, "main") == ["product code changed (calc.py) but no end-to-end path test (tests/test_data_path_*.py or tests/e2e/*.spec.js) changed"]


def test_a_test_of_new_code_that_cannot_import_on_the_old_code_counts_as_failing_before(tmp_path):
    root = _repo(tmp_path, {"calc.py": FIX + "\n\ndef mid(row):\n    return (row['bid'] + row['ask']) / 2\n",
                            "tests/test_data_path_mid.py": "from calc import mid\n\n\ndef test_mid():\n    assert mid({'bid': 1, 'ask': 3}) == 2\n"})
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
    assert cfb.violations(root, "main") == ["product code changed (calc.js) but no end-to-end path test (tests/test_data_path_*.py or tests/e2e/*.spec.js) changed"]


# The code before and after a cleanup that only rewrites comments and docstrings: the same code, so
# nothing for a test to fail on.
NOTED = {"calc.py": ('"""Spot, from the row (RC-12, 2026-09-01)."""\n\n\n'
                     "def spot(row):\n    \"\"\"The bid (used to be the mark).\"\"\"\n"
                     "    return row['bid']  # audit 2026-09-02\n"),
         "page.js": "// RC-9 2026-09-01: drawn here\nvar url = 'http://x/*y*/';  /* was a fallback */\nvar re = /\\/\\//;\n"}
CLEANED = {"calc.py": ('"""Spot, from the row."""\n\n\n'
                       "def spot(row):\n    \"\"\"The bid.\"\"\"\n"
                       "    return row['bid']\n"),
           "page.js": "// drawn here\nvar url = 'http://x/*y*/';\nvar re = /\\/\\//;\n"}


def test_a_change_to_comments_and_docstrings_only_needs_no_test(tmp_path):
    root = _repo(tmp_path, CLEANED, base={**BASE, **NOTED})
    assert cfb.violations(root, "main") == []


@pytest.mark.parametrize("path, text", [
    ("calc.py", '"""Spot, from the row."""\n\n\ndef spot(row):\n    """The bid."""\n    return row["ask"]\n'),
    ("page.js", "// drawn here\nvar url = 'http://x/*z*/';\nvar re = /\\/\\//;\n"),        # inside a string
    ("page.js", "// drawn here\nvar url = 'http://x/*y*/';\nvar re = /\\/\\/x/;\n"),      # inside a regex
    # an encoding line: imported, the strings read otherwise
    ("calc.py", '# -*- coding: latin-1 -*-\n"""Spot, from the row."""\n\n\ndef spot(row):\n    """The bid."""\n'
                "    return row['bid']\n"),
])
def test_a_code_change_beside_the_comments_still_needs_a_failing_test(tmp_path, path, text):
    root = _repo(tmp_path, {**CLEANED, path: text}, base={**BASE, **NOTED})
    assert cfb.violations(root, "main") == [
        f"product code changed ({path}) but no end-to-end path test (tests/test_data_path_*.py or tests/e2e/*.spec.js) changed"]


def test_a_comment_only_change_to_an_html_page_still_needs_a_test(tmp_path):
    """A browser's reading of a page's whitespace, entities and comments depends on CSS and parser
    details, so a page is never judged unchanged by its comments."""
    root = _repo(tmp_path, {"page.html": "<p>a</p>\n"}, base={**BASE, "page.html": "<!-- RC-UI-1 -->\n<p>a</p>\n"})
    assert cfb.violations(root, "main") == ["product code changed (page.html) but no end-to-end path test (tests/test_data_path_*.py or tests/e2e/*.spec.js) changed"]


def test_deleting_a_product_file_is_proven_by_the_suite(tmp_path):
    """Operator 2026-10-28: a change that only removes whole undecorated Python functions or classes is
    proven by the full suite and the browser tests passing."""
    root = _repo(tmp_path, {"notes.md": "words\n"}, base={**BASE, "dead.py": "def unused(row):\n    return row['ask']\n"})
    _git(root, "rm", "-q", "dead.py")
    _git(root, "commit", "-q", "-m", "remove dead.py")
    assert cfb.violations(root, "main") == []


def test_moving_a_product_file_out_of_product_paths_is_a_deletion(tmp_path):
    root = _repo(tmp_path, {"notes.md": "words\n"}, base={**BASE, "dead.py": "def unused(row):\n    return row['ask']\n"})
    (root / "docs").mkdir()
    _git(root, "mv", "dead.py", "docs/dead.py")
    _git(root, "commit", "-q", "-m", "move dead.py")
    assert cfb.violations(root, "main") == []


ROUTE = "app = object()\n\n\n@app.get('/api/x')\ndef x():\n    return 1\n"
NEEDS = "but no end-to-end path test (tests/test_data_path_*.py or tests/e2e/*.spec.js) changed"


@pytest.mark.parametrize("name, before, after", [
    ("routes.py", ROUTE, "app = object()\n"),                              # a decorated route deleted
    ("page.js", "function a() { return 1; }\nfunction b() { return 2; }\n", "function a() { return 1; }\n"),
    ("calc.py", BASE["calc.py"] + "\n\ndef unused(row):\n    return row['ask']\n", FIX),   # a deletion and a changed line
    ("num.py", "def number(v):\n    if isinstance(v, str):\n        return None\n    return float(v)\n",
     "def number(v):\n    return float(v)\n"),                               # a guard line inside a function
    ("app.py", "app = object()\napp.mount('/static')\n", "app = object()\n"),   # a module-level call (a route)
    ("fields.py", "FIELDS = (\n    'bid',\n    'ask',\n)\n", "FIELDS = (\n    'bid',\n)\n"),   # an entry of a list
    ("page_text.py", 'T = """\n#a {}\n"""\n\n\ndef unused():\n    return 1\n', 'T = """\n#b {}\n"""\n'),   # a string's `#` line
    ("latin.py", "T = 'x'\n\n\ndef unused():\n    return 1\n", "# -*- coding: latin-1 -*-\nT = 'x'\n"),   # an encoding added
])
def test_a_deletion_that_is_not_whole_undecorated_python_units_still_needs_a_test(tmp_path, name, before, after):
    """Operator 2026-10-28: the suite proves only a removal of whole undecorated functions or classes;
    a line removed inside one, a module-level call or a decorated one changes behavior."""
    root = _repo(tmp_path, {name: after}, base={**BASE, name: before})
    assert cfb.violations(root, "main") == [f"product code changed ({name}) {NEEDS}"]


def test_a_deleted_file_with_a_module_level_call_still_needs_a_test(tmp_path):
    root = _repo(tmp_path, {"notes.md": "words\n"}, base={**BASE, "boot.py": "import os\n\nos.environ['X'] = '1'\n"})
    _git(root, "rm", "-q", "boot.py")
    _git(root, "commit", "-q", "-m", "remove boot.py")
    assert cfb.violations(root, "main") == [f"product code changed (boot.py) {NEEDS}"]


def test_an_added_empty_file_is_judged_not_failed(tmp_path):
    """A new file is no deletion: the check judges the PR's tests, and does not fail itself."""
    root = _repo(tmp_path, {"pkg/__init__.py": "", "calc.py": FIX, "tests/test_data_path_calc.py": (
        "from calc import spot\n\n\ndef test_spot_is_the_last_trade():\n    assert spot({'bid': 1, 'last': 2}) == 2\n")})
    assert cfb.violations(root, "main") == []


@pytest.mark.parametrize("path", ["my calc.py", "café.py"])
def test_a_product_file_whose_name_git_quotes_still_needs_a_test(tmp_path, path):
    root = _repo(tmp_path, {path: FIX}, base={**BASE, path: BASE["calc.py"]})
    assert cfb.violations(root, "main") == [f"product code changed ({path}) but no end-to-end path test (tests/test_data_path_*.py or tests/e2e/*.spec.js) changed"]


def test_a_product_file_replaced_by_a_link_still_needs_a_test(tmp_path):
    root = _repo(tmp_path, {"notes.md": "words\n"})
    (tmp_path / "target.txt").write_text("calc_impl.py", encoding="utf-8")
    sha = subprocess.run(["git", "hash-object", "-w", str(tmp_path / "target.txt")], cwd=root, check=True,
                         capture_output=True, text=True).stdout.strip()
    _git(root, "update-index", "--cacheinfo", f"120000,{sha},calc.py")
    _git(root, "commit", "-q", "-m", "calc.py becomes a link")
    assert cfb.violations(root, "main") == ["product code changed (calc.py) but no end-to-end path test (tests/test_data_path_*.py or tests/e2e/*.spec.js) changed"]


def test_removing_a_function_nothing_calls_is_proven_by_the_suite(tmp_path):
    base = {**BASE, "calc.py": BASE["calc.py"] + "\n\ndef unused(row):\n    return row['ask']\n"}
    root = _repo(tmp_path, {"calc.py": BASE["calc.py"]}, base=base)
    assert cfb.violations(root, "main") == []


USES = "import json\nimport math\nfrom os import path, sep\n\n\ndef spot(row):\n    return math.floor(row['bid'])\n"


@pytest.mark.parametrize("before, after", [
    (USES + "\n\ndef dump(row):\n    return json.dumps(row) + path.sep\n",        # json and path only the removed code used
     "import math\nfrom os import sep\n\n\ndef spot(row):\n    return math.floor(row['bid'])\n"),
    (USES + "\n\ndef dump(row):\n    return json.dumps(row)\n", USES.replace("import json\n", "")),
])
def test_a_removal_may_drop_the_imports_only_the_removed_code_used(tmp_path, before, after):
    """Operator 2026-10-28 ("Yes, both"): a removal may also drop the imports that only the removed
    functions or classes used."""
    root = _repo(tmp_path, {"calc.py": after}, base={**BASE, "calc.py": before})
    assert cfb.violations(root, "main") == []


@pytest.mark.parametrize("after", [
    USES.replace("import math\n", ""),                                           # an import still used, dropped
    "import csv\n" + USES,                                                       # an import added
    USES.replace("import json\n", ""),                                           # one the removed code never used
    USES.replace("import json\nimport math\n", "import math\nimport json\n"),    # imports reordered
])
def test_a_removal_that_drops_a_used_import_or_adds_one_still_needs_a_test(tmp_path, after):
    before = USES + "\n\ndef dump(row):\n    return row\n"
    root = _repo(tmp_path, {"calc.py": after}, base={**BASE, "calc.py": before})
    assert cfb.violations(root, "main") == [f"product code changed (calc.py) {NEEDS}"]


@pytest.mark.parametrize("before, after", [
    ("import math\n\n\ndef spot(row):\n    return math.floor(row['bid'])\n\n\ndef unused():\n    return 1\n",
     "import math; math.floor = round\n\n\ndef spot(row):\n    return math.floor(row['bid'])\n"),   # a statement beside an import
    ("from os.path import join as f\nfrom posixpath import basename as f\n\n\ndef g():\n    return f('a/b')\n\n\n"
     "def unused():\n    return 1\n",
     "from posixpath import basename as f\nfrom os.path import join as f\n\n\ndef g():\n    return f('a/b')\n"),  # imports swapped
])
def test_a_removal_beside_a_change_hidden_in_the_imports_still_needs_a_test(tmp_path, before, after):
    root = _repo(tmp_path, {"calc.py": after}, base={**BASE, "calc.py": before})
    assert cfb.violations(root, "main") == [f"product code changed (calc.py) {NEEDS}"]


def test_a_removal_that_drops_the_future_import_still_needs_a_test(tmp_path):
    """`from __future__ import annotations` binds a name no code uses; dropping it changes when every
    annotation is evaluated (FastAPI reads them), so it is not an import the removed code used."""
    future = "from __future__ import annotations\n\n" + USES
    root = _repo(tmp_path, {"calc.py": USES}, base={**BASE, "calc.py": future + "\n\ndef dump(row):\n    return row\n"})
    assert cfb.violations(root, "main") == [f"product code changed (calc.py) {NEEDS}"]
