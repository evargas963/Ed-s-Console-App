"""tools/check_one_reader.py (ONE-31) on real git repositories: a pull request may not add a module
that reads a Schwab field raw. The refused case is what happened: the daemon's option rule
(`capture._took_price`) read LAST_PRICE itself, beside the price plane, with its own rule for -999."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_one_reader as cor  # noqa: E402

FIELDS = ("canonical_field,endpoint,type,variants,first_seen,last_seen,schwab_doc,sample\n"
          "LAST_PRICE,streaming,number,,2026-09-28,2026-09-28,,\n"
          "chains.callExpDateMap.*.openInterest,chains,number,,2026-09-28,2026-09-28,,\n")
PLANE = 'def spot(item):\n    return item.get("LAST_PRICE")\n'
BASE = {"docs/schwab_fields.csv": FIELDS, "plane.py": PLANE,
        "tests/test_plane.py": 'def test_it():\n    assert {"LAST_PRICE": 1}["LAST_PRICE"] == 1\n'}


def _git(root: Path, *a: str) -> None:
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)


def _pr(tmp_path: Path, files: dict[str, str | None]) -> Path:
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
        if text is None:
            _git(root, "rm", "-q", name)
            continue
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
        _git(root, "add", name)
    _git(root, "commit", "-q", "-m", "pr")
    return root


def test_a_second_module_reading_a_schwab_field_raw_is_refused(tmp_path):
    root = _pr(tmp_path, {"capture.py": (
        'def took_price(record):\n    native = record["native"]\n'
        '    return native["LAST_PRICE"] if "LAST_PRICE" in native else None\n')})
    assert cor.violations(root, "main") == [
        "LAST_PRICE: read raw by 2 modules, 1 before (added capture.py); one module reads a Schwab field"]


def test_moving_the_one_reader_and_a_test_reading_it_are_not_refused(tmp_path):
    root = _pr(tmp_path, {"plane.py": None, "parse.py": PLANE,
                          "tests/test_more.py": 'def test_it():\n    assert {"LAST_PRICE": 2}.get("LAST_PRICE")\n'})
    assert cor.violations(root, "main") == []


def test_a_field_name_from_the_list_by_its_last_name_is_read_from_any_mapping(tmp_path):
    root = _pr(tmp_path, {"levels.py": 'def oi(ct):\n    return ct["openInterest"]\n',
                          "book.py": 'def oi(ct):\n    return ct.get("openInterest")\n'})
    assert cor.violations(root, "main") == [
        "openInterest: read raw by 2 modules, 0 before (added book.py, levels.py); one module reads a Schwab field"]


def test_a_name_that_is_not_a_schwab_field_is_not_judged(tmp_path):
    root = _pr(tmp_path, {"other.py": 'def f(row):\n    return row["computed_ts_utc"]\n',
                          "more.py": 'def g(row):\n    return row.get("computed_ts_utc")\n'})
    assert cor.violations(root, "main") == []
