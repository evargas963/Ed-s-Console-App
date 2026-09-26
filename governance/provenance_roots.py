"""The root population under the root rule (governance/provenance_inventory.py, RC-532).

ROUTES — every served route, classified (an unclassified route fails the suite).
MARKET_STATE — every MarketState field: (category, producer row ref or None = OPEN).
ENGINE_INPUTS — every argument of every decision-engine entry: producer row ref or None.

Categories are reviewed human judgment from the closed vocabulary FIELD_CATEGORIES; the
producer refs were seeded mechanically from build_market_state's assignments (2026-09-07)
and are OPEN where the assembler takes the value from a local the seed could not trace.
An OPEN root is NOT_PROVEN, listed by name, and reported — never hidden.
"""
from __future__ import annotations

ROUTES: dict[str, tuple[str, str | None]] = {
    '/': ('PAGE', None),
    '/api/alerts': ('PRODUCER', 'server.py:get_alerts'),
    '/api/analytics/light/stream': ('STREAM', None),
    '/api/bars1m': ('PRODUCER', 'server.py:get_bars1m'),
    '/api/build': ('OPS', None),
    '/api/chain': ('PRODUCER', 'server.py:get_chain'),
    '/api/desk/brief': ('CARRIER', None),
    '/api/desk/dossier': ('CARRIER', None),
    '/api/desk/evidence': ('CARRIER', None),
    '/api/desk/radar': ('CARRIER', None),
    '/api/desk/structure': ('CARRIER', None),
    '/api/expiries': ('PRODUCER', None),
    '/api/exposure/flow': ('PRODUCER', 'server.py:get_exposure_flow'),
    '/api/forces': ('PRODUCER', 'server.py:get_forces'),
    '/api/health': ('OPS', None),
    '/api/level_crosses': ('CARRIER', None),
    '/api/levels': ('PRODUCER', 'server.py:get_levels'),
    '/api/liquidity-snapshot': ('CARRIER', None),
    '/api/options/charm-by-strike': ('PRODUCER', 'server.py:get_charm_by_strike'),
    '/api/options/gamma-surface': ('PRODUCER', 'server.py:project_gamma_surface'),
    '/api/options/tape': ('PRODUCER', 'server.py:get_options_tape'),
    '/api/options/vanna-by-strike': ('PRODUCER', 'server.py:get_vanna_by_strike'),
    '/api/order-flow/book-heatmap': ('PRODUCER', 'server.py:get_order_flow_book_heatmap'),
    '/api/order-flow/microstructure': ('PRODUCER', 'server.py:api_order_flow_microstructure'),
    '/api/order-flow/options-microstructure': ('PRODUCER', 'server.py:api_order_flow_options_microstructure'),
    '/api/release/current': ('OPS', None),
    '/api/session': ('PRODUCER', 'server.py:get_session'),
    '/api/spot': ('PRODUCER', 'server.py:get_spot'),
    '/api/streaming/active-option-contract': ('OPERATOR_INPUT', None),
    '/api/streaming/active-option-contracts': ('OPERATOR_INPUT', None),
    '/api/streaming/active-ticker': ('OPERATOR_INPUT', None),
    '/api/streaming/watchlist-symbols': ('OPERATOR_INPUT', None),
    '/api/terrain': ('PRODUCER', 'server.py:get_terrain'),
    '/api/terrain/scorecard': ('PRODUCER', None),
    '/api/terrain/strikes': ('PRODUCER', 'server.py:get_terrain_strikes'),
    '/api/watchlist-quotes': ('PRODUCER', 'server.py:api_watchlist_quotes'),
    '/chart': ('PAGE', None),
    '/desk': ('PAGE', None),
    '/exposure': ('PAGE', None),
    '/favicon.ico': ('PAGE', None),
    '/options': ('PAGE', None),
}

MARKET_STATE: dict[str, tuple[str, str | None]] = {}

ENGINE_INPUTS: dict[tuple[str, str], dict[str, str | None]] = {}

#: Keys the serializer adds to the card payload OUTSIDE MarketState (B2 payload fields).
PAYLOAD_EXTRAS: dict[str, tuple[str, str | None]] = {}

#: Roots with no producer yet — NOT_PROVEN, by name. The suite asserts this list is EXACT:
#: a root cannot go OPEN silently, and a root that closes must leave this list.
OPEN_ROOTS: tuple[str, ...] = (
    '/api/expiries',
    '/api/terrain/scorecard',
)
