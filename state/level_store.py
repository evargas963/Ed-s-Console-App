"""Every ticker's levels as last published, with what they were priced from.

The pricing thread is the one writer (server._publish_levels, server.restamp_open_surfaces);
every live reader reads them here, never a database (docs/DATA_FLOW.md §2 D6).
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from instrument_identity import ticker_storage_key
from option_contract import OptionContract
from terrain_engine import StrikeValue, TerrainSnapshot


@dataclass(frozen=True)
class PublishedLevels:
    """A ticker's levels as server._publish_levels published them, with their inputs."""

    snap: TerrainSnapshot
    #: when the chain was fetched: a reprice on a kept chain does not make the chain newer
    computed_ts_utc: float
    #: the newest Schwab option value in them: the chain, or a value pushed since
    levels_ts_utc: float
    #: Schwab's label of the chain's completeness (CAPTURE_BASIS, or a capture's own)
    chain_basis: str
    #: the price the levels were computed at, its source and its time
    spot_source: str
    spot_as_of_ts_utc: float | None
    #: the price as resolved for this publication: (price, source, time)
    priced_at: tuple[float | None, str, float | None]
    #: the heatmap grid (server.project_gamma_surface); None without a price or a book
    gamma_surface: dict[str, Any] | None
    vanna_rows: list[StrikeValue]
    charm_rows: list[StrikeValue]
    #: the chain as Schwab sent it, and as priced with the values pushed since
    chain: list[OptionContract]
    priced_chain: list[OptionContract]
    #: the contracts Schwab listed in the newest chain, each record by its symbol
    contracts: Mapping[str, OptionContract]
    #: read from the stored captures, recomputed only when `captures_key` changes
    forces: dict[str, Any]
    prior_day: TerrainSnapshot | None
    captures_key: tuple[float | None, str]

    def served(self) -> dict[str, Any]:
        """Return the levels as the terrain panel sends them, before the live price's relations."""
        return self.snap.to_dict() | {
            "computed_ts_utc": self.computed_ts_utc,
            "levels_ts_utc": self.levels_ts_utc,
            "chain_basis": self.chain_basis,
            "spot_source": self.spot_source,
            "spot_as_of_ts_utc": self.spot_as_of_ts_utc,
        }


#: ticker (its storage key) -> its levels as last published
_levels: dict[str, PublishedLevels] = {}
_lock = threading.Lock()


def published_levels(ticker: str) -> PublishedLevels | None:
    """Return the ticker's levels as last published, or None before the first."""
    with _lock:
        return _levels.get(ticker_storage_key(ticker))


def publish(tk: str, levels: PublishedLevels) -> None:
    """Hold `levels` as ticker `tk`'s (its storage key), in place of any it held."""
    with _lock:
        _levels[tk] = levels


def every_published() -> list[tuple[str, PublishedLevels]]:
    """Return each ticker's levels as last published, in the order first published."""
    with _lock:
        return list(_levels.items())


def listing_ticker(sym: str) -> str | None:
    """Return the ticker whose chain Schwab listed option contract `sym` in, or None.

    The same rule for every instrument, whatever the contract's root (SPXW and SPX are both
    $SPX's).
    """
    with _lock:
        return next((tk for tk, levels in _levels.items() if sym in levels.contracts), None)
