"""The `confluence` panel: the Confluence matrix of one expiry, its key levels and its summary.

Read from State: the published levels (state.level_store), the price-level snapshot and the hold
counts (state.price_level_store), the 1-minute bars (state.bar_store), each option contract's
look-back record (app.options.order_flow.state) and the live price.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.options.order_flow.state import look_back
from calc.confluence_composite import (
    ASSUMPTION,
    FamilyVote,
    Matrix,
    StrikeLookBack,
    at_price,
    atm_iv_change,
    build_matrix,
    distance,
    expiry_flow,
    family_votes,
    implied_move,
    window_rows,
)
from calc.liquidity_value_engine import bars_from_candles, visits
from calc.math_exposure_core import Bucket, merge_exposure_books
from calc.math_levels import expiry_gamma
from calc.option_window import strike_look_back
from calc.terrain_engine import (
    OPTION_LEVELS,
    SAME_DAY_LEVELS,
    Book,
    ExpiryKey,
    TerrainSnapshot,
    nearest_strike,
)
from calc.terrain_read import (
    REGIME_NEGATIVE_GAMMA,
    REGIME_POSITIVE_GAMMA,
    REGIME_TEXT,
    REGIME_UNAVAILABLE,
)
from numeric_contract import dollars_text, iv_text, price_text
from option_contract import OptionContract
from push.answers import unavailable
from push.levels import pin_note
from push.liquidity import hold_text
from push.spot import price_mark, resolve_spot
from push.strike_rows import expiry_unreadable, window
from push.verdict import LevelsVerdict, terrain_staleness
from state import bar_store
from state.level_store import PublishedLevels, published_levels
from state.price_level_store import canonical_price_level_snapshot, materialize_hold_counts
from time_et import ET, age_text, ct_label, option_close_product, sessions, time_to_expiry_years

#: the look-back windows the page offers (decision 11): minutes, or since the regular open; each
#: column of the look-back follows the one chosen
LOOKBACKS = {
    "1": "1 min",
    "3": "3 min",
    "5": "5 min",
    "15": "15 min",
    "30": "30 min",
    "60": "60 min",
    "open": "since the open",
}
#: the window the matrix opens on (decision 11)
DEFAULT_LOOKBACK = "5"
#: why "since the open" has no window yet
NOT_OPEN = "the regular session has not opened"


def _window_start(choice: str, now: datetime) -> int | None:
    """Return the look-back's first whole minute (minutes since the epoch), or None.

    `choice` minutes before the minute `now` is in, so a window covers at least that long, as a
    bar does; "open": the minute the regular session opened, today's as Schwab's /markets sent
    it. None before that open, or with no regular session held for the day.
    """
    minute = int(now.timestamp() // 60)
    if choice != "open":
        return minute - int(choice)
    held, day = sessions(), now.astimezone(ET).date().isoformat()
    if day not in held or not held[day].regular or now < held[day].regular[0][0]:
        return None
    return int(held[day].regular[0][0].timestamp() // 60)


def _window_open(tk: str, start: int | None) -> float | None:
    """Return the open of Schwab's 1-minute bar of the look-back's first minute; None: not held."""
    if start is None:
        return None
    bars = bar_store.bars_1m(tk, bar_store.BARS_KEPT)
    return next((c.open for c in bars if c.ts == start * 60.0), None)


def _looks(
    contracts: list[OptionContract], now: datetime, start: int | None
) -> dict[float, StrikeLookBack] | None:
    """Each strike's readings over the look-back from minute `start`; None: no window."""
    if start is None:
        return None
    by_strike: dict[float, list[OptionContract]] = {}
    for c in contracts:
        if c.strike is not None and c.symbol:
            by_strike.setdefault(float(c.strike), []).append(c)
    held = look_back(
        [c.symbol for c in contracts if c.symbol], now.astimezone(ET).date().isoformat(), start
    )
    return {s: strike_look_back(cs, held) for s, cs in by_strike.items()}


