"""The `chain` panel: one expiry of a ticker's full chain, as the chain screens show it.

Read from State: the published levels' priced chain and heatmap (state.level_store), each
contract's newest streamed values (app.options.order_flow.state) and the live price. Sent again on
each streamed quote of the ticker (server.FLOW_PANELS). The Chain ladder, Strike Detail and
Structures each ask it with their own expiry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import live_market_plane as lmp
from app.options.order_flow.state import rest_quotes, streamed_values
from calc.math_exposure_core import overlay_streamed_contract_fields
from calc.terrain_engine import LadderRow, chain_ladder
from numeric_contract import count_text, dollars_text, iv_text, price_text, strike_text
from option_contract import OptionContract, chain_row
from push.spot import resolve_spot
from push.verdict import LevelsVerdict, terrain_cache_get
from state import level_store
from state.level_store import PublishedLevels
from time_et import ct_label, et_date_str_from_ts_utc

# the program's one log (capture._start_log: the day's file and the window)
log = logging.getLogger("ed_server")

#: the chain panel's reason while no chain of the ticker is held and no chain error is recorded
NO_CHAIN_YET = "the daemon has not delivered this ticker's chain yet"


def _net_gex_column(surf: dict[str, Any] | None, expiry: str) -> dict[float, float | None] | None:
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
    newest, _ = overlay_streamed_contract_fields(
        contracts,
        {s: streamed[s] for s in live},
        live,
        rest_quotes([s for s in syms if s not in streamed], since),
    )
    return newest


def _shown(contracts: list[OptionContract]) -> list[dict[str, Any]]:
    """Each contract as the chain screens show it, with its counts, IV, bid and ask as text."""
    return [
        {
            **chain_row(c),
            "oi_text": count_text(c.open_interest),
            "volume_text": count_text(c.volume),
            "iv_text": iv_text(c.volatility),
            "bid_text": price_text(c.bid),
            "ask_text": price_text(c.ask),
        }
        for c in contracts
    ]


#: the fields Schwab sends per contract that Structures shows once per ladder row, under Schwab's
#: names: a listing's call and put at one strike share them
SERIES_FIELDS = (
    "multiplier",
    "settlementType",
    "exerciseType",
    "expirationType",
    "nonStandard",
    "pennyPilot",
)


def _last_trading_day_et(leg: dict[str, Any]) -> str | None:
    """Return Schwab's lastTradingDay (epoch milliseconds) as its date in ET; None when not sent."""
    ms = leg.get("lastTradingDay")
    return et_date_str_from_ts_utc(ms / 1000.0) if isinstance(ms, float) else None


def _series(row: LadderRow) -> dict[str, Any]:
    """Return the contract-level fields of the row's call and put, each once, as Structures shows.

    Each is the value every leg of the row was sent with (a row of one leg, that leg's); one the
    legs differ on, or that Schwab did not send, is None: no leg's value stands for another's.
    """
    legs = [leg for leg in (row["call"], row["put"]) if leg is not None]
    read = {f: {leg.get(f) for leg in legs} for f in SERIES_FIELDS}
    read["last_trading_day_et"] = {_last_trading_day_et(leg) for leg in legs}
    return {f: next(iter(v)) if len(v) == 1 else None for f, v in read.items()}


def _served_ladder(
    ladder: list[LadderRow], column: dict[float, float | None] | None
) -> list[dict[str, Any]]:
    """Each ladder row with its net GEX in this expiry and its contract-level fields (_series).

    The net GEX is the expiry's column of the surface, as the heatmap publishes it
    (_net_gex_column): Strike Detail shows it beside this expiry's contracts -- one value, one
    producer.
    """
    served: list[dict[str, Any]] = []
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


def _listing(contracts: list[OptionContract]) -> dict[str, Any]:
    """Return what Schwab's listing says of an expiry's contracts, as the chain panel serves it."""
    return {
        # two contracts listed at one (strike, side): the chain is not strike-unique
        "has_duplicate_contracts": len({(c.strike, c.side) for c in contracts}) < len(contracts),
    }


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
    expiry = params.get("expiry")
    # the chain's state is its levels' (terrain_staleness), the one verdict the screen shows
    held, verdict = terrain_cache_get(t, now)
    listed = held.snap.expiries if held is not None else None
    requested = expiry.strip()[:10] if isinstance(expiry, str) and expiry.strip() else None
    resolved = requested or (listed[0] if listed else None)

    def why(reason: str) -> ExpiryAsked:
        return ExpiryAsked(held, verdict, resolved, [], reason)

    if "expiry" not in params or not (expiry is None or isinstance(expiry, str)):
        return why(f"expiry {expiry!r} is not an expiry date or null")
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


def chain(ticker: str, now: float, params: dict[str, Any]) -> dict[str, Any]:
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
            "status": "unavailable",
            **verdict,
            "scope": {"kind": "unavailable", "reason": asked.reason},
        }
    response_contracts = asked.contracts
    shown = _shown(response_contracts)
    live_spot, _src, live_ts = resolve_spot(t, now=now)  # the one spot, with Schwab's trade time
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
        "spot_text": price_text(live_spot),
        "spot_time_ct": ct_label(live_ts) if live_ts is not None else None,
        "expiry": resolved_expiry,
        **_listing(response_contracts),
        **verdict,
        "status": "ok",
        "ladder": served,
        "n_strikes": len({r["strike"] for r in ladder}),
        "scope": {"kind": "complete_single_expiry"},
    }
