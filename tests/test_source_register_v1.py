"""The source documents' register (docs/SOURCES.md) is whole and none of its sources is overdue.

Failure this catches (2026-11-12): a change was built on the belief that a ticker's option
contract list changes once a day; the exchanges' listing plan says a series may be added during
the trading day. Operator: "you always check source documents first", and the documents "should be
checked periodically". Checked: every source names what it settles, a file that exists or a link,
the date it was read and the date it is read again by, and that date has not passed.
"""

from datetime import date, datetime
from pathlib import Path

import time_et
from time_et import ET

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "docs" / "SOURCES.md"
COLUMNS = ["id", "settles", "source", "where", "saved", "read", "again by"]


def _rows() -> list[dict[str, str]]:
    lines = [ln for ln in REGISTER.read_text(encoding="utf-8").splitlines() if ln.startswith("|")]
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    assert header == COLUMNS, header
    return [
        dict(zip(header, (c.strip() for c in ln.strip("|").split("|")), strict=True))
        for ln in lines[2:]
    ]


def test_every_source_is_listed_whole_and_its_file_exists():
    rows = _rows()
    assert len(rows) >= 12 and len({r["id"] for r in rows}) == len(rows), "one row per source"
    for r in rows:
        assert all(r[c] for c in COLUMNS), r["id"]
        assert date.fromisoformat(r["read"]) <= date.fromisoformat(r["again by"]), r["id"]
        if r["saved"] == "saved":
            assert (ROOT / r["where"]).is_file(), (
                f"{r['id']}: {r['where']} is not in the repository"
            )
        else:
            linked = r["saved"].startswith("link only: ") and r["where"].startswith("https://")
            assert linked, r["id"]


def test_the_options_that_close_at_the_index_close_are_the_sources_list():
    """The program's 4:15 p.m. ET list is the exchange's, symbol for symbol.

    Failure this catches (2026-11-13): the program held SPY, QQQ and IWM where the source lists
    65 symbols, so DIA's, GLD's and the others' options were closed at 16:00 ET. Checked: the
    symbols the register's nasdaq-options-hours row lists are the program's set, no more, no
    fewer.
    """
    row = next(r for r in _rows() if r["id"] == "nasdaq-options-hours")
    listed = row["settles"].split("(", 1)[1].split(")", 1)[0].split(", ")
    assert len(listed) == len(set(listed)) == 65
    assert set(listed) == time_et._INDEX_CLOSE_UNDERLYINGS


def test_no_source_is_past_the_date_it_is_read_again_by():
    today = datetime.fromtimestamp(time_et.now(), ET).date()
    overdue = [r["id"] for r in _rows() if date.fromisoformat(r["again by"]) < today]
    assert not overdue, (
        f"read these sources again and give each its new dates in docs/SOURCES.md: {overdue}"
    )