def _expiry_order(item: tuple[str, float | None]) -> tuple[int, float, str]:
    """Known days-to-expiration first, then the date. A missing count sorts last."""
    dte = item[1]
    if isinstance(dte, (int, float)):
        return (0, float(dte), item[0])
    return (1, 0.0, item[0])


def _confluence_expiries(books: dict[ExpiryKey, Book]) -> list[dict[str, Any]]:
    """Each expiry of the chain with Schwab's daysToExpiration, the key of its book."""
    found = {str(exp)[:10]: dte for exp, dte in books if exp}
    return [{"expiry": exp, "dte": dte} for exp, dte in sorted(found.items(), key=_expiry_order)]


#: The matrix's key levels: only those institutions have a mechanical reason to trade at
#: (docs/derived_register.md "Confluence key levels"). From the chain, where options dealers'
#: hedging turns and concentrates (Gamma Flip, Gamma Call, Gamma Put, Gamma Total) and the pin
#: of the expiry settling today (OI Pin); the first four's same-day copies only on the chosen
#: expiry's own day, where the pinning evidence is. From the session, the execution desks'
#: benchmarks: VWAP and the prior close.
_KEY_OPTION_IDS = ("gamma_flip", "call_wall", "put_wall", "absolute_gamma_strike")
KEY_OPTION_LEVELS = tuple(
    level for level in OPTION_LEVELS if level[0] in (*_KEY_OPTION_IDS, "pin_candidate")
)
KEY_SAME_DAY_LEVELS = tuple(level for level in SAME_DAY_LEVELS if level[0] in _KEY_OPTION_IDS)
KEY_SESSION_LEVELS = ("VWAP", "PDC")
#: the one key level with a measured hold rate (calc.liquidity_value_engine.HOLD_LEVELS); VWAP
#: moves during the session and is not measured, and the option levels get no rate (decision 34)
HOLD_MEASURED = "PDC"
NO_HOLD_RECORD = "hold rate: no record yet"
#: an answer with no matrix places no level
NO_LEVELS: dict[str, list[Any]] = {"levels_above": [], "levels_below": []}


def _hold_rate(tk: str, now: datetime) -> str:
    """Return the prior close's hold rate at 15 and 30 minutes, as the Liquidity page words it."""
    counts = materialize_hold_counts(
        tk,
        bars_from_candles(bar_store.bars_1m(tk, bar_store.BARS_KEPT)),
        daily=bar_store.series(tk, "1d"),
        now=now,
    )[HOLD_MEASURED]
    return f"hold rate: {hold_text(counts[15])} [30 min: {hold_text(counts[30])}]"


def _confluence_markers(
    live: TerrainSnapshot, tk: str, now: datetime, expiry_day: bool
) -> list[dict[str, Any]]:
    """Return the key levels of this priced snapshot and of the session's published levels.

    Each with its hold rate's words (`hold_text`). `expiry_day`: the chosen expiry settles
    today, so the same-day levels are its own.
    """
    markers: list[dict[str, Any]] = []
    snap = canonical_price_level_snapshot(tk, now)
    if snap is not None:
        for lid, value in snap.levels.items():
            if lid in KEY_SESSION_LEVELS:
                row = value.to_contract_dict()
                markers.append(
                    {
                        "short": row["short"],
                        "title": row["label"],
                        "lane": "session",
                        "price": row["price"],
                        "hold_text": _hold_rate(tk, now) if lid == HOLD_MEASURED else None,
                    }
                )
    named = [(label, live.level(gid)) for gid, label in KEY_OPTION_LEVELS]
    if expiry_day:
        named += [("0DTE " + label, live.same_day[gid]) for gid, label in KEY_SAME_DAY_LEVELS]
    markers += [
        {"short": label, "title": label, "lane": "options", "price": price, "hold_text": None}
        for label, price in named
        if price is not None
    ]
    return markers


