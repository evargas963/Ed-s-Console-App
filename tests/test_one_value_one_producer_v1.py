"""One producer per value, read once per change, every consumer the same value (operator
2026-10-13: "Every value, not just price: one producer, read once per change, and every consumer
gets that same value"). Two pages open on the real console (uvicorn, a real WebSocket): Gamma >
Heatmap with a strike selected (the heatmap, GEX by Strike and Strike Detail's chain on screen) and
the Trade Desk (the terrain and the levels). The price then moves across strikes, as Schwab's
quote moves it; on the newest answer of every panel, each value two of them carry is the same
number: the spot each used, the strike nearest it, the walls and the flip. Before, each route read
the live price at its own moment and the heatmap was answered again only on a levels publication:
its spot row stayed on the old strike while GEX by Strike's moved.

Real data: CRWD's 2026-10-16 chain captured 2026-10-07 10:38:40 ET (tests/real_chains.py), its
levels published at its capture. STAND-IN (named): the daemon's status and CRWD's last trades
(tests/feed_live_helper.py)."""
from __future__ import annotations

import asyncio
import json

from websockets.asyncio.client import connect

import push_changes
from tests.feed_live_helper import price_sent
from tests.test_live_values_push_v1 import TK, _AT, _console, _view, published  # noqa: F401 (the fixture)
from tests.real_chains import CRWD

_EXPIRY = "2026-10-16"


async def _newest(ws, answers: dict, quiet: float) -> None:
    """Take every panel answer that arrives until `quiet` seconds pass with none (the beat, the
    symbols and the rows come meanwhile), the newest of each panel kept."""
    loop = asyncio.get_running_loop()
    end = loop.time() + quiet
    while (left := end - loop.time()) > 0:
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), left))
        except TimeoutError:
            return
        if msg["type"] == "panels":
            answers.update({p["panel"]: p["body"] for p in msg["panels"]})
            end = loop.time() + quiet


def _consumers(gamma: dict, desk: dict) -> dict:
    """Each value two or more panels carry: {value: {panel: the number it carries}}."""
    spot_row = [c["strike"] for c in gamma["gamma.surface"]["cells"] if c["spot"]]
    chain_row = [r["strike"] for r in gamma["gamma.strike"]["ladder"] if r.get("spot")]
    level = {lv["id"]: lv["price"] for lv in desk["desk.levels"]["levels"]}
    terrain = desk["desk.terrain"]
    return {
        "spot": {"heatmap": gamma["gamma.surface"]["spot"], "gex_by_strike": gamma["gamma.strikes"]["spot"],
                 "strike_detail": gamma["gamma.strike"]["spot"], "desk_levels": desk["desk.levels"]["spot"],
                 "desk_strikes": desk["desk.strikes"]["spot"]},
        "spot_strike": {"heatmap": spot_row[0] if spot_row else None,
                        "gex_by_strike": gamma["gamma.strikes"]["spot_strike"],
                        "strike_detail": chain_row[0] if chain_row else None,
                        "desk_strikes": desk["desk.strikes"]["spot_strike"]},
        **{w: {"desk_terrain": terrain.get(w), "desk_levels": level.get(w)}
           for w in ("call_wall", "put_wall", "gamma_flip", "max_pain")},
    }


def test_every_consumer_of_a_value_shows_the_same_number_after_the_price_moves(published):
    async def body(host):
        async with connect(f"ws://{host}/api/live", max_size=None) as g, connect(f"ws://{host}/api/live", max_size=None) as d:
            strikes = sorted({c["strikePrice"] for c in CRWD.chain})
            near = min(strikes, key=lambda k: abs(k - CRWD.spot))
            await g.send(_view(1, strike=near, strike_expiry=_EXPIRY))
            await d.send(_view(1, workspace="trade-desk", subview="desk", view=""))
            gamma, desk = {}, {}
            await asyncio.gather(_newest(g, gamma, 2.0), _newest(d, desk, 2.0))
            # the price moves up across strikes, quote by quote, as Schwab's quotes come
            at = _AT.timestamp()
            for i, px in enumerate((CRWD.spot + 4, CRWD.spot + 9, CRWD.spot + 15)):
                price_sent(TK, px, at + 60 + i)
                push_changes.changed(TK, push_changes.FLOW)
                await asyncio.sleep(0.05)
            await asyncio.gather(_newest(g, gamma, 2.0), _newest(d, desk, 2.0))
            values = _consumers(gamma, desk)
            absent = {v: [p for p, n in shown.items() if n is None] for v, shown in values.items()}
            assert not any(absent.values()), f"a consumer carries no value: {absent}"
            differ = {v: shown for v, shown in values.items() if len(set(shown.values())) != 1}
            assert differ == {}, f"consumers of one value show different numbers: {differ}"
            assert values["spot"]["heatmap"] == CRWD.spot + 15, values["spot"]   # the newest price
    _console(body)
