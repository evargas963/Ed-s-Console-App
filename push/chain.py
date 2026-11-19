"""The `chain` panel: one expiry of a ticker's full chain, as the chain screens show it.

Read from State: the published levels' priced chain and heatmap (state.level_store), each
contract's newest streamed values (app.options.order_flow.state) and the live price. Sent again on
each streamed quote of the ticker (server.FLOW_PANELS). The Chain ladder, Strike Detail and
Structures each ask it with their own expiry.
"""

from __future__ import annotations

import logging
from typing import Any

import live_market_plane as lmp
from app.options.order_flow.state import rest_quotes, streamed_values
from calc.math_exposure_core import overlay_streamed_contract_fields
from calc.terrain_engine import LadderRow, chain_ladder, nearest_strike
from numeric_contract import count_text, dollars_text, iv_text, price_text, strike_text
from option_contract import OptionContract, chain_row
from push.spot import resolve_spot
from push.verdict import terrain_cache_get
from state import level_store
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


def _ladder_with_gex(
    ladder: list[LadderRow], column: dict[float, float | None] | None
) -> list[dict[str, Any]]:
    """Each ladder strike with its net GEX in this expiry, as the heatmap publishes it.

    The expiry's column of the surface (_net_gex_column): Strike Detail shows it beside this
    expiry's contracts -- one value, one producer.
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
            }
        )
    return served


def _listing(contracts: list[OptionContract]) -> dict[str, Any]:
    """Return what Schwab's listing says of an expiry's contracts, as the chain panel serves it."""
    return {
        # Schwab's own flag for a non-standard (adjusted) deliverable, as sent
        "adjusted_deliverable_symbols": [c.symbol for c in contracts if c.non_standard],
        # Schwab's lastTradingDay, an instant in epoch milliseconds, as its date on the market's
        # clock (ET); a contract Schwab sent none for has no entry
        "last_trading_day_et": {
            c.symbol: et_date_str_from_ts_utc(ms / 1000.0)
            for c in contracts
            if isinstance(ms := c.listing.get("lastTradingDay"), float)
        },
        # two contracts listed at one (strike, side): the chain is not strike-unique
        "has_duplicate_contracts": len({(c.strike, c.side) for c in contracts}) < len(contracts),
    }


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
    expiry = params.get("expiry")
    # the chain's state is its levels' (terrain_staleness), the one verdict the screen shows
    held, verdict = terrain_cache_get(t, now)
    listed = held.snap.expiries if held is not None else None
    requested = expiry.strip()[:10] if isinstance(expiry, str) and expiry.strip() else None
    resolved_expiry = requested or (listed[0] if listed else None)

    def _unavailable(reason: str) -> dict[str, Any]:
        return {
            "ticker": t,
            "spot": None,
            "expiry": resolved_expiry,
            "ladder": [],
            "status": "unavailable",
            **verdict,
            "scope": {"kind": "unavailable", "reason": reason},
        }

    if "expiry" not in params or not (expiry is None or isinstance(expiry, str)):
        return _unavailable(f"expiry {expiry!r} is not an expiry date or null")
    if held is None:
        return _unavailable(level_store.chain_failure(t) or NO_CHAIN_YET)
    if not held.priced_chain:
        return _unavailable(held.snap.error or level_store.chain_failure(t) or NO_CHAIN_YET)
    if resolved_expiry is None:
        return _unavailable("no listed expiry for this ticker")
    # the contracts as the levels priced them (_publish_levels), each with the newest values
    # Schwab sent since: the screen shows Schwab's value when it arrives, not at the next pricing
    priced = [c for c in held.priced_chain if c.expiry == resolved_expiry]
    if not priced:
        return _unavailable(f"the chain lists no contracts for {resolved_expiry}")
    response_contracts = _newest(priced, held.computed_ts_utc, now)
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
    served = _ladder_with_gex(ladder, _net_gex_column(held.gamma_surface, resolved_expiry))
    return {
        "ticker": t,
        "spot": live_spot,
        "spot_text": price_text(live_spot),
        "spot_time_ct": ct_label(live_ts) if live_ts is not None else None,
        "expiry": resolved_expiry,
        "spot_strike": nearest_strike(
            {c.strike for c in response_contracts if c.strike is not None}, live_spot
        ),
        **_listing(response_contracts),
        **verdict,
        "status": "ok",
        "ladder": served,
        "n_strikes": len({r["strike"] for r in ladder}),
        "scope": {"kind": "complete_single_expiry"},
    }
