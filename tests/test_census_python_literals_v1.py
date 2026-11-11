"""tools.census.python_literals: which Python literal puts a value where one is missing.

The statements are the product's own, as the operator read them one at a time on 2026-11-11
(the census's 24 "fallbacks: Python product"), and the ones removed since as fallbacks.
"""

from __future__ import annotations

import pytest

from tools import check_end_to_end as e2e
from tools.census.python_literals import stands_in

#: reported apart: nothing is invented (a reason, a state word, a label, nothing to show, a
#: setting of the program's own)
NOT_FALLBACKS = [
    'if oi is None:\n    return "no_open_interest"\n',
    'if ask is None:\n    return "BID"\n',
    'if newest is None:\n    return "feed record: none yet"\n',
    'if n_spot is None:\n    return {"gsf": None, "grc": None, "state": "UNAVAILABLE"}\n',
    "if prior is None:\n    return {}\n",
    'line = "daemon link: " + ("connected" if st is not None else "NOT CONNECTED")\n',
    "for lid, value in snap.levels.items() if snap is not None else ():\n    pass\n",
    "degraded = list(snap.degraded) if snap is not None else []\n",
    "stats = stats if stats is not None else {}\n",
    'raw = os.environ.get(name, "").strip()\n',
    'allow = os.environ.get("ED_OTHER", "8123")\n',
    'label = getattr(row, "label", None)\n',
    'name = row.get("name", "")\n',
]

#: fallbacks: a value of the data's kind stands where one is missing
FALLBACKS = [
    "if charm is None:\n    charm_net = 0.0\n",
    "generation = 1 if existing is None else existing.generation + 1\n",
    "volume = quote.get('volume', 0)\n",
    "size = row.get('size') or 0\n",
    "live = row.get('live', False)\n",
    'strike = row.get("strike", "0")\n',
    "levels = levels or [0.0]\n",
    'top = top if top is not None else {"bid": 0, "ask": 0}\n',
    "seen = counts.setdefault(key, 0)\n",
    "spot = getattr(snap, 'spot', last_spot)\n",
    "frame = frame.fillna(0)\n",
]


def _line(source: str) -> int:
    """The one line check_end_to_end finds a shape on in `source`."""
    (found,) = {line for line, _what in e2e.shapes("product.py", source)}
    return found


@pytest.mark.parametrize("source", NOT_FALLBACKS)
def test_a_literal_that_invents_nothing_is_not_a_fallback(source):
    assert not stands_in(source, _line(source))


@pytest.mark.parametrize("source", FALLBACKS)
def test_a_value_of_the_datas_kind_where_one_is_missing_is_a_fallback(source):
    assert stands_in(source, _line(source))
