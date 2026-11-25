"""The `chain` panel: one expiry of a ticker's full chain, as the chain screens show it.

Read from State: the published levels' priced chain and heatmap (state.level_store), each
contract's newest streamed values (app.options.order_flow.state) and the live price. Sent again on
each streamed quote of the ticker (server.FLOW_PANELS). The Chain ladder, Strike Detail and
Structures each ask it with their own expiry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal, TypedDict

import live_market_plane as lmp
from app.options.order_flow.state import rest_quotes, streamed_values
from calc.math_exposure_core import overlay_streamed_contract_fields
from calc.terrain_engine import LadderRow, chain_ladder
from numeric_contract import (
    count_text,
    dollars_text,
    greek_text,
    iv_text,
    price_text,
    schwab_time_ms,
    strike_text,
)
from option_contract import ChainRow, OptionContract, chain_row
from push.spot import resolve_spot
from push.strike_rows import expiry_unreadable
from push.verdict import LevelsVerdict, terrain_cache_get
from state import level_store
from state.level_store import GammaSurface, PublishedLevels
from time_et import et_date_str_from_ts_utc

# the program's one log (capture._start_log: the day's file and the window)
log = logging.getLogger("ed_server")

#: the chain panel's reason while no chain of the ticker is held and no chain error is recorded
NO_CHAIN_YET = "the daemon has not delivered this ticker's chain yet"
#: a chain answer's status: one expiry's contracts, or none (its scope says why)
CHAIN_OK: Final = "ok"
CHAIN_UNAVAILABLE: Final = "unavailable"
#: a chain answer's scope (its `scope.kind`): every contract of one expiry, or no chain to answer
#: from; and each as the chain's badge says it (`scope.kind_text`)
COMPLETE_SINGLE_EXPIRY, SCOPE_UNAVAILABLE = "complete_single_expiry", "unavailable"
SCOPE_TEXT = {COMPLETE_SINGLE_EXPIRY: "complete (ALL)", SCOPE_UNAVAILABLE: "unavailable"}
#: what every chain screen says with no row to draw and no reason for it (AGENTS.md rule 4)
NO_CHAIN_FOR_EXPIRY = "no chain for this expiry"


class ChainLeg(ChainRow):
    """A contract as the chain screens show it (_shown).

    Its fields under Schwab's names (option_contract.chain_row), and its open interest, volume,
    IV, bid, ask, delta and gamma as the screen shows them: None where Schwab sent no value.
    """

    oi_text: str | None
    volume_text: str | None
    iv_text: str | None
    bid_text: str | None
    ask_text: str | None
    delta_text: str | None
    gamma_text: str | None


class Series(TypedDict):
    """A ladder row's contract-level fields, each once, as Structures shows them (_series).

    Each as Schwab sent it to every leg of the row, under Schwab's name; the last trading day as
    its date in ET. None where the legs differ or Schwab sent none.
    """

    multiplier: object
    settlementType: object
    exerciseType: object
    expirationType: object
    nonStandard: object
    pennyPilot: object
    last_trading_day_et: str | None


#: a Series field read from a leg under Schwab's own name
type SeriesField = Literal[
    "multiplier", "settlementType", "exerciseType", "expirationType", "nonStandard", "pennyPilot"
]


class ServedLadderRow(LadderRow[ChainLeg]):
    """A ladder row as the chain panel serves it (_served_ladder).

    The row, its strike as the screen shows it, its net GEX in this expiry (None with no surface
    value at the strike) with that as text, and its contract-level fields.
    """

    strike_text: str
    net_gex: float | None
    net_gex_text: str | None
    series: Series


class ChainScope(TypedDict):
    """A chain answer's scope: its kind, and the kind as the chain's badge says it."""

    kind: str
    kind_text: str


class NoChainScope(ChainScope):
    """The scope of an answer with no chain: why there is none."""

    reason: str | None


class ChainPanel(LevelsVerdict):
    """The `chain` panel (chain): one expiry of the ticker's chain, with the levels' verdict.

    The expiry answered, whether Schwab lists two contracts at one strike and side, the ladder
    (its spot row at the live price), how many strikes it holds, and what the chain screens say
    with no row to draw (None with rows). The price itself is the price row's, which the page
    draws (one producer).
    """

    ticker: str
    expiry: str
    has_duplicate_contracts: bool
    status: Literal["ok"]
    ladder: list[ServedLadderRow]
    n_strikes: int
    scope: ChainScope
    none_said: str | None


class NoChain(LevelsVerdict):
    """The `chain` panel's answer with no chain to answer from: why, in its scope.

    The expiry asked for (None with none asked and none listed), a ladder of no rows (the page
    draws the ladder it is sent), and what the chain screens say for it, its reason in it.
    """

    ticker: str
    expiry: str | None
    ladder: list[ServedLadderRow]
    status: Literal["unavailable"]
    scope: NoChainScope
    none_said: str


def _net_gex_column(surf: GammaSurface | None, expiry: str) -> dict[float, float | None] | None:
    """Return the heatmap's net GEX by strike in `expiry`; None without a surface or its column."""
    if surf is None:
        return None
    col = next((i for i, e in enumerate(surf["expirations"]) if e["expiry"] == expiry), None)
    if col is None:
        return None
    return {c["strike"]: c["gex"][col] for c in surf["cells"]}


