"""The Options/Gamma heatmap's surface is the page socket's panel, served by no route.

Its cells' numbers are served as text (tests/test_served_numbers_v1.py); the page formats none.
"""

from __future__ import annotations

import server as srv
from app.market_data.schwab.streaming.live_ui import Asked
from push import surface as push_surface


def test_gamma_surface_is_the_sockets_panel_and_no_route():
    paths = [route.path for route in srv.app.routes]
    assert "/api/options/gamma-surface" not in paths
    asked = Asked("ZZNOSURFACE", 0.0, {"scope": "auto", "centre": None, "shift": 0})
    assert srv.PAGE_PANELS["surface"](asked) == push_surface.gamma_surface(
        asked.ticker, asked.now, asked.params, requested=False
    )
    # /console converged into `/` here (/console cutover, operator directive 2026-09-14) --
    # the dev route is gone, not aliased; the new console is served at `/` (see root()).
    assert "/" in paths
