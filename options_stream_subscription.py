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

#: Schwab's streamer budget is counted in KEYS (symbol x service), not symbols. The repo's own
#: recorded arithmetic (governance/CONSOLE_REBUILD_PLAN_CR_V1.md S3, "Streamer capacity v1.1"):
#: 50xL1 + 50xNYSE_BOOK + 50xNASDAQ_BOOK + 450 internals = 600 > 500 — i.e. each service a
#: symbol is subscribed to consumes its own key against a ~500 ceiling. That document treats 500
#: as the operative number while noting the real accounting is measured at CR-01, so it is used
#: here as a DOCUMENTED BOUND, not a verified vendor constant.
SCHWAB_STREAM_KEY_LIMIT = 500

#: Keep a margin so a selection that is briefly stale, or an equity resubscribe landing at the
#: same moment, cannot push the account over the limit and disturb the equity/book subscriptions
#: this console actually depends on.
KEY_SAFETY_MARGIN = 20

#: Fallback ceiling when the budget cannot be computed. Deliberately small: under uncertainty the
#: safe error is too little coverage (a measurable gap) rather than a rejected subscription that
#: could take the shared stream with it.
MAX_STREAMED_CONTRACTS = 240

#: Per-underlying shape of the selection. Strikes are counted PER SIDE of spot, so a value of 8
#: yields up to 16 strikes across, times 2 (call+put), times the expiry count.
DEFAULT_STRIKES_PER_SIDE = 8
DEFAULT_EXPIRIES = 3

#: Underlyings that are NEVER rotated out. These are the money path: the console's own decision
#: surface, terrain and models are built on SPY/QQQ/IWM, so a gap in their options history is a
#: gap in the record for everything that matters most. Everything else shares what remains.
CORE_UNDERLYINGS = ("SPY", "QQQ", "IWM")

#: How long one rotation slice lasts. Long enough that a slice yields a usable run of observations
#: for the underlyings it covers (a 60-second slice would produce confetti), short enough that a
#: full cycle over the enrolled universe completes within a session.
DEFAULT_SLICE_SECONDS = 900