def _screen_levels(
    markers: list[dict[str, Any]], spot: float | None, sigma_root_t: float | None
) -> list[dict[str, Any]]:
    """Each level at its own price, with its distance from the live price.

    The page does not move a level onto a strike: its tag says its own price (`text`), and its
    hover its name and hold rate.
    """
    levels: list[dict[str, Any]] = []
    for marker in markers:
        price = marker.get("price")
        if not isinstance(price, (int, float)):
            continue
        shown = price_text(price)
        hold = marker["hold_text"] or NO_HOLD_RECORD
        levels.append(
            {
                "lane": marker["lane"],
                "abbrev": marker["short"],
                "price": float(price),
                "price_text": shown,
                "title": marker["title"],
                "text": f"{marker['short']} {shown}",
                "hover": f"{marker['title']} {shown} · {hold}",
                **distance(float(price), spot, sigma_root_t),
            }
        )
    return levels


def _tags(levels: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Place each key level against the shown strike rows (highest strike first).

    A level inside the rows is a tag on the row of the strike nearest its price (the lower one on
    a tie; decision 64, O-5), with its own price (`rows`, each with its `tags`);
    `levels_above` / `levels_below`: the levels past the rows, in the levels' order. With no
    rows nothing is inside, above or below. Pure: the rows given are not changed.
    """
    if not rows:
        return {"rows": [], **NO_LEVELS}
    strikes = [r["strike"] for r in rows]
    top, bottom = strikes[0], strikes[-1]
    tags: dict[float, list[dict[str, Any]]] = {s: [] for s in strikes}
    for lv in levels:
        at = nearest_strike(strikes, lv["price"]) if bottom <= lv["price"] <= top else None
        if at is not None:
            tags[at].append(lv)
    return {
        "rows": [{**r, "tags": tags[r["strike"]]} for r in rows],
        "levels_above": [lv for lv in levels if lv["price"] > top],
        "levels_below": [lv for lv in levels if lv["price"] < bottom],
    }


def _book(snap: TerrainSnapshot, chosen: str) -> dict[float, Bucket]:
    """Return the exposure book of one expiry of `snap`: its books merged (none: no strike)."""
    selected = [book for key, book in snap.books.items() if str(key[0])[:10] == chosen]
    return selected[0][0] if len(selected) == 1 else merge_exposure_books(selected)[0]


def _matrix(
    tk: str,
    published: PublishedLevels,
    priced: tuple[float, datetime],
    chosen: str,
    now: datetime,
    start: int | None,
) -> Matrix:
    """Return the readings of one expiry of a priced chain: the one the matrix request shows.

    `priced`: the price and the instant the snapshot was priced at; `chosen` is an expiry of the
    snapshot's books (_confluence_expiries); its gamma if the price were at each strike, priced
    at that same instant (calc.math_levels.expiry_gamma, for this expiry alone); its book on the
    prior day (None, no prior day held; an expiry that day does not list: every strike new); the
    regular session's visits at each strike so far; each strike over the look-back from minute
    `start` (_looks).
    """
    snap, prior_day = published.snap, published.prior_day
    exposures = _book(snap, chosen)
    prior = None if prior_day is None else _book(prior_day, chosen)
    bars = bars_from_candles(bar_store.bars_1m(tk, bar_store.BARS_KEPT))
    contracts = [c for c in published.chain if c.expiry == chosen]
    gamma = expiry_gamma(
        [c for c in published.priced_chain if c.expiry == chosen],
        priced[1],
        sessions=sessions(),
        product=option_close_product(tk),
    )
    return build_matrix(
        exposures,
        snap.charm_by_expiry[chosen],
        snap.iv_by_expiry[chosen],
        priced[0],
        gamma,
        prior,
        visits(bars, sorted(exposures), now, sessions()),
        _looks(contracts, now, start),
    )


def _sigma_root_t(published: PublishedLevels, tk: str, expiry: str, now: datetime) -> float | None:
    """Return the expiry's one implied move (calc.confluence_composite.implied_move), or None.

    The volatility is the expiry's own (TerrainSnapshot.atm_iv_pct_by_expiry, a percent); the
    time is to its settlement at `now`, in years, by the one clock (time_et.time_to_expiry_years)
    from each of its contracts' expirationDate and settlementType as Schwab sent them. None when
    either is not known, or when the expiry's contracts settle at different times (an AM and a
    PM index series on one date): the expiry then has no one time left.
    """
    held, product = sessions(), option_close_product(tk)
    times = {
        time_to_expiry_years(
            c.expiration, now, sessions=held, settlement_type=c.settlement, product=product
        )
        for c in published.chain
        if c.expiry == expiry and c.expiration is not None
    }
    t = times.pop() if len(times) == 1 else None
    return implied_move(published.snap.atm_iv_pct_by_expiry[expiry], t)


def _chain_status(verdict: LevelsVerdict, fetched: float, now: float) -> str:
    """Return the matrix's status line: the levels' word, the chain's time and age, and why."""
    parts = [
        verdict["levels_state"],
        f"chain as of {ct_label(fetched)}, {age_text(now - fetched)} old",
    ]
    if verdict["levels_stale_reason"]:
        parts.append(verdict["levels_stale_reason"])
    return " · ".join(parts)


