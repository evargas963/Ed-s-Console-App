"""One producer per value (operator 2026-10-14: "Every value in the repo has one producer: every
number, list (strike lists included), mark and time"), audit groups A-C: spot and strikes,
expirations, ages. Each page opens on the real console's push (server.live_values, driven with the
page's end of the socket stood in for: tests/test_live_values_push_v1._Page) and every panel that
shows one value must carry the same number.

Real data: CRWD's 2026-10-16 chain captured 2026-10-07 10:38:40 ET and MRVL's full chain (20
expiries) captured 10:31:20 ET (tests/real_chains.py), each priced at its capture. STAND-IN
(named): the daemon's status and each ticker's last trades (tests/feed_live_helper.py); the price
then moves above the price the chain was priced at (MOVE), as Schwab's quotes would, with no new
chain round -- so the live spot and the priced spot differ, as they do between rounds.
"""
from __future__ import annotations

import asyncio
import time

import pytest

import app.options.order_flow.state as ofls
import push_changes
import server
from tests.feed_live_helper import daemon_holds, forget_price, ledger_round, no_daemon, price_sent
from tests.real_chains import CRWD, MRVL
from tests.test_live_values_push_v1 import _Page, _by_name, _view
from time_et import age_label

TK = server.ticker_storage_key("CRWD")
MK = server.ticker_storage_key("MRVL")
#: the price's move after the chain was priced: to 302.54, by 302.50 -- a strike the charm panel's
#: own strike list leaves out (no priceable charm there), so before, its "spot strike" was 300 or 305
MOVE = 33.5


def _published(tk: str, chain) -> None:
    """`chain` priced at its capture, at Schwab's price in it (the trade recorded first)."""
    push_changes.bind(None)
    daemon_holds(chain.now.timestamp(), {"LEVELONE_EQUITIES": [tk]})
    price_sent(tk, chain.spot, chain.now.timestamp())
    ledger_round(tk, chain.chain, chain.now.timestamp(), now=chain.now)


def _clear(tk: str) -> None:
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    server._rounds.pop(tk, None)
    forget_price(tk)


@pytest.fixture
def crwd():
    _published(TK, CRWD)
    yield
    _clear(TK)
    ofls.clear_all_live_state()
    no_daemon()
    push_changes.bind(None)


@pytest.fixture
def mrvl():
    _published(MK, MRVL)
    yield
    _clear(MK)
    ofls.clear_all_live_state()
    no_daemon()
    push_changes.bind(None)


def _answers(ticker: str, spot: float, views: dict) -> dict:
    """Each view's panels' newest answers ({view: {panel: body}}), the price having moved to `spot`
    after the chain was priced (a trade, as the console's stream takes it)."""
    return {v: {n: p["body"] for n, p in got.items() if n != BEAT} for v, got in _frames(ticker, spot, views).items()}


#: the key of a view's beat after its panels (the console's "feed" line) in _frames
BEAT = "feed"


def _frames(ticker: str, spot: float, views: dict) -> dict:
    """Each view's panels as the push sent them ({view: {panel: its newest frame entry, BEAT: the
    next beat after them}}), as _answers."""
    async def go():
        push_changes.bind(asyncio.get_running_loop())
        daemon_holds(time.time(), {"LEVELONE_EQUITIES": [ticker]})
        price_sent(ticker, spot, time.time())
        push_changes.changed(ticker, push_changes.FLOW)
        await asyncio.sleep(0.05)
        out = {}
        for name, over in views.items():
            page = _Page()
            console = asyncio.create_task(server.live_values(page))
            try:
                await page.inbox.put(_view(1, ticker=ticker.lstrip("$"), symbols=[ticker.lstrip("$")], **over))
                view = await page.next("view")
                # the console's panels: the charts at 1 minute draw the daemon's series, not its answer
                shown = set(view["shown"]) - {"watchlist"} - set(view["series"])
                got: dict = {}
                async with asyncio.timeout(20):     # one limit for the whole wait: a panel that never comes fails
                    while not shown <= set(got):
                        got.update(_by_name(await page.next("panels")))
                got[BEAT] = await page.next("feed")
                out[name] = got
            finally:
                await page.inbox.put(None)
                await asyncio.wait_for(console, 10)
        return out
    return asyncio.run(go())