def _net_gex_at(column: dict[float, float | None] | None, strike: float) -> float | None:
    """Return the column's net GEX at `strike`; None without a column or a value there."""
    if column is None:
        return None
    return column.get(strike)


def _newest(contracts: list[OptionContract], since: float, now: float) -> list[OptionContract]:
    """Return `contracts` (as the levels priced them) with the newest values Schwab sent by `now`.

    A contract live on LEVELONE_OPTIONS by the one live rule takes its newest streamed record,
    and one Schwab does not stream its newest /quotes answer received at or after `since` (the
    chain's start), as the levels' pricing gives them (overlay_streamed_contract_fields). Every
    other contract keeps the values the levels priced: the last value stands.
    """
    syms = [c.symbol for c in contracts if c.symbol]
    feed = lmp.feed_now(now)
    streamed = streamed_values(lmp.held_option_symbols(syms, now, feed))
    live = lmp.live_symbols(feed, streamed, "LEVELONE_OPTIONS", now)
    return overlay_streamed_contract_fields(
        contracts,
        {s: streamed[s] for s in live},
        live,
        rest_quotes([s for s in syms if s not in streamed], since),
    )


def _shown(contracts: list[OptionContract]) -> list[ChainLeg]:
    """Each contract as the chain screens show it: its counts, IV, prices and Greeks as text."""
    return [
        {
            **chain_row(c),
            "oi_text": count_text(c.open_interest),
            "volume_text": count_text(c.volume),
            "iv_text": iv_text(c.volatility),
            "bid_text": price_text(c.bid),
            "ask_text": price_text(c.ask),
            "delta_text": greek_text(c.delta),
            "gamma_text": greek_text(c.gamma),
        }
        for c in contracts
    ]


def _last_trading_day_et(leg: ChainLeg) -> str | None:
    """Return Schwab's lastTradingDay (epoch milliseconds) as its date in ET; None when not sent."""
    ms = schwab_time_ms(leg.get("lastTradingDay"))
    return None if ms is None else et_date_str_from_ts_utc(ms / 1000.0)


def _only[T](values: set[T]) -> T | None:
    """Return the one value of `values`; None where they differ."""
    return next(iter(values)) if len(values) == 1 else None


def _shared(legs: list[ChainLeg], name: SeriesField) -> object:
    """Return the value every one of `legs` was sent `name` with; None where they differ."""
    return _only({leg.get(name) for leg in legs})


def _series(row: LadderRow[ChainLeg]) -> Series:
    """Return the contract-level fields of the row's call and put, each once, as Structures shows.

    The fields Schwab sends per contract, under Schwab's names: a listing's call and put at one
    strike share them. Each is the value every leg of the row was sent with (a row of one leg,
    that leg's); one the legs differ on, or that Schwab did not send, is None: no leg's value
    stands for another's.
    """
    legs = [leg for leg in (row["call"], row["put"]) if leg is not None]
    return {
        "multiplier": _shared(legs, "multiplier"),
        "settlementType": _shared(legs, "settlementType"),
        "exerciseType": _shared(legs, "exerciseType"),
        "expirationType": _shared(legs, "expirationType"),
        "nonStandard": _shared(legs, "nonStandard"),
        "pennyPilot": _shared(legs, "pennyPilot"),
        "last_trading_day_et": _only({_last_trading_day_et(leg) for leg in legs}),
    }


def _served_ladder(
    ladder: list[LadderRow[ChainLeg]], column: dict[float, float | None] | None
) -> list[ServedLadderRow]:
    """Each ladder row with its net GEX in this expiry and its contract-level fields (_series).

    The net GEX is the expiry's column of the surface, as the heatmap publishes it
    (_net_gex_column): Strike Detail shows it beside this expiry's contracts -- one value, one
    producer.
    """
    served: list[ServedLadderRow] = []
    for row in ladder:
        gex = _net_gex_at(column, row["strike"])
        served.append(
            {
                **row,
                "strike_text": strike_text(row["strike"]),
                "net_gex": gex,
                "net_gex_text": dollars_text(gex),
                "series": _series(row),
            }
        )
    return served


def _has_duplicates(contracts: list[OptionContract]) -> bool:
    """Tell whether Schwab lists two contracts at one (strike, side): not strike-unique."""
    return len({(c.strike, c.side) for c in contracts}) < len(contracts)