#: the kind of move the options' gamma at the price makes, the read the research supports (true
#: positions: Ni, Pearson, Poteshman and White 2021; Baltussen, Da, Lammers and Martens 2021;
#: Adams and co-authors 2026 for same-day options), as (headline, tone, what the hedging does),
#: by every regime the levels serve: none while the gamma at the price is not known
KIND_OF_MOVE: dict[str, tuple[str, str, str] | None] = {
    REGIME_NEGATIVE_GAMMA: (
        "Wider, continuing moves",
        "neg",
        "the hedging chases moves instead of absorbing them: larger ranges, follow-through, and "
        "continuation late in the day",
    ),
    REGIME_POSITIVE_GAMMA: (
        "Calmer, reverting moves",
        "pos",
        "the hedging absorbs moves: smaller ranges and more reversals",
    ),
    REGIME_UNAVAILABLE: None,
}
#: what every reading of direction says until its record passes the test of decision 56
UNTESTED = "untested · direction words wait for 20 ordinary sessions and the test (decision 56)"


#: each family's card: its title, and what it says it read
FAMILY_TITLES = {
    "positioning": "POSITIONING (OPEN INTEREST, GREEKS)",
    "option trades": "OPTION TRADES · HEDGING FLOW",
    "volatility": "VOLATILITY · AT THE MONEY",
    "stock book": "STOCK BOOK AND TAPE",
}
#: a vote in words: +1 wider and continuing, -1 calmer and reverting
VOTE_WORDS = {1: "votes wider, continuing", -1: "votes calmer, reverting"}
VOTE_TONE = {1: "neg", -1: "pos"}
NOT_VOTED = {
    "positioning": "the gamma at the price is not known",
    "option trades": "the look-back's hedging flow or price move is not known, or is zero",
    "volatility": "the look-back's at-the-money volatility change is not known, or is zero",
    "stock book": "not measured on the matrix yet",
}


def _family_text(vote: FamilyVote) -> str:
    """Return what one family read, in words: its reading and its vote."""
    if vote.vote is None:
        return NOT_VOTED[vote.family]
    words = VOTE_WORDS[vote.vote]
    if vote.family == "positioning":
        sign = "Negative" if vote.vote == 1 else "Positive"
        return f"{sign} gamma at the price: {words}"
    if vote.family == "option trades":
        side = "with" if vote.vote == 1 else "against"
        return f"Hedging flow {dollars_text(vote.reading)} {side} the look-back's move: {words}"
    return f"At-the-money IV {_signed_text(vote.reading)} in the look-back: {words}"


def _signed_text(n: float | None) -> str | None:
    return None if n is None else f"{n:+.2f}"


def _headline(live: TerrainSnapshot, votes: tuple[FamilyVote, ...]) -> dict[str, Any]:
    """Return the Composite's headline: the kind of move the gamma at the price makes, est.

    With each family's card and how many of those measured agree with it, every one untested.
    """
    families = [
        {
            "title": FAMILY_TITLES[v.family],
            "text": _family_text(v),
            "tone": None if v.vote is None else VOTE_TONE[v.vote],
        }
        for v in votes
    ]
    kind = KIND_OF_MOVE[live.regime]
    measured = [v for v in votes if v.vote is not None]
    agree = sum(v.vote == votes[0].vote for v in measured)
    return {
        "text": None if kind is None else kind[0],
        "tone": None if kind is None else kind[1],
        "note": GAMMA_UNKNOWN if kind is None else _kind_note(live, kind[2]),
        "record": UNTESTED,
        "families": families,
        "grade_text": None
        if kind is None
        else f"{agree} of {len(measured)} families measured agree, one equal vote each",
    }


