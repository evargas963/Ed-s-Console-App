"""tools/check_one_reader.py (ENF-23) on real git repositories, with the repository's own Schwab
field list (docs/schwab_fields.csv): a pull request may not add a module that reads a Schwab
field raw. The refused shape is the daemon's option rule reading LAST_PRICE itself
(app/market_data/schwab/streaming/capture.py), beside the price plane's reader."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_one_reader as cor  # noqa: E402

FIELDS = (Path(__file__).resolve().parent.parent / "docs" / "schwab_fields.csv").read_text(
    encoding="utf-8"
)
PLANE = 'def spot(item):\n    return item.get("LAST_PRICE")\n'
BASE = {
    "docs/schwab_fields.csv": FIELDS,
    "plane.py": PLANE,
    "tests/test_plane.py": 'def test_it():\n    assert {"LAST_PRICE": 1}["LAST_PRICE"] == 1\n',
}


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
    root = _pr(
        tmp_path,
        {
            "capture.py": (
                'def took_price(record):\n    native = record["native"]\n'
                '    return native["LAST_PRICE"] if "LAST_PRICE" in native else None\n'
            )
        },
    )
    assert cor.violations(root, "main") == [
        "LAST_PRICE: read raw by 2 modules, 1 before (added capture.py); one module reads a Schwab field"
    ]


def test_a_one_word_streamer_field_is_judged(tmp_path):
    """DELTA is Schwab's LEVELONE_OPTIONS field; our own records name it `delta`."""
    root = _pr(
        tmp_path,
        {
            "greeks.py": 'def d(item):\n    return item.get("DELTA")\n',
            "tape.py": 'def d(item):\n    return item["DELTA"]\n',
        },
    )
    assert cor.violations(root, "main") == [
        "DELTA: read raw by 2 modules, 0 before (added greeks.py, tape.py); one module reads a Schwab field"
    ]


def test_a_read_through_a_module_constant_is_a_read(tmp_path):
    root = _pr(
        tmp_path,
        {
            "trades.py": 'VENDOR_LAST_PRICE = "LAST_PRICE"\n\n\n'
            "def price(item):\n    return item.get(VENDOR_LAST_PRICE)\n"
        },
    )
    assert cor.violations(root, "main") == [
        "LAST_PRICE: read raw by 2 modules, 1 before (added trades.py); one module reads a Schwab field"
    ]


def test_moving_the_one_reader_and_a_test_reading_it_are_not_refused(tmp_path):
    root = _pr(
        tmp_path,
        {
            "plane.py": None,
            "parse.py": PLANE,
            "tests/test_more.py": 'def test_it():\n    assert {"LAST_PRICE": 2}.get("LAST_PRICE")\n',
        },
    )
    assert cor.violations(root, "main") == []


def test_a_rest_field_in_camel_case_is_read_from_any_mapping(tmp_path):
    root = _pr(
        tmp_path,
        {
            "levels.py": 'def oi(ct):\n    return ct["openInterest"]\n',
            "book.py": 'def oi(ct):\n    return ct.pop("openInterest")\n',
        },
    )
    assert cor.violations(root, "main") == [
        "openInterest: read raw by 2 modules, 0 before (added book.py, levels.py); one module reads a Schwab field"
    ]


def test_our_own_records_keys_named_like_a_plain_schwab_word_are_not_judged(tmp_path):
    """`status`, `type` and `symbol` are in Schwab's field list and are our own records' keys too."""
    root = _pr(
        tmp_path,
        {
            "feed.py": '_feed = {"status": None}\n\n\ndef state():\n    return _feed["status"]\n',
            "push.py": 'def kind(msg):\n    return msg.get("type"), msg["symbol"]\n',
            "more.py": 'def kind(msg):\n    return msg.get("type"), msg["symbol"]\n',
        },
    )
    assert cor.violations(root, "main") == []


def test_removing_a_field_from_the_list_does_not_take_it_out_of_the_check(tmp_path):
    kept = "\n".join(line for line in FIELDS.splitlines() if ".LAST_PRICE," not in line) + "\n"
    assert "LAST_PRICE" not in cor.schwab_fields(kept) and "LAST_PRICE" in cor.schwab_fields(FIELDS)
    root = _pr(
        tmp_path,
        {
            "docs/schwab_fields.csv": kept,
            "capture.py": 'def took(n):\n    return n["LAST_PRICE"]\n',
        },
    )
    assert cor.violations(root, "main") == [
        "LAST_PRICE: read raw by 2 modules, 1 before (added capture.py); one module reads a Schwab field"
    ]


def test_a_membership_test_is_a_read(tmp_path):
    root = _pr(tmp_path, {"has.py": 'def has(item):\n    return "LAST_PRICE" not in item\n'})
    assert cor.violations(root, "main") == [
        "LAST_PRICE: read raw by 2 modules, 1 before (added has.py); one module reads a Schwab field"
    ]


def test_a_write_in_schwabs_spelling_is_not_a_read(tmp_path):
    root = _pr(tmp_path, {"build.py": 'def build(d):\n    d["LAST_PRICE"] = 1\n    return d\n'})
    assert cor.violations(root, "main") == []


def test_a_new_reader_beside_another_is_refused_even_when_one_stops_reading(tmp_path):
    root = _pr(
        tmp_path,
        {
            "plane.py": 'def spot(item):\n    return item.get("LAST_PRICE")\n',
            "first.py": 'def a(item):\n    return item["BID_PRICE"]\n',
        },
    )
    _git(root, "checkout", "-q", "main")
    (root / "first.py").write_text('def a(item):\n    return item["BID_PRICE"]\n', encoding="utf-8")
    (root / "second.py").write_text(
        'def b(item):\n    return item["BID_PRICE"]\n', encoding="utf-8"
    )
    _git(root, "add", "first.py", "second.py")
    _git(root, "commit", "-q", "-m", "two readers")
    _git(root, "checkout", "-q", "-b", "swap")
    (root / "second.py").write_text("def b(item):\n    return item\n", encoding="utf-8")
    (root / "third.py").write_text(
        'def c(item):\n    return item.get("BID_PRICE")\n', encoding="utf-8"
    )
    _git(root, "add", "second.py", "third.py")
    _git(root, "commit", "-q", "-m", "swap a reader")
    assert cor.violations(root, "main") == [
        "BID_PRICE: read raw by 2 modules, 2 before (added third.py); one module reads a Schwab field"
    ]


def test_the_check_exits_2_when_it_cannot_read_the_code(tmp_path, capsys):
    root = _pr(tmp_path, {"broken.py": "def f(:\n"})
    here = Path.cwd()
    try:
        os.chdir(root)
        assert cor.main(["--base", "main"]) == 2
    finally:
        os.chdir(here)
    assert "does not parse" in capsys.readouterr().err


def test_a_module_that_does_not_parse_fails_the_check_closed(tmp_path):
    root = _pr(tmp_path, {"broken.py": "def f(:\n"})
    try:
        cor.violations(root, "main")
    except cor.ToolError as e:
        assert "broken.py does not parse" in str(e)
    else:
        raise AssertionError("an unparseable module was left out of the count")
