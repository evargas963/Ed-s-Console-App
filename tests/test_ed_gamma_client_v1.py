"""The Options/Gamma heatmap's surface is the page socket's panel, served by no route.

Its cells' numbers are served as text (tests/test_served_numbers_v1.py); the page formats none.
The surface is MRVL's full chain of 2026-10-07 as Schwab sent it
(tests/fixtures/real_mrvl_full_chain_2026_10_07.json), published as the stored capture it is, at
the price Schwab sent in it.
"""

from __future__ import annotations

import server as srv
from app.market_data.schwab.streaming.live_ui import Asked
from push import surface as push_surface
from state import level_store
from tests.feed_live_helper import publish_capture
from tests.real_chains import MRVL


def test_gamma_surface_is_the_sockets_panel_and_no_route():
    paths = [route.path for route in srv.app.routes]
    assert "/api/options/gamma-surface" not in paths
    publish_capture(
        "MRVL", MRVL.chain, MRVL.now.timestamp(), MRVL.spot, MRVL.now.date().isoformat(), MRVL.now
    )
    try:
        asked = Asked(
            "MRVL",
            MRVL.now.timestamp(),
            {"scope": "auto", "centre": None, "shift": 0, "cols": None, "expiry": None},
        )
        served = srv.PAGE_PANELS["surface"](asked)
        assert served == push_surface.gamma_surface(
            asked.ticker, asked.now, asked.params, requested=False
        )
    finally:
        level_store._levels.pop("MRVL", None)
    # the panel is MRVL's surface, not a refusal: its window has columns, strikes and cells
    assert served["available"] is True
    assert served["expirations"] and served["strikes"] and served["cells"]
    # /console converged into `/` here (/console cutover, operator directive 2026-09-14) --
    # the dev route is gone, not aliased; the new console is served at `/` (see root()).
    assert "/" in paths