def _level(levels_body: dict, lid: str) -> dict:
    return next(r for r in levels_body["levels"] if r["id"] == lid)


def _spot_rows(rows: list) -> list:
    return [r["strike"] for r in rows if r.get("spot")]


def test_a_the_strike_at_the_price_and_every_value_read_from_the_price_is_one_number_everywhere(crwd):
    """Audit A. The strike nearest the live price, on every panel that shows it (the heatmap's
    spot row, GEX by Strike, Strike Detail and the Chain's ladders, vanna, charm, the chart, the
    Desk, Right Now), is one strike from one strike list. Each wall's distance from the price, the
    price's side of the flip, whether a wall is breached and the expected-move band are each one
    number at the live price, on the terrain and on the levels alike, never at the price the
    chain was priced at."""
    spot = CRWD.spot + MOVE
    strikes = sorted({c["strikePrice"] for c in CRWD.chain})
    near = min(strikes, key=lambda k: abs(k - CRWD.spot))
    a = _answers(TK, spot, {
        "heatmap": {"strike": near, "strike_expiry": "2026-10-16"},
        "chart": {"view": "chart"},
        "chain": {"subview": "chain", "view": ""},
        "vanna": {"subview": "vanna", "view": ""},
        "charm": {"subview": "charm", "view": ""},
        "desk": {"workspace": "trade-desk", "subview": "desk", "view": ""},
        "rightnow": {"workspace": "trade-desk", "subview": "right-now", "view": ""},
    })
    spot_strike = {
        "heatmap": _spot_rows(a["heatmap"]["gamma.surface"]["cells"]),
        "gex_by_strike": [a["heatmap"]["gamma.strikes"]["spot_strike"]],
        "strike_detail": _spot_rows(a["heatmap"]["gamma.strike"]["ladder"]),
        "chain": _spot_rows(a["chain"]["chain"]["ladder"]),
        "vanna": [a["vanna"]["vanna"]["spot_strike"]],
        "charm": [a["charm"]["charm"]["spot_strike"]],
        "chart": [a["chart"]["gamma.chart.strikes"]["spot_strike"]],
        "desk": [a["desk"]["desk.strikes"]["spot_strike"]],
        "rightnow": [a["rightnow"]["rightnow.strikes"]["spot_strike"]],
    }
    one = min(strikes, key=lambda k: abs(k - spot))
    assert spot_strike == {panel: [one] for panel in spot_strike}, spot_strike

    terrain, levels = a["desk"]["desk.terrain"], a["desk"]["desk.levels"]
    assert levels["spot"] == spot
    call, put, flip = _level(levels, "call_wall"), _level(levels, "put_wall"), _level(levels, "gamma_flip")
    assert terrain["dist_to_call_wall"] == call["distance"]
    assert terrain["dist_to_put_wall"] == -put["distance"]
    assert (terrain["flip_relation"] == "ABOVE") == (flip["distance"] <= 0)
    assert (terrain["call_wall_state"] == "breached") == (call["distance"] <= 0)
    assert (terrain["put_wall_state"] == "breached") == (put["distance"] >= 0)
    points = terrain["implied_1d_move"]["points"]
    assert (_level(levels, "em_up")["price"], _level(levels, "em_dn")["price"]) == (spot + points, spot - points)