#: why the headline has no kind of move
GAMMA_UNKNOWN = "the gamma at the price is not known"


def _kind_note(live: TerrainSnapshot, effect: str) -> str:
    """Return what the gamma at the price does, in words, and the price's side of the flip."""
    note = (
        f"The options' gamma at the price is {REGIME_TEXT[live.regime].lower()} ({ASSUMPTION}), "
        f"so {effect}."
    )
    flip = price_text(live.gamma_flip)
    side = "below" if live.regime == REGIME_NEGATIVE_GAMMA else "above"
    return note if flip is None else f"{note} The price is {side} the Gamma Flip ({flip})."


def _cards(
    body: dict[str, Any],
    live: TerrainSnapshot,
    chosen: str,
    sigma_root_t: float | None,
) -> list[dict[str, Any]]:
    """Return the summary's cards, each its label, value, line beneath, tone and hover."""
    spot = body["spot"]
    flip = distance(live.gamma_flip, spot, sigma_root_t) if live.gamma_flip else None
    pin = distance(live.pin_candidate, spot, sigma_root_t) if live.pin_candidate else None
    kind = KIND_OF_MOVE[live.regime]
    tone = None if kind is None else kind[1]
    minutes = live.pin_minutes_to_close
    return [
        {
            "label": "SPOT",
            "value": body["spot_text"],
            "sub": body["spot_not_live_text"]
            or (f"Schwab last trade {body['spot_time_ct']}" if body["spot_time_ct"] else None),
            "tone": None,
            "hover": None,
        },
        {
            "label": "GAMMA REGIME",
            "value": REGIME_TEXT[live.regime],
            "sub": "est. · the convention's sign",
            "tone": tone,
            "hover": f"The sign of the whole book's net gamma at the price, on {ASSUMPTION}.",
        },
        {
            "label": "GAMMA FLIP",
            "value": price_text(live.gamma_flip),
            "sub": None
            if flip is None
            else " · ".join(
                t for t in (flip["distance_text"], flip["sigma_text"], "model · whole book") if t
            ),
            "tone": None,
            "hover": "The modelled price where the whole book's net gamma changes sign; no "
            "published test of it as a level.",
        },
        {
            "label": "OI PIN (EXPIRY DAY)",
            "value": price_text(live.pin_candidate),
            "sub": None
            if pin is None or minutes is None
            else " · ".join(
                t
                for t in (
                    pin["distance_text"],
                    pin["sigma_text"],
                    f"{minutes:.0f} min to the close",
                )
                if t
            ),
            "tone": None,
            "hover": None
            if pin is None
            else f"{pin_note(live)} Size, not direction: about one more close in a hundred lands "
            "on it for single stocks; none found for ETFs or same-day options (Ni, Pearson and "
            "Poteshman 2005).",
        },
        {
            "label": f"AT-THE-MONEY IV · {chosen}",
            "value": iv_text(live.atm_iv_pct_by_expiry[chosen]),
            "sub": "derived · the two strikes the price is between",
            "tone": None,
            "hover": "The chosen expiry's at-the-money volatility: the mean of Schwab's volatility "
            "at the two strikes the price lies between (docs/derived_register.md).",
        },
    ]


def confluence(tk: str, now: datetime, params: dict[str, Any]) -> dict[str, Any]:
    """Return the `confluence` panel at the page's one expiry choice (`params["expiry"]`).

    Over the look-back the page chose (`params["lookback"]`, one of LOOKBACKS; none or another:
    DEFAULT_LOOKBACK).
    """
    unreadable = expiry_unreadable(params)
    if unreadable is not None:
        return unavailable(tk, unreadable, **NO_LEVELS)
    chosen = params.get("lookback")
    lookback = chosen if isinstance(chosen, str) and chosen in LOOKBACKS else DEFAULT_LOOKBACK
    return confluence_payload(tk, params["expiry"], now, lookback)


