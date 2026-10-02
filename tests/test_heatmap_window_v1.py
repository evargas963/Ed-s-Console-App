"""The heatmap the server serves is the one the page draws: the strike rows of the scope around the
price (or the panned centre), the columns the page fits, the row at the price, the contracts to
stream, each measure's colour scale and the cells whose value changed since the last publication.
Real data: three SPY chain captures, one expiry each (10-14, 10-15, 11-20), published as one chain
(no single capture spans three expiries); the live price is a stand-in, the 10-15 capture's spot."""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import pytest

import server
from terrain_engine import SCOPE_ROWS, strike_window

_FX = Path(__file__).resolve().parent / "fixtures"
_CHAIN = [c for f, key in (("real_spy_2026_10_14_chain_oi_zero.json", "contracts"),
                           ("real_spy_2026_10_15_chain_oi_zero.json", "contracts"),
                           ("real_spy_2026_11_20_chain_and_quotes.json", "chain"))
          for c in json.loads((_FX / f).read_text(encoding="utf-8"))[key]]
_SPOT = 764.92                                    # stand-in: the 10-15 capture's spot
TK = "SPY"


@pytest.fixture(autouse=True)
def _published(monkeypatch, pin_clock):
    pin_clock(2026, 10, 1, 12, 0)                 # the captures' day, before every expiry
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))
    monkeypatch.setattr(server, "_desired_stream_greeks_for_ticker", lambda tk, listed=None: {})
    with server._terrain_cache_lock:              # this test's chain, never one an earlier test left
        server._terrain_cache.pop(TK, None)
    assert server._publish_levels(TK, copy.deepcopy(_CHAIN), 1.0) is not None
    yield
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)


def _heat(**kw):
    args = {"scope": "auto", "centre": None, "shift": 0, "cols": None, "expiry": None, **kw}
    return json.loads(server.get_options_gamma_surface(TK, **args).body)


def _every_strike():
    return _heat(scope="all")["strikes"]


def test_each_scope_serves_its_rows_around_the_price_and_all_serves_every_strike():
    every = _every_strike()
    at_price = min(every, key=lambda k: abs(k - _SPOT))
    for scope, n in SCOPE_ROWS.items():
        d = _heat(scope=scope)
        assert len(d["cells"]) == n and d["strikes"] == [c["strike"] for c in d["cells"]]
        assert d["view"]["centre"] == at_price
        assert [c["strike"] for c in d["cells"] if c["spot"]] == [at_price]
        i = d["strikes"].index(at_price)
        assert i == (n - 1) // 2                   # the price row in the middle
    assert len(_heat(scope="all")["cells"]) == len(every) > SCOPE_ROWS["wider"]


def test_a_pan_moves_the_rows_and_stops_at_the_ends_of_the_chain():
    every = _every_strike()
    d = _heat(shift=3)
    centre = _heat()["view"]["centre"]
    assert d["view"]["centre"] == every[every.index(centre) + 3]
    top = _heat(centre=every[0])
    assert top["strikes"] == every[:SCOPE_ROWS["auto"]] and top["view"]["centre"] == every[0]
    bottom = _heat(centre=every[-1], shift=50)
    assert bottom["strikes"] == every[-SCOPE_ROWS["auto"]:] and bottom["view"]["centre"] == every[-1]


def test_strike_window_with_no_strikes_has_no_rows():
    assert strike_window([], 100.0, "auto") == (0, -1, None)


def test_columns_are_the_ones_the_page_fits_or_the_one_selected():
    expiries = ["2026-10-14", "2026-10-15", "2026-11-20"]
    assert [e["expiry"] for e in _heat(scope="all")["expirations"]] == expiries
    assert [e["expiry"] for e in _heat(cols=2)["expirations"]] == expiries[:2]
    assert [e["expiry"] for e in _heat(cols=1, scope="wider")["expirations"]] == expiries[:2]
    one = _heat(expiry="2026-11-20")
    assert [e["expiry"] for e in one["expirations"]] == ["2026-11-20"]
    assert all(len(c["gex"]) == 1 for c in one["cells"]) and one["view"]["missing_expiry"] is None
    gone = _heat(expiry="2026-12-18")
    assert gone["expirations"] == [] and gone["view"]["missing_expiry"] == "2026-12-18"
    assert [e["front"] for e in _heat(scope="all")["expirations"]] == [True, False, False]


def test_the_view_serves_the_colour_scale_and_the_contracts_drawn():
    d = _heat(cols=2)
    for m in ("gex", "dex"):
        drawn = [abs(v) for c in d["cells"] for v in c[m] if v is not None]
        assert d["view"]["max_abs"][m] == (max(drawn) if drawn else None)
    drawn = [pair[side] for j in range(2) for c in d["cells"] for pair in [c["contracts"][j]]
             if pair for side in ("call", "put") if pair.get(side)]
    assert d["view"]["demand"] == list(dict.fromkeys(drawn)) and d["view"]["demand"]
    listed = {c["symbol"] for c in _CHAIN}
    assert set(d["view"]["demand"]) <= listed


def test_a_cell_is_marked_changed_only_where_its_value_changed_since_the_last_publication():
    assert not any(any(flags) for c in _heat(scope="all")["cells"] for flags in c["changed"].values())
    target = next(c for c in _CHAIN if c["expirationDate"].startswith("2026-11-20") and c["openInterest"] > 0)
    chain = copy.deepcopy(_CHAIN)
    next(c for c in chain if c["symbol"] == target["symbol"])["openInterest"] += 1000
    server._publish_levels(TK, chain, 2.0)
    d = _heat(scope="all")
    col = [e["expiry"] for e in d["expirations"]].index("2026-11-20")
    marked = [(c["strike"], j) for c in d["cells"] for j, f in enumerate(c["changed"]["oi"]) if f]
    assert marked == [(float(target["strikePrice"]), col)]
