"""tools.census.compare: before and after, from two census reports in the census's own format.
Zero is a value, missing is unknown: a category one report lacks is 0 only when that report shows
its checker ran; otherwise it is "-" and the totals say they are incomplete.
"""

from __future__ import annotations

from tools.census.compare import compare

HEADER = "| Section | Category | Rule | Counted by | Count | Kind |\n|---|---|---|---|---|---|\n"
BEFORE = (
    "# EdWebConsole census, 2026-11-07, 6be67378\n\n"
    + HEADER
    + "| A. Code patterns | patch shapes: Python product | 1 | e2e | 124 | issue |\n"
    "| A. Code patterns | inner imports: tests | 13 | ruff PLC0415 | 278 | issue |\n"
    "| B. Linters | ruff ARG001 | locks | ruff | 71 | issue |\n"
    "| B. Linters | ruff: equals its own total (reported) | census | ruff | 71 | reported |\n"
    "| F. Databases | columns stamped by SQLite's clock (ed_console.db) | 11 | db | 2 | issue |\n"
)
AFTER = (
    "# EdWebConsole census, 2026-11-08, 1234abcd\n\n"
    + HEADER
    + "| A. Code patterns | patch shapes: Python product | 1 | e2e | 120 | issue |\n"
    "| A. Code patterns | inner imports: tests | 13 | ruff PLC0415 | 278 | issue |\n"
    "| B. Linters | ruff: equals its own total (reported) | census | ruff | 0 | reported |\n"
    "| C. Dead code | page functions nothing calls | 1 | regex | 0 | issue |\n"
)


def _compare(tmp_path):
    before, after = tmp_path / "before.md", tmp_path / "after.md"
    before.write_text(BEFORE, encoding="utf-8")
    after.write_text(AFTER, encoding="utf-8")
    return compare(before, after)


def test_a_row_present_on_both_sides_compares_its_counts(tmp_path):
    out = _compare(tmp_path)

    assert "| A. Code patterns | 402 | 398 | -4 |" in out
    assert "| A. Code patterns | patch shapes: Python product | 124 | 120 | -4 |" in out
    assert "inner imports" not in out.split("Categories that moved")[1]


def test_a_rule_missing_where_its_checker_ran_is_zero(tmp_path):
    out = _compare(tmp_path)

    assert "| B. Linters | 71 | 0 | -71 |" in out
    assert "| B. Linters | ruff ARG001 | 71 | 0 | -71 |" in out


def test_a_category_whose_check_did_not_run_is_unknown_never_zero(tmp_path):
    out = _compare(tmp_path)

    assert "| F. Databases | 2 | - (incomplete) | - |" in out
    assert "| F. Databases | columns stamped by SQLite's clock (ed_console.db) | 2 | - | - |" in out
    assert "| C. Dead code | page functions nothing calls | - | 0 | - |" in out
    assert "| ALL | 475 (incomplete) | 398 (incomplete) | - |" in out
