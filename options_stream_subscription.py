"""OPTIONS FLOW — deterministic contract selection + subscription onto the EXISTING StreamClient.

WHAT THIS IS. Schwab entitles LEVELONE_OPTIONS and OPTIONS_BOOK; this console has never subscribed
to either. This module selects WHICH contracts to stream and drives the subscription through the
ONE StreamClient that order_flow_streaming already owns. It deliberately does not construct a
client, open a socket, or touch the LEVELONE_EQUITIES / NASDAQ_BOOK / NYSE_BOOK subscriptions —
those remain that module's authority, and a second socket would be a second source of truth.

WHY A SELECTION POLICY EXISTS AT ALL. Two failure modes bracket this decision and both are real:
  * Inheriting the equity path's viewer-dependent single-ticker behaviour would make options HISTORY
    a function of what someone happened to be looking at — useless for research, and silently
    incomplete in a way nobody would notice for months.
  * Subscribing an entire US options universe is not something we have proven Schwab or this host
    can carry. A chain fetch for ONE index root already exceeded the vendor's contract budget
    (RC-491, the $SPX 502), so "just subscribe everything" is an unproven capacity claim.
So contracts are chosen by an explicit, deterministic, explainable rule with a hard ceiling, and the
selection is RECORDED with each subscription so a later reader can tell exactly what was and was not
observable at a given time. Coverage that is bounded and known beats coverage that is unbounded and
assumed.

WHAT IS NOT INFERRED HERE. Selecting a contract says nothing about dealer ownership, inventory sign,
aggressor side, opening/closing intent, or market-maker economics. This module chooses symbols and
stores frames. Nothing it produces enters Decide.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

log = logging.getLogger(__name__)

#: Hard ceiling on simultaneously streamed option contracts. Chosen as a STARTING BOUND to be
#: measured against, not as a proven capacity limit — the message rate, host CPU and write rate at
#: this size are exactly what the capacity work has to establish. It exists so a policy bug cannot
#: silently subscribe thousands of symbols before anyone notices.
MAX_STREAMED_CONTRACTS = 240

#: Per-underlying shape of the selection. Strikes are counted PER SIDE of spot, so a value of 8
#: yields up to 16 strikes across, times 2 (call+put), times the expiry count.
DEFAULT_STRIKES_PER_SIDE = 8
DEFAULT_EXPIRIES = 3


@dataclass(frozen=True)
class SelectionPolicy:
    """A deterministic, explainable contract-selection rule.

    Deterministic matters for replay: given the same chain and spot, this returns the same symbols
    in the same order, so a historical window can be reasoned about rather than guessed at.
    """
    strikes_per_side: int = DEFAULT_STRIKES_PER_SIDE
    expiries: int = DEFAULT_EXPIRIES
    max_contracts: int = MAX_STREAMED_CONTRACTS

    def describe(self) -> str:
        return (f"nearest {self.expiries} expiries x {self.strikes_per_side} strikes per side of "
                f"spot x {{call,put}}, hard ceiling {self.max_contracts} contracts")


@dataclass
class SelectionResult:
    """Chosen symbols plus WHY — recorded so history is interpretable after the fact."""
    symbols: list[str] = field(default_factory=list)
    per_underlying: dict[str, int] = field(default_factory=dict)
    policy: str = ""
    truncated: bool = False
    notes: list[str] = field(default_factory=list)


def _contract_symbol(contract: dict) -> str | None:
    s = contract.get("symbol")
    return s if isinstance(s, str) and s.strip() else None


def select_contracts(chains_by_ticker: dict[str, tuple[float | None, list[dict]]],
                     policy: SelectionPolicy | None = None) -> SelectionResult:
    """Choose option contracts to stream, deterministically, from chains we ALREADY fetch.

    `chains_by_ticker` maps ticker -> (spot, contracts). Contracts are the native per-contract dicts
    the REST chain already returns, so this adds no vendor call: the selection rides data in hand.

    The rule, in order: nearest expiries first (a flow product lives at the front of the curve);
    within each expiry, strikes closest to spot first so the selection is centred rather than
    drifting to one wing; both sides of each strike. Ties break on the vendor symbol so the result
    is stable across runs.

    ALLOCATION IS FAIR ACROSS UNDERLYINGS, and that is not cosmetic. The first version filled the
    ceiling one underlying at a time in alphabetical order, which MEASURED OUT as AAPL/IWM/NVDA
    consuming all 240 slots and SPY and QQQ receiving ZERO — the two most important underlyings
    silently absent because of their initials. Contracts are now drawn round-robin, so a ceiling
    degrades DEPTH evenly across underlyings instead of deleting whole underlyings. Truncation is
    reported per underlying, so a reader can see what depth each one actually had.
    """
    pol = policy or SelectionPolicy()
    res = SelectionResult(policy=pol.describe() + ", allocated round-robin across underlyings")

    # Build each underlying's ORDERED preference list first (nearest expiry, then nearest strike).
    ranked: dict[str, list[str]] = {}
    for ticker in sorted(chains_by_ticker):
        spot, contracts = chains_by_ticker[ticker]
        if not contracts:
            res.notes.append(f"{ticker}: no contracts supplied — skipped")
            continue
        if spot is None or not spot > 0:
            res.notes.append(f"{ticker}: no usable spot — skipped rather than guessing a centre")
            continue

        by_expiry: dict[Any, list[dict]] = {}
        for c in contracts:
            if isinstance(c, dict) and c.get("expirationDate") is not None:
                by_expiry.setdefault(c["expirationDate"], []).append(c)
        if not by_expiry:
            res.notes.append(f"{ticker}: no contract carried an expirationDate — skipped")
            continue

        order: list[str] = []
        for exp in sorted(by_expiry)[: max(0, pol.expiries)]:
            group = by_expiry[exp]
            strikes = sorted({float(c["strikePrice"]) for c in group
                              if isinstance(c.get("strikePrice"), (int, float))})
            if not strikes:
                continue
            above = [k for k in strikes if k >= spot][: pol.strikes_per_side]
            below = list(reversed([k for k in strikes if k < spot]))[: pol.strikes_per_side]
            keep = set(above) | set(below)
            # nearest-to-spot first, then side, then symbol — deterministic and centred
            for c in sorted(group, key=lambda x: (
                    abs(float(x.get("strikePrice", 0)) - spot),
                    str(x.get("putCall", "")), _contract_symbol(x) or "")):
                k = c.get("strikePrice")
                if isinstance(k, (int, float)) and float(k) in keep:
                    sym = _contract_symbol(c)
                    if sym and sym not in order:
                        order.append(sym)
        if order:
            ranked[ticker] = order
            res.per_underlying[ticker] = 0

    # Round-robin draw: every underlying gets its 1st choice before any gets its 2nd.
    chosen: list[str] = []
    seen: set[str] = set()
    idx = 0
    while len(chosen) < pol.max_contracts:
        progressed = False
        for ticker in sorted(ranked):
            lst = ranked[ticker]
            if idx >= len(lst):
                continue
            progressed = True
            sym = lst[idx]
            if sym in seen:
                continue
            if len(chosen) >= pol.max_contracts:
                break
            chosen.append(sym)
            seen.add(sym)
            res.per_underlying[ticker] = res.per_underlying.get(ticker, 0) + 1
        if not progressed:
            break
        idx += 1

    if any(idx < len(lst) for lst in ranked.values()) and len(chosen) >= pol.max_contracts:
        res.truncated = True
        res.notes.append(
            f"ceiling {pol.max_contracts} reached — depth truncated EVENLY across "
            f"{len(ranked)} underlyings (per_underlying shows the depth each actually got); "
            f"strikes beyond that depth are NOT observable in this window")

    res.symbols = chosen
    return res


async def subscribe_options(stream_client: Any, symbols: Iterable[str], *,
                            level_one: bool = True, book: bool = True) -> dict[str, Any]:
    """Subscribe the given option symbols on the EXISTING client. Never creates one.

    LEVELONE_OPTIONS is requested with the COMPLETE entitled field set (all_fields()), never a
    convenient subset: the point of this foundation is that native truth is not lost because
    today's code did not ask for it. OPTIONS_BOOK carries its full nested structure inherently —
    the frame is the structure — so there is no field list to widen there.

    Returns a receipt describing what was actually requested, including the field COUNT, so a
    caller can assert the full surface was asked for rather than trusting a default.
    """
    syms = [s for s in dict.fromkeys(symbols) if s]
    receipt: dict[str, Any] = {"requested": len(syms), "level_one": None, "book": None, "errors": []}
    if not syms:
        receipt["errors"].append("no symbols to subscribe")
        return receipt
    if stream_client is None:
        receipt["errors"].append("no stream client — options subscription requires the existing one")
        return receipt

    if level_one:
        try:
            fields = list(type(stream_client).LevelOneOptionFields.all_fields())
            await stream_client.level_one_option_subs(syms, fields=fields)
            receipt["level_one"] = {"symbols": len(syms), "fields_requested": len(fields)}
            log.info("LEVELONE_OPTIONS subscribed: %d symbols, %d fields (complete surface)",
                     len(syms), len(fields))
        except Exception as e:                      # noqa: BLE001 - report, never kill the stream
            receipt["errors"].append(f"level_one_option_subs: {e}")
            log.warning("LEVELONE_OPTIONS subscribe failed: %s", e)

    if book:
        try:
            await stream_client.options_book_subs(syms)
            receipt["book"] = {"symbols": len(syms)}
            log.info("OPTIONS_BOOK subscribed: %d symbols (full nested depth)", len(syms))
        except Exception as e:                      # noqa: BLE001
            receipt["errors"].append(f"options_book_subs: {e}")
            log.warning("OPTIONS_BOOK subscribe failed: %s", e)

    return receipt


async def unsubscribe_options(stream_client: Any, symbols: Iterable[str]) -> dict[str, Any]:
    """Drop option subscriptions without touching the equity/book ones."""
    syms = [s for s in dict.fromkeys(symbols) if s]
    out: dict[str, Any] = {"requested": len(syms), "errors": []}
    if not syms or stream_client is None:
        return out
    for name in ("level_one_option_unsubs", "options_book_unsubs"):
        try:
            await getattr(stream_client, name)(syms)
        except Exception as e:                      # noqa: BLE001
            out["errors"].append(f"{name}: {e}")
    return out