def test_b_the_expiries_their_days_and_the_front_one_are_one_list_everywhere(mrvl):
    """Audit B. MRVL's 20 expiries: the dropdown's list, the heatmap's columns and the terrain's
    list are one list, each expiry with one days-to-expiry and one expired state; the front expiry
    (the nearest not expired by Schwab's session) is the heatmap's front column, the Chain's
    default expiry and the expiry max pain is read from, by one front-expiry rule."""
    spot = MRVL.spot
    a = _answers(MK, spot, {"heatmap": {"scope": "all"}, "chain": {"subview": "chain", "view": ""}})
    exp_panel, surface = a["heatmap"]["expiries"], a["heatmap"]["gamma.surface"]
    terrain = a["heatmap"]["gamma.terrain"]
    columns = surface["expirations"]
    assert [c["expiry"] for c in columns] == exp_panel["expiries"] == terrain["expiries"]
    assert {c["expiry"]: c["dte"] for c in columns} == exp_panel["dte"] == terrain["expiry_dte"]
    assert {c["expiry"]: c["expired"] for c in columns} == exp_panel["expired"]
    front = [c["expiry"] for c in columns if c["front"]]
    assert front == [exp_panel["front"]] == [a["chain"]["chain"]["expiry"]] == [terrain["max_pain_expiry"]]


def test_b_the_front_expiry_moves_at_its_settlement_and_is_unknown_behind_an_unknown_one():
    """Audit B at fixed instants, MRVL's real chain (no /markets answer held: each contract settles
    at Schwab's expirationDate, time_et.settles_at): at the capture the front is the nearest expiry
    not settled; a second after its settlement, the next; and with the nearest one's settlement
    not known (STAND-IN, named: its settlement removed), the front is not known either -- never
    the one after it."""
    from datetime import datetime

    from terrain_engine import expiry_states, listed_expiries
    listed = listed_expiries(MRVL.chain)
    settles = {}
    for c in MRVL.chain:
        e = c["expirationDate"][:10]
        settles[e] = max(settles.get(e, 0.0), datetime.fromisoformat(c["expirationDate"]).timestamp())
    at = MRVL.now.timestamp()
    order = [e for e in listed["expiries"] if settles[e] > at]
    assert expiry_states(listed, at)["front"] == order[0]
    after = expiry_states(listed, settles[order[0]] + 1)
    assert after["front"] == order[1] and after["expired"][order[0]] is True
    unknown = {**listed, "expiry_settles": {**listed["expiry_settles"], order[0]: None}}
    states = expiry_states(unknown, at)
    assert states["expired"][order[0]] is None and states["front"] is None


def test_c_the_levels_age_is_one_instant_labelled_once(crwd):
    """Audit C. The age of the published levels, on every panel that shows it (Key Levels, GEX by
    Strike, the heatmap, the Desk's terrain and its gamma levels): every answer names the one
    instant (the publication's, `as_of`) and serves no age of its own; the push labels it
    (time_et.age_label) on each answer and, every beat, for every panel shown at one instant:
    one age computation, one wording."""
    f = _frames(TK, CRWD.spot, {"heatmap": {}, "desk": {"workspace": "trade-desk", "subview": "desk", "view": ""}})
    published = CRWD.now.timestamp()
    panels = {"heatmap": ("gamma.terrain", "gamma.strikes", "gamma.surface"), "desk": ("desk.terrain", "desk.levels")}
    for view, names in panels.items():
        for name in names:
            body, ages = f[view][name]["body"], f[view][name]["ages"]
            assert body["as_of"]["levels"] == published, (view, name)
            assert ages["levels"] in {age_label(time.time() - published + d) for d in (-1, 0)}, (view, name, ages)
            seconds = [k for k in _keys(body) if k.endswith("age_sec") or k in ("levels_age", "age")]
            assert not seconds, (view, name, seconds)
        beat = f[view][BEAT]["as_of_ages"]
        assert beat["levels"] in {age_label(time.time() - published + d) for d in (-1, 0)}, beat
    gamma_rows = [r["staleness"] for r in f["desk"]["desk.levels"]["body"]["levels"] if r["family"] == "gamma"]
    assert gamma_rows and all(s["age_of"] == "levels" and s["as_of_ts_utc"] == published for s in gamma_rows)


def _keys(v) -> list:
    """Every key of every dict nested in `v`."""
    if isinstance(v, dict):
        return [key for k, x in v.items() for key in (k, *_keys(x))]
    if isinstance(v, list):
        return [key for x in v for key in _keys(x)]
    return []