@dataclass(frozen=True)
class ExpiryAsked:
    """One expiry of a ticker's chain as a panel's `params` ask for it (expiry_asked).

    The levels these come from (None before the first) and their verdict; the expiry (the asked
    one, else the chain's front one; None with neither); its contracts with the newest values
    Schwab sent (_newest), or why there are none (`reason`, the contracts then empty).
    """

    held: PublishedLevels | None
    verdict: LevelsVerdict
    expiry: str | None
    contracts: list[OptionContract]
    reason: str | None


def expiry_asked(t: str, now: float, params: dict[str, Any]) -> ExpiryAsked:
    """Return the expiry `params` ask for of ticker `t`'s chain at `now`, with its contracts.

    `params["expiry"]`: the selected expiry, or None for the chain's front one, the levels' first
    listed. Each contract as the levels priced it, with the newest values Schwab sent since: the
    screen shows Schwab's value when it arrives, not at the next pricing.
    """
    unreadable = expiry_unreadable(params)
    # the expiry the page chose: a date, or None for the front one (and where it names none)
    expiry: str | None = None if unreadable is not None else params["expiry"]
    # the chain's state is its levels' (terrain_staleness), the one verdict the screen shows
    held, verdict = terrain_cache_get(t, now)
    listed = held.snap.expiries if held is not None else None
    requested = expiry.strip()[:10] if expiry is not None and expiry.strip() else None
    resolved = requested or (listed[0] if listed else None)

    def why(reason: str) -> ExpiryAsked:
        return ExpiryAsked(held, verdict, resolved, [], reason)

    if unreadable is not None:
        return why(unreadable)
    if held is None:
        return why(level_store.chain_failure(t) or NO_CHAIN_YET)
    if not held.priced_chain:
        return why(held.snap.error or level_store.chain_failure(t) or NO_CHAIN_YET)
    if resolved is None:
        return why("no listed expiry for this ticker")
    priced = [c for c in held.priced_chain if c.expiry == resolved]
    if not priced:
        return why(f"the chain lists no contracts for {resolved}")
    return ExpiryAsked(held, verdict, resolved, _newest(priced, held.computed_ts_utc, now), None)


def chain(ticker: str, now: float, params: dict[str, Any]) -> ChainPanel | NoChain:
    """Return one expiry of the ticker's full chain at `now`, from the chain the daemon delivered.

    The `chain` panel: the Chain ladder, Strike Detail and Structures, each its own reader with
    its own `expiry` (the selected expiry, or None for the chain's front one, the levels' first
    listed). Every contract Schwab listed, as the chain screens show it (option_contract.chain_row:
    a value Schwab did not send is null), once: in its `ladder` row -- from the chain the daemon
    delivered
    (strike_range=ALL), with each live streamed contract's streamed fields as its values (the
    stream owns them), by the levels' own rule on the same inputs (the chain's listed contracts,
    its fetch time). Every watchlist ticker's chain is kept. Answers `status: unavailable` with a
    reason when no chain is held. `ticker` is the levels' own key.
    """
    t = ticker
    asked = expiry_asked(t, now, params)
    held, verdict, resolved_expiry = asked.held, asked.verdict, asked.expiry
    if asked.reason is not None or held is None or resolved_expiry is None:
        return {
            "ticker": t,
            "expiry": resolved_expiry,
            "ladder": [],
            "status": CHAIN_UNAVAILABLE,
            **verdict,
            "scope": {
                "kind": SCOPE_UNAVAILABLE,
                "reason": asked.reason,
                "kind_text": SCOPE_TEXT[SCOPE_UNAVAILABLE],
            },
            "none_said": (
                NO_CHAIN_FOR_EXPIRY
                if asked.reason is None
                else f"chain unavailable — {asked.reason}"
            ),
        }
    response_contracts = asked.contracts
    shown = _shown(response_contracts)
    live_spot = resolve_spot(t, now=now)[0]  # the one spot: the ladder's spot row is at it
    ladder, not_on_ladder = chain_ladder(response_contracts, live_spot, shown)
    if not_on_ladder:
        log.warning(
            "%s %s: %d contract(s) Schwab sent have no strike or no CALL/PUT side and are not "
            "on the chain ladder",
            t,
            resolved_expiry,
            not_on_ladder,
        )
    served = _served_ladder(ladder, _net_gex_column(held.gamma_surface, resolved_expiry))
    return {
        "ticker": t,
        "expiry": resolved_expiry,
        "has_duplicate_contracts": _has_duplicates(response_contracts),
        **verdict,
        "status": CHAIN_OK,
        "ladder": served,
        "n_strikes": len({r["strike"] for r in ladder}),
        "scope": {
            "kind": COMPLETE_SINGLE_EXPIRY,
            "kind_text": SCOPE_TEXT[COMPLETE_SINGLE_EXPIRY],
        },
        "none_said": None if served else NO_CHAIN_FOR_EXPIRY,
    }