@dataclass(frozen=True)
class RotationPolicy:
    """How universal coverage is achieved when the budget cannot hold everything at once.

    THE CONSTRAINT, stated plainly. Schwab bills KEYS (symbol x service) against roughly 500. With
    both options services on, that is ~238 contracts. The enrolled universe is 58 underlyings.
    Spreading 238 across 58 gives FOUR contracts each — two strikes, one expiry, both sides. That
    is enough to prove a pipeline works and nowhere near enough to describe an underlying's flow.

    So breadth and depth cannot both be had at one instant, and pretending otherwise is how a
    product ends up with a permanently useless strike ladder. The resolution is to make the choice
    explicit and TIME-VARYING rather than fixed:

      * CORE underlyings are always subscribed, at depth. They are the money path; their history
        must be continuous, not sampled.
      * The remaining budget rotates over the rest of the enrolled universe in deterministic
        slices, so each non-core underlying receives REAL depth periodically instead of a
        permanent sliver.
      * Every slice is written to the coverage record, so a reader can always answer "was this
        contract observable then" rather than inferring it from the presence of rows.

    WHAT THIS DELIBERATELY DOES NOT CLAIM. Rotation does not give universal SIMULTANEOUS coverage;
    nothing can, under the key budget. It gives universal ELIGIBILITY with recorded, bounded gaps.
    A study that needs all 58 underlyings at one instant cannot be served by this and should be
    told so by the coverage record rather than discovering it in the data.
    """
    core: tuple[str, ...] = CORE_UNDERLYINGS
    core_fraction: float = 0.5          # share of the budget reserved for core, at depth
    slice_seconds: int = DEFAULT_SLICE_SECONDS
    rotating_per_slice: int = 8         # fallback only; cohort_size_for_budget derives the real one

    #: What "useful depth" actually costs, MEASURED rather than nominal. The selection policy
    #: nominally asks for 3 expiries x 8 strikes/side x {call,put} = 96 contracts, but running
    #: the real select_contracts against real production chains with the ceiling lifted returns
    #: 32 for 49 of the 55 enrolled names with a fresh chain (the other six are thinner:
    #: 16/20/24/26/28/30). So 32 is what an underlying needs to be described, not 96.
    useful_depth_contracts: int = 32

    def cohort_size_for_budget(self, rotating_budget: int) -> int:
        """How many non-core underlyings fit in a slice AT USEFUL DEPTH.

        DERIVED, not chosen — the same discipline contract_budget_from_key_limit applies to the
        contract ceiling. A fixed rotating_per_slice=8 against the real budget hands each name
        119//8 = 14 contracts, which is a permanent sliver: the exact failure this rotation was
        built to end, wearing the policy's own name. Depth is the invariant the operator asked
        for, so breadth-per-slice is what gives way, and the cycle length becomes a REPORTED
        consequence instead of a hidden one.
        """
        depth = max(1, int(self.useful_depth_contracts))
        return max(1, int(rotating_budget) // depth)

    def slice_index(self, at_epoch_s: float) -> int:
        """Which slice an instant falls in. A pure function of the clock, so two processes
        computing coverage for the same moment agree without coordinating."""
        return int(at_epoch_s // max(1, int(self.slice_seconds)))

    def describe(self) -> str:
        return (f"core {'/'.join(self.core)} always-on at {self.core_fraction:.0%} of budget; "
                f"remaining budget rotates {self.rotating_per_slice} non-core underlyings per "
                f"{self.slice_seconds}s slice")


def rotation_cohort(all_underlyings: Iterable[str], at_epoch_s: float,
                    policy: RotationPolicy | None = None) -> dict[str, Any]:
    """Which underlyings are eligible in the slice containing `at_epoch_s`.

    Deterministic and stateless: the cohort is a function of the sorted universe and the slice
    index, so replay can reconstruct exactly which underlyings were eligible at a past instant
    without consulting anything but the clock and the roster. The rotation walks the non-core
    list in order, wrapping — every non-core underlying is guaranteed a turn within
    ceil(n_non_core / rotating_per_slice) slices, which is reported so the gap is a known
    quantity rather than an emergent one.
    """
    pol = policy or RotationPolicy()
    core = [u for u in pol.core if u in set(all_underlyings)]
    non_core = sorted(set(all_underlyings) - set(pol.core))
    idx = pol.slice_index(at_epoch_s)

    cohort: list[str] = []
    if non_core:
        k = max(1, int(pol.rotating_per_slice))
        start = (idx * k) % len(non_core)
        for i in range(min(k, len(non_core))):
            cohort.append(non_core[(start + i) % len(non_core)])

    import math
    cycle_slices = math.ceil(len(non_core) / max(1, pol.rotating_per_slice)) if non_core else 0  # caps-ok: with no rotating symbols the rotation is genuinely zero slices long — an arithmetic identity about the policy, not a measurement standing in for missing data
    return {
        "slice_index": idx,
        "slice_seconds": pol.slice_seconds,
        "core": core,
        "rotating": cohort,
        "eligible": core + cohort,
        "non_core_total": len(non_core),
        "full_cycle_slices": cycle_slices,
        "full_cycle_seconds": cycle_slices * pol.slice_seconds,
        "policy": pol.describe(),
    }


def split_budget(total_contracts: int, n_core: int, n_rotating: int,
                 policy: RotationPolicy | None = None) -> dict[str, int]:
    """Split the contract budget between always-on core and the rotating cohort.

    Core gets a reserved share so its depth does not collapse when the cohort is large; the
    remainder goes to the cohort. Both halves are returned explicitly so the trade-off is visible
    in the subscription receipt rather than buried in arithmetic.
    """
    pol = policy or RotationPolicy()
    total = max(0, int(total_contracts))
    if n_core <= 0:
        return {"core": 0, "rotating": total}
    core_budget = int(total * float(pol.core_fraction))
    if n_rotating <= 0:
        return {"core": total, "rotating": 0}
    return {"core": core_budget, "rotating": total - core_budget}


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


def contract_budget_from_key_limit(*, equity_symbols: int = 1, book_enabled: bool = True,
                                   key_limit: int = SCHWAB_STREAM_KEY_LIMIT,
                                   margin: int = KEY_SAFETY_MARGIN) -> dict[str, Any]:
    """How many option CONTRACTS fit in the remaining streamer key budget.

    The arithmetic, stated so it can be checked rather than trusted:
      * the equity path holds `equity_symbols` x 3 keys — LEVELONE_EQUITIES, NASDAQ_BOOK and
        NYSE_BOOK are three separate services on the same symbol;
      * each option contract costs 1 key for LEVELONE_OPTIONS, plus 1 more for OPTIONS_BOOK
        when book depth is collected;
      * a margin is held back so a concurrent equity resubscribe cannot tip the account over.

    WHY THIS REPLACES A CHOSEN NUMBER. The previous ceiling of 240 was an arbitrary starting
    bound. Under the key model it happens to sit just under the limit when books are on
    (240x2 + 3 = 483), which is luck, not derivation — and it would have been silently WRONG the
    moment books were disabled (leaving ~477 keys unused) or the equity path subscribed more
    symbols. Deriving it means the ceiling tracks the real constraint instead of a guess.

    NOTE ON BOOKS. Collecting OPTIONS_BOOK halves contract coverage for the same budget. The
    rebuild plan reached the same trade-off for equities and resolved it as "sentinel-first
    books" — depth on a few names, quotes broadly. The same choice is available here and is the
    caller's; this function only reports the arithmetic.
    """
    equity_keys = max(0, int(equity_symbols)) * 3
    per_contract = 2 if book_enabled else 1  # caps-ok: Schwab key COST of a contract — LEVELONE_OPTIONS alone is 1 key, adding OPTIONS_BOOK makes it 2. A capacity constant of the subscription protocol, not a substituted market value.
    available = int(key_limit) - int(margin) - equity_keys
    allowed = max(0, available // per_contract)
    return {
        "key_limit": int(key_limit),
        "safety_margin": int(margin),
        "equity_keys_held": equity_keys,
        "keys_per_contract": per_contract,
        "keys_available_for_options": max(0, available),
        "contracts_allowed": allowed,
        "book_enabled": bool(book_enabled),
        "basis": "governance/CONSOLE_REBUILD_PLAN_CR_V1.md S3 streamer-capacity arithmetic "
                 "(documented bound, real accounting measured at CR-01)",
    }


def build_chains_for_selection(db_path: Any = None, *, max_age_s: float = 86_400.0,
                               tickers: Iterable[str] | None = None
                               ) -> dict[str, tuple[float | None, list[dict]]]:
    """Assemble {ticker: (spot, contracts)} from chains ALREADY FETCHED and persisted.

    Deliberately reads the most recent persisted snapshot per ticker rather than calling the
    vendor. Selection must not add REST load, and it must not become a second chain-fetch
    authority beside the one the console already runs — a second fetcher would drift from the
    first the moment either changed.

    Tickers whose newest snapshot is older than ``max_age_s`` are SKIPPED rather than streamed
    against a stale strike ladder: subscribing to yesterday's strikes around today's spot would
    quietly collect the wrong contracts and look like coverage.
    """
    import json as _json
    import sqlite3
    import time as _time

    if db_path is None:
        try:
            from db import DB_PATH as _DB
            db_path = _DB
        except Exception:                               # noqa: BLE001
            return {}

    cutoff = _time.time() - float(max_age_s)
    out: dict[str, tuple[float | None, list[dict]]] = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    except sqlite3.Error as e:
        log.warning("build_chains_for_selection: cannot open %s: %s", db_path, e)
        return {}
    try:
        rows = conn.execute(
            "SELECT s.ticker, s.spot, s.option_chain_json FROM snapshots s "
            "JOIN (SELECT ticker, MAX(ts_utc) AS mx FROM snapshots "
            "      WHERE option_chain_json IS NOT NULL AND ts_utc >= ? GROUP BY ticker) m "
            "  ON m.ticker = s.ticker AND m.mx = s.ts_utc "
            "WHERE s.option_chain_json IS NOT NULL", (cutoff,)).fetchall()
    except sqlite3.Error as e:
        log.warning("build_chains_for_selection query failed: %s", e)
        rows = []
    finally:
        conn.close()

    want = {str(t).upper() for t in tickers} if tickers else None
    for ticker, spot, blob in rows:
        if want is not None and str(ticker).upper() not in want:
            continue
        try:
            contracts = _json.loads(blob)
        except (TypeError, ValueError):
            continue
        if isinstance(contracts, list) and contracts:
            out[str(ticker)] = (float(spot) if spot is not None else None, contracts)
    log.info("build_chains_for_selection: %d ticker(s) with a chain newer than %.0fs",
             len(out), max_age_s)
    return out


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
            def _centred(x: dict) -> tuple:
                # RC-290 lesson, applied here: a contract with no strikePrice does not sit AT
                # strike 0, it has no distance from spot at all. `.get("strikePrice", 0)`
                # handed it a fabricated number that sorted it as maximally far below spot.
                # Rank presence first so an unreadable strike sorts after every real one
                # without being assigned a price it does not have.
                k = x.get("strikePrice")
                side = x.get("putCall")
                label = ""
                if isinstance(side, str):
                    label = side
                sym = _contract_symbol(x) or ""
                if isinstance(k, (int, float)):
                    return (0, abs(float(k) - spot), label, sym)
                # No strike means no distance from spot at all. Rank it after every real
                # strike rather than expressing "absent" as a number in either field.
                return (1, 0.0, label, sym)

            for c in sorted(group, key=_centred):
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
    """Drop option subscriptions without touching the equity/book ones.

    REPORTS PER SERVICE, and that is not cosmetic. This returned only `{requested, errors}` and
    swallowed every exception into that list, so it NEVER raised — a caller wrapping it in
    try/except could not detect failure at all, and the one in order_flow_streaming did exactly
    that: it closed the coverage epochs and dropped the contracts from its own list on a call
    that had failed at the vendor. The contracts stayed live, kept sending frames the record
    said were outside any epoch, and above all kept holding Schwab KEYS that nothing would ever
    release — a slow leak whose end state is the account past its key limit and the equity
    stream, which is what the console actually depends on, refused.

    `level_one` and `book` are True only when that service's unsubscribe was actually accepted,
    so a caller can release exactly what the vendor released and retry the rest.
    """
    syms = [s for s in dict.fromkeys(symbols) if s]
    out: dict[str, Any] = {"requested": len(syms), "level_one": False, "book": False,
                           "errors": []}
    if not syms:
        out["errors"].append("no symbols to unsubscribe")
        return out
    if stream_client is None:
        out["errors"].append("no stream client — cannot unsubscribe")
        return out
    for name, key in (("level_one_option_unsubs", "level_one"), ("options_book_unsubs", "book")):
        fn = getattr(stream_client, name, None)
        if fn is None:
            out["errors"].append(f"{name}: stream client has no such method")
            continue
        try:
            await fn(syms)
            out[key] = True
        except Exception as e:                      # noqa: BLE001
            out["errors"].append(f"{name}: {e}")
    return out
