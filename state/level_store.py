"""Every ticker's levels as last published, with what they were priced from.

The pricing thread is the one writer (server._publish_levels, server.restamp_open_surfaces);
every live reader reads them here, never a database (docs/DATA_FLOW.md §2 D6).
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypedDict

from calc.terrain_engine import TerrainSnapshot
from instrument_identity import ticker_storage_key
from option_contract import OptionContract


class SurfaceColumn(TypedDict):
    """One expiration column of the heatmap grid: its expiry and Schwab's daysToExpiration."""

    expiry: str
    dte: int | None


class CallPutTotal(TypedDict):
    """A cell's call and put values of one measure, and their total."""

    call: float
    put: float
    total: float


class CellContracts(TypedDict):
    """The contracts behind one cell: its call's and its put's symbol, None where none is listed."""

    call: str | None
    put: str | None


class StreamLeg(TypedDict):
    """One contract of a cell on the stream: its state and when it was last received."""

    symbol: str
    state: str
    ts_recv: float | None


class StreamLegs(TypedDict, total=False):
    """A cell's legs on the stream: the call's and the put's, each only where it is listed."""

    call: StreamLeg
    put: StreamLeg


class CellStream(StreamLegs):
    """A cell's stream state: its legs', the cell's own from them, and its tooltip (None: live)."""

    state: str
    title: str | None


class ProjectedCell(TypedDict):
    """One strike's row of the heatmap grid: each measure's value in every expiration column.

    A value not known is None; `contracts` names each column's call and put.
    """

    strike: float
    gex: list[float | None]
    dex: list[float | None]
    vanna: list[float | None]
    oi: list[CallPutTotal | None]
    volume: list[CallPutTotal | None]
    contracts: list[CellContracts]


class GridCell(ProjectedCell):
    """A row of the grid with each column's stream state: None where the expiry lists none."""

    stream: list[CellStream | None]


class ProjectedSurface(TypedDict):
    """The strike x expiry grid as server.project_gamma_surface shapes it from the priced books.

    `contracts_total`: the chain's contracts; `contracts_used`: those given a column (a contract
    with a missing or malformed expiry is counted and has none).
    """

    expirations: list[SurfaceColumn]
    strikes: list[float]
    cells: list[ProjectedCell]
    contracts_total: int
    contracts_used: int


class SurfaceState(TypedDict):
    """What the grid carries beside its cells: its counts, its stream state and its revision.

    `stream_overlay_contracts`: how many of the chain's contracts the stream held when it was
    priced; `stream_overlay_symbols`: the contracts the pricing gave newer values than the
    chain's; `stream_overlay_computed_ts_utc`: when it was priced; `stream_by_expiry`: each
    column's state from its cells'; `surface_seq`: the grid's revision, new with every publication
    and restamp.
    """

    contracts_total: int
    contracts_used: int
    stream_overlay_contracts: int
    stream_overlay_symbols: list[str]
    stream_overlay_computed_ts_utc: float
    stream_by_expiry: dict[str, str]
    surface_seq: int


class GammaSurface(SurfaceState):
    """The heatmap grid the levels hold: the projection, stamped with its cells' stream state."""

    expirations: list[SurfaceColumn]
    strikes: list[float]
    cells: list[GridCell]


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
    gamma_surface: GammaSurface | None
    #: every contract the heatmap's cells name, read once as it is published: the beat's restamp
    #: (server.restamp_open_surfaces) reads it every second for every ticker
    surface_symbols: frozenset[str]
    #: the chain as Schwab sent it, and as priced with the values pushed since
    chain: list[OptionContract]
    priced_chain: list[OptionContract]
    #: the contracts Schwab listed in the newest chain, each record by its symbol
    contracts: Mapping[str, OptionContract]
    #: the prior market day's levels, read from the stored captures, recomputed only when
    #: `captures_key` changes
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
#: ticker (its storage key) -> why its newest chain is not priced: the daemon's chain fetch failed
#: with Schwab's answer, or pricing it failed. Cleared by the next chain priced.
_failures: dict[str, str] = {}
_lock = threading.Lock()


def chain_failed(tk: str, why: str) -> None:
    """Hold why ticker `tk`'s (its storage key) newest chain is not priced."""
    with _lock:
        _failures[tk] = why


def chain_priced(tk: str) -> None:
    """Clear ticker `tk`'s chain failure: its newest chain is priced."""
    with _lock:
        _failures.pop(tk, None)


def chain_failure(ticker: str) -> str | None:
    """Return why the ticker's newest chain is not priced, or None while none failed."""
    with _lock:
        return _failures.get(ticker_storage_key(ticker))


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
