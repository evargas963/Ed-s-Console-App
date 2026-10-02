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
    args = {"scope": "auto", "centre": None, "shift": 0, "cols": None, "expiry": None, "since": None, **kw}
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


def _marked(d, measure):
    return [(c["strike"], d["expirations"][j]["expiry"]) for c in d["cells"] if "changed" in c
            for j, f in enumerate(c["changed"][measure]) if f]


def test_a_cell_flashes_when_its_value_changed_after_the_publication_the_page_drew():
    """`changed` is relative to `since`, the surface_seq the page last drew: a change in a
    publication the page never read still flashes, and a redraw of what it has seen does not."""
    first = _heat(scope="all")
    assert not _marked(first, "oi")                               # the first draw: nothing to flash
    drawn = first["surface_seq"]
    target = next(c for c in _CHAIN if c["expirationDate"].startswith("2026-11-20") and c["openInterest"] > 0)
    chain = copy.deepcopy(_CHAIN)
    next(c for c in chain if c["symbol"] == target["symbol"])["openInterest"] += 1000
    server._publish_levels(TK, chain, 2.0)                         # the OI changes ...
    server._publish_levels(TK, copy.deepcopy(chain), 3.0)          # ... and a publication the page skips
    want = [(float(target["strikePrice"]), "2026-11-20")]
    assert _marked(_heat(scope="all", since=drawn), "oi") == want
    latest = _heat(scope="all")["surface_seq"]
    assert latest == drawn + 2
    assert not _marked(_heat(scope="all", since=latest), "oi")    # drawn already: no flash again
    # a strike that leaves the chain and comes back starts afresh: its earlier change is not flashed
    k = float(target["strikePrice"])
    server._publish_levels(TK, [c for c in chain if float(c["strikePrice"]) != k], 4.0)
    server._publish_levels(TK, copy.deepcopy(chain), 5.0)
    assert not _marked(_heat(scope="all", since=drawn), "oi")


def test_with_no_live_price_the_window_says_it_is_not_around_the_price(monkeypatch):
    """No price and no pan: the rows are the middle of the chain, served with the reason (no row
    is marked as the price), on the heatmap and on every per-strike panel."""
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (None, "none", None))
    d = _heat()
    assert d["view"]["note"] == server.WINDOW_NO_PRICE and not any(c["spot"] for c in d["cells"])
    strikes = json.loads(server.get_terrain_strikes(TK, scope="auto", centre=None, shift=0).body)
    assert {v["note"] for v in strikes["views"].values() if v["centre"] is not None} == {server.WINDOW_NO_PRICE}
    every = _every_strike()
    panned = _heat(centre=every[3])                                # the operator's pan: no reason needed
    assert panned["view"]["note"] is None and panned["view"]["centre"] == every[3]


def test_expired_columns_are_drawn_labelled_and_never_streamed_or_counted(pin_clock):
    """On 2026-10-15 the 10-14 column has expired: Auto draws the unexpired columns, Wider and All
    draw it labelled, and its contracts are neither streamed nor counted in the coverage."""
    pin_clock(2026, 10, 15, 12, 0)
    auto = _heat(cols=3)
    assert [e["expiry"] for e in auto["expirations"]] == ["2026-10-15", "2026-11-20"]
    every = _heat(scope="all")
    assert [(e["expiry"], e["expired"], e["front"]) for e in every["expirations"]] == [
        ("2026-10-14", True, False), ("2026-10-15", False, True), ("2026-11-20", False, False)]
    expired = {c["symbol"] for c in _CHAIN if c["expirationDate"].startswith("2026-10-14")}
    assert not expired & set(every["view"]["demand"]) and every["view"]["demand"]
    only = _heat(expiry="2026-10-14")                              # the expired column alone
    assert only["view"]["demand"] == [] and only["view"]["coverage"]["cells"] == 0
    # the chip says the columns have expired, not that no cell has a contract
    assert (only["view"]["coverage"]["state"], only["view"]["coverage"]["label"]) == (server.COVERAGE_EXPIRED, "EXPIRED")


def test_every_per_strike_panel_is_served_its_window_and_scale():
    """GEX by strike (today: all, near, far), the chart's DEX and OI, the migration's scale with the
    prior day, vanna and charm: each list is the scope's rows around the price or the pan, with
    the largest |value| drawn as its scale."""
    def lists(body):
        return {**{sc: body["today"][sc] for sc in ("all", "near", "far")},
                **{m: body["measures"][m]["rows"] for m in ("dex", "oi")}}
    body = json.loads(server.get_terrain_strikes(TK, scope="auto", centre=None, shift=0).body)
    every = lists(json.loads(server.get_terrain_strikes(TK, scope="all", centre=None, shift=0).body))
    assert every["all"] and every["dex"] and every["oi"]
    for name, rows in lists(body).items():
        view = body["views"][name]
        assert len(rows) == min(SCOPE_ROWS["auto"], len(every[name])), name
        assert all(r in every[name] for r in rows), name                # rows of the list, as published
        known = [abs(r[1]) for r in rows if r[1] is not None]
        assert view["max_abs"] == (max(known) if known else None), name
        assert view["note"] is None or not rows, name
    # no prior day is stored here: the migration's scale is today's
    assert body["views"]["all"]["max_abs_with_prior"] == body["views"]["all"]["max_abs"] is not None
    assert body["views"]["near"]["max_abs_with_prior"] is None                  # no near-term rows
    assert body["measures"]["dex"]["view"] == body["views"]["dex"]
    for route in (server.get_vanna_by_strike, server.get_charm_by_strike):
        d = json.loads(route(TK, scope="auto", centre=None, shift=0).body)
        rows = [r[0] for r in d["rows"]]
        panned = json.loads(route(TK, scope="auto", centre=d["view"]["centre"], shift=2).body)
        every = [r[0] for r in json.loads(route(TK, scope="all", centre=None, shift=0).body)["rows"]]
        assert panned["view"]["centre"] == every[every.index(d["view"]["centre"]) + 2]
        assert [r[0] for r in panned["rows"]] != rows and len(panned["rows"]) == len(rows)
