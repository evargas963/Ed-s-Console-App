"""tools.census.copied_blocks: a block of 8 or more lines copied, imports left out as pylint does.

The imports are the two test modules' the census at 219c0c84 counted as a copied block
(tests/test_option_contract_rule_v1.py:29 = tests/test_level_crosses_wire.py:22); the copied
body is the Recorder's own queue drain (stream_spine.CaptureWriter._drained).
"""

from __future__ import annotations

import ast

import pytest

from tools.census.copied_blocks import copied, import_lines

pytestmark = pytest.mark.rail

#: the ten lines the two modules' imports, in isort's order, hold alike, and a parenthesized
#: import of eight names both hold
_IMPORTS = """\
from pathlib import Path

import pytest

import live_market_plane as lmp
import live_price_rows
import server
import time_et
from app.market_data.schwab.streaming import capture
from app.options.order_flow import streaming as ofs
from tests.feed_live_helper import (
    clock_from,
    daemon_status,
    mark_feed_down,
    mark_feed_live,
    publish_capture,
    recorder,
    stored_crosses,
)
"""

_DRAINED = '''\
def _drained(q):
    """Empty the queue; the messages it held, in order."""
    items = []
    while True:
        try:
            item = q.get_nowait()
        except queue.Empty:
            return items
        if item is not None:
            items.append(item)
'''


def _read(**texts: str) -> dict[str, tuple[str, set[int]]]:
    """Each module's text with its import lines, as the census reads a Python file."""
    return {f"{name}.py": (text, import_lines(ast.parse(text))) for name, text in texts.items()}


def test_two_modules_importing_the_same_names_copied_nothing():
    rule = _IMPORTS + "\n\ndef test_rule():\n    assert lmp and capture\n"
    crosses = _IMPORTS + "\n\ndef test_crosses():\n    assert ofs and server\n"
    assert list(copied(_read(rule=rule, crosses=crosses))) == []


def test_a_block_copied_below_other_imports_is_found_where_each_begins():
    """INDUCED: the Recorder's queue drain, copied into a module with imports of its own."""
    first = "from stream_spine import (\n    CAPTURE_HELD,\n    CAPTURE_REFUSED,\n)\n\n\n"
    again = "import queue\n\n\n"
    assert list(copied(_read(first=first + _DRAINED, again=again + _DRAINED))) == [
        ("again.py:4", "first.py:7")
    ]


def test_an_import_statement_takes_every_line_it_spans():
    tree = ast.parse("import os\nfrom a import (\n    b,\n    c,\n)\n\nx = 1\n")
    assert import_lines(tree) == {1, 2, 3, 4, 5}