def _lookback(choice: str, start: int | None) -> dict[str, Any]:
    """Return the look-back as served: the choice, the choices and the window's start in words."""
    return {
        "chosen": choice,
        "choices": [{"key": k, "text": t, "on": k == choice} for k, t in LOOKBACKS.items()],
        "start_text": None if start is None else f"since {ct_label(start * 60.0)}",
        "reason": NOT_OPEN if start is None else None,
    }


def confluence_payload(
    tk: str, expiry: str | None, now: datetime, lookback: str = DEFAULT_LOOKBACK
) -> dict[str, Any]:
    """Return the matrix of the priced chain, for the expiry and look-back the operator picks.

    `expiry`: the page's one expiry choice. None (All Expirations) is the front expiry still open.
    An expiry the chain does not list as open is answered with why, never another expiry's
    matrix. `lookback`: one of LOOKBACKS.
    """
    published = published_levels(tk)
    priced_at = None if published is None else published.snap.spot
    valued_at = None if published is None else published.snap.valued_at
    if published is None or not published.snap.books or priced_at is None or valued_at is None:
        return unavailable(tk, "no priced chain is held for this ticker", **NO_LEVELS)
    live = published.snap
    today = now.strftime("%Y-%m-%d")
    listed = [e for e in _confluence_expiries(live.books) if e["expiry"] >= today]
    if not listed:
        return unavailable(tk, "no expiry on this chain is still open", **NO_LEVELS)
    chosen = expiry
    if chosen is None:
        # All Expirations: the matrix reads one expiry, the front one still open
        live_listed = [e for e in listed if e["dte"] is not None and e["dte"] >= 0]
        chosen = (live_listed or listed)[0]["expiry"]
    match = next((e for e in listed if e["expiry"] == chosen), None)
    if match is None or match["dte"] is None:
        absent = match is None
        reason = (
            f"the chain lists no open contracts for {chosen}"
            if absent
            else "that expiry did not carry days to expiration"
        )
        return unavailable(tk, reason, expiry=chosen, **NO_LEVELS)
    start = _window_start(lookback, now)
    stored = _matrix(tk, published, (priced_at, valued_at), chosen, now, start)
    fetched = published.computed_ts_utc
    live_spot, _src, live_ts = resolve_spot(tk, now=now.timestamp())
    sigma_root_t = _sigma_root_t(published, tk, chosen, now)
    markers = _confluence_markers(live, tk, now, chosen == today)
    levels = _screen_levels(markers, live_spot, sigma_root_t)
    strikes = stored.strikes
    lo, hi, view = window(strikes, nearest_strike(strikes, live_spot), "auto", None, 0)
    body: dict[str, Any] = {
        "notes": [note for note in (view["note"],) if note is not None],
        "peaks": stored.peaks,
        "rows": window_rows(stored, strikes[lo : hi + 1]),
    }
    body.update(at_price(body["rows"], strikes, live_spot, sigma_root_t))
    body.update(
        {
            "ticker": tk,
            "available": True,
            "reason": None,
            "expiry": chosen,
            # the distances and the price row are from the live price: its mark
            **price_mark(tk, live_ts, now.timestamp()),
            # the levels' one verdict (terrain_staleness): its word, the chain's time and age,
            # and why when it is not LIVE or CLOSE (AGENTS rule 5)
            "status_text": _chain_status(
                terrain_staleness(fetched, tk, now=now.timestamp()), fetched, now.timestamp()
            ),
            **_tags(levels, body["rows"]),
            "headline": _headline(
                live,
                family_votes(
                    live.net_gex_at_spot,
                    expiry_flow(stored),
                    (_window_open(tk, start), live_spot),
                    atm_iv_change(stored, live_spot),
                ),
            ),
            "lookback": _lookback(lookback, start),
        }
    )
    body["cards"] = _cards(body, live, chosen, sigma_root_t)
    return body
