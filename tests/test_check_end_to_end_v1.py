"""tools/check_end_to_end.py (AGENTS.md rule 1) on real git repositories: a pull request that patches
is refused with each violation named; an end-to-end change passes."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_end_to_end as cee  # noqa: E402

BODY = "Schwab → screen: the daemon's quote.\nDeleted: the old queue.\nEnd-to-end test: tests/test_data_path_x.py\n"


def _repo(tmp_path: Path, base: dict[str, str]) -> Path:
    def git(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    for name, text in base.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    git("add", *base)
    git("commit", "-q", "-m", "base")
    git("checkout", "-q", "-b", "pr")
    return tmp_path


def _commit(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", *files], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "pr"], cwd=root, check=True, capture_output=True)


BASE = {"server.py": "def spot(row):\n    return row['last']\n",
        "static/js/page.js": "function draw(v) { return v; }\n",
        "tests/test_data_path_x.py": "def test_x():\n    pass\n"}


def test_a_patch_with_no_end_to_end_test_is_refused_with_each_violation_named(tmp_path):
    root = _repo(tmp_path, BASE)
    _commit(root, {
        "server.py": ("def spot(row):\n"
                      "    try:\n"
                      "        return row.get('last', 0) or 0\n"
                      "    except Exception:\n"
                      "        return None\n"),
        "static/js/page.js": "function draw(v) { return v || 0; }\n"})
    found = cee.violations(root, "main", "Fixed it.")
    assert found[0].startswith("product code changed")
    text = "\n".join(found)
    assert "server.py:3: a missing value replaced by a literal (`.get(key, <literal>)`)" in text
    assert "server.py:3: a missing value replaced by a literal (`or <literal>`)" in text
    assert "server.py:4: an except that catches everything" in text
    assert "server.py:4: an except that swallows the error" in text
    assert "static/js/page.js:1: a missing value replaced by a literal, or an empty catch" in text
    assert found[-1] == "the PR description lacks: Schwab → screen:, Deleted:, End-to-end test:"


def test_an_end_to_end_change_passes(tmp_path):
    root = _repo(tmp_path, BASE)
    _commit(root, {"server.py": "def spot(row):\n    return row['last'] if row['live'] else None\n",
                   "tests/test_data_path_x.py": "def test_x():\n    assert True\n"})
    assert cee.violations(root, "main", BODY) == []


def test_a_patch_already_on_main_is_not_counted_against_a_pr_that_does_not_touch_it(tmp_path):
    root = _repo(tmp_path, {**BASE, "server.py": "def spot(row):\n    return row.get('last', 0)\n"})
    _commit(root, {"server.py": "def spot(row):\n    return row.get('last', 0)\n\n\ndef bid(row):\n    return row['bid']\n",
                   "tests/test_data_path_x.py": "def test_x():\n    assert 1\n"})
    assert cee.violations(root, "main", BODY) == []
