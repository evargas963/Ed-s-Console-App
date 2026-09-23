"""Chain-width authority: how many strikes (and over what date window) every level-feeding
Schwab option-chain fetch asks for. Extracted from server.py (RC-REHAB-1, 2026-09-23,
thirty-eighth slice) as one unit: the strike-count floor/ceiling/cold-start constants, the
vendor contract budget, the index DTE horizon, the learned per-instrument geometry
(spot + strike increment + expiry count, guarded by one lock), and the four functions that
read or write it -- _learn_strike_geometry, resolve_chain_strike_count (RC-59: THE width
faucet), _chain_to_date_for / _chain_from_date_for (RC-494 / Cursor-audit F2 date bounds).

Nothing here touches a server.py runtime object; the geometry dicts are mutated in place
(never rebound), so server.py's re-export of them is the same object tests and the terrain
producer read. Callers that monkeypatch `server._terrain_strike_count` /
`server._learn_strike_geometry` keep working because their consumers (terrain_refresh,
server_state_intake) read those names through `server` at call time.
"""
from __future__ import annotations

import threading
from datetime import date

from instrument_identity import ticker_storage_key
from math_exposure import infer_strike_increment, required_strike_count

# Strike count is DERIVED per instrument, never tabulated — see math_levels.
# required_strike_count(). The bar is the flip's +/-5% span requirement
# (GAMMA_FLIP_MIN_SPAN_PCT); how many strikes that takes depends on the instrument's own
# strike spacing, so it is computed from measured geometry rather than assumed.
#
# MEASURED 2026-07-20 across 52 stored chains: the previous hardcoded table was wrong in
# BOTH directions — $SPX needed 150 and got 40; IWM needed 30 and got 80; ~48 equities
# needed under 20 and got 40. Over-fetching is not free: it saturates the 2-slot chain
# gate (observed starving the operator card at the open) and every payload is persisted
# twice (RC-6).
#: Floor. Below this, wall/pin selection has too few strikes to be meaningful regardless
#: of what the span arithmetic asks for; it is also the live UI's own chain width.
TERRAIN_STRIKE_COUNT_MIN: int = 20
#: Ceiling, set by the VENDOR not by us. Schwab returned HTTP 502 for SPY/QQQ at
#: strikeCount=200 at the 2026-07-20 open; 100 was observed working the same session.
#: A ticker whose requirement exceeds this is fetched at the ceiling and honestly reports
#: LOW_CONFIDENCE_NARROW_CHAIN rather than pretending.
#: RAISED 100 -> 120, MEASURED 2026-07-26 by `python tools/probe_chain_depth_v1.py` against the
#: live vendor (the previous 100 was an ASSUMPTION: 200 had 502'd and nothing between was tried).
#: Ladder result: SPY 120 OK / 150 -> HTTP 502; QQQ 120 OK / 150 -> 502; IWM OK to 250 (saturates
#: at 246 distinct strikes = its whole chain). 120 is therefore the highest UNIVERSALLY safe
#: request. What it delivers is far wider than the span bar suggests, because strikeCount applies
#: PER EXPIRY across ~35 expiries: SPY at 120 returned 259 distinct strikes spanning -40.5%/+44.8%
#: of spot (8,118 contracts), vs 219 strikes / -33.7%/+33.3% at 100.
#: KNOWN GAP: $SPX 502s even at 100, so it is not truncated — it fails outright and needs its own
#: LOWER ladder probe (RC-63); raising this ceiling does not help it.
TERRAIN_STRIKE_COUNT_MAX: int = 120
#: Used only until this ticker's geometry is known. The prewarm seeds geometry from
#: stored chains, so this normally applies to a ticker we have never seen.
TERRAIN_STRIKE_COUNT_COLD_START: int = 40

#: ticker -> (spot, strike_increment), learned from chains we have already fetched.
_strike_geometry: dict[str, tuple[float, float]] = {}
_strike_geometry_lock = threading.Lock()
#: ticker -> distinct expiry count, learned the same way (guarded by the same lock).
_strike_expiry_count: dict[str, int] = {}

#: RC-63 — the vendor's REAL limit, MEASURED 2026-07-26 (`python tools/probe_chain_depth_v1.py`).
#: Schwab caps the number of CONTRACTS in a chain response, not strikeCount: SPY returned 8,118
#: contracts at strikeCount=120 and HTTP 502 at 150; QQQ 7,894 at 120 then 502; $SPX 502'd at 80
#: with only 60 working (6,950 contracts) purely because it lists 55 expiries vs SPY's 35; IWM
#: never failed even at 250 because its whole chain is 5,492. So a single global strikeCount
#: ceiling is structurally wrong — it starves wide-expiry instruments and under-fetches narrow
#: ones.
#: VALUE CHOSEN BY BACK-TEST against those four measured ceilings, not by picking a round number:
#: `strikeCount * 2 * expiries` UNDER-predicts the real payload for some instruments ($SPX
#: returned 6,950 contracts where the estimate said 6,600), so a budget tuned to the largest
#: success (SPY's 8,118) would have allowed $SPX 72 — above its measured 502 threshold of 60.
#: 6,600 is the largest budget that reproduces EVERY measured ceiling without exceeding one:
#: SPY 94 (safe vs 120), QQQ 97 (vs 120), $SPX 60 (exactly its max), IWM 100 (vs 250).
#: Deliberately conservative: a 502 returns NO chain at all, while a slightly narrower request
#: still delivers far more than the span bar needs (SPY at 94 still spans ~±31% of spot).
SCHWAB_CHAIN_CONTRACT_BUDGET: int = 6600
#: Index option books ($SPX, $VIX, $RUT, $NDX, ...) list expirations out for YEARS (daily +
#: weekly + monthly + LEAPS), far more than the contract budget allows at any usable strike
#: width — RC-491 measured $SPX still 502 even at width 33 (33 * 2 * ~150 expiries = 9,900 >
#: 6,600). RC-494: the _fetch_state chain is therefore fetched only out to a bounded DTE
#: horizon (_chain_to_date_for → to_date), which caps the expiry count so a FIXED, generous
#: strike width fits the budget deterministically (no geometry feedback loop, RC-149).
#: SCOPE (verified 2026-08-25 — SAFE on all six semantics): this bound is correct ONLY for the
#: _fetch_state path, which slices the chain to a SINGLE (front) expiry before any gamma/flip/
#: pin/vanna/charm math runs, so the far expiries it drops were already discarded. It must NOT
#: be wired into the TERRAIN producer (_terrain_refresh_one): terrain is a deliberate
#: MULTI-EXPIRY aggregate over the FULL book (dealers hedge the whole delta book across weekly/
#: monthly expiries), so bounding it to 45d WOULD silently drop real gamma/flip/pin/wall/charm
#: contributions. Terrain keeps its own full→120d→45d ladder (to_date=None first rung).
#: 60 strikes * 2 * ~34 expiries in 45 days = ~4,080 < 6,600 (safe even at 55 expiries).
INDEX_CHAIN_DTE_HORIZON_DAYS: int = 45
INDEX_CHAIN_STRIKE_COUNT: int = 60


def _learn_strike_geometry(ticker: str, contracts: list | None, spot: float | None,
                           *, date_window_narrowed: bool = False) -> bool:
    """Remember this instrument's spot and strike spacing from a chain we just read.

    Returns True when a geometry was stored, so callers can count outcomes without
    reading the shared dict outside the lock (Cursor audit 2026-07-20: the seed loop
    compared len() across calls unlocked while workers mutate under the lock).

    RC-149 — `date_window_narrowed` exists because the expiry count is the DENOMINATOR of the
    width budget, and learning it from a date-narrowed chain inverts the safety it provides.
    A `to_date`-limited fetch returns only the expiries inside that window, so n_exp comes back
    SMALL; a small n_exp makes `resolve_chain_strike_count` compute a LARGER ceiling; the next
    cycle then asks for that wider chain over the FULL date range and blows the contract budget.
    The narrower the rung that rescued us, the more certain the next request is to fail — a
    feedback loop that cannot recover on its own. MEASURED 2026-07-30: $SPX's last success was
    on `chain_basis: dte<=120` with contracts_used 6785, and every fetch after it returned
    HTTP 502 for 2h10m. A narrowed chain's count is a FLOOR, never the truth, so it may seed an
    unknown instrument but must never overwrite a full-basis measurement.
    """
    tk = (ticker or "").upper().strip()
    if not tk or not contracts or spot is None or spot <= 0:
        return False
    incr = infer_strike_increment(contracts)
    if incr is None:
        return False
    # RC-63: also learn how many EXPIRIES this instrument lists. The vendor's real limit is on
    # the number of CONTRACTS returned, and contracts ~= strikeCount * 2 * expiries — so the
    # safe strikeCount depends on the expiry count, not on the ticker.
    n_exp = len({str(c.get("expirationDate"))[:10] for c in contracts
                 if isinstance(c, dict) and c.get("expirationDate")})
    with _strike_geometry_lock:
        _strike_geometry[tk] = (float(spot), float(incr))
        if n_exp > 0:
            if not date_window_narrowed:
                _strike_expiry_count[tk] = n_exp
            else:
                # a floor: raise a missing/too-low count, never lower a full-basis one
                _strike_expiry_count[tk] = max(_strike_expiry_count.get(tk, 0), n_exp)
    return True


def resolve_chain_strike_count(ticker: str) -> int:
    """THE strike-count faucet — one authority for EVERY chain fetch that feeds level math.

    RC-59: the console/analytics path (`_fetch_state`) and the terrain path used to size their
    chains differently — `_fetch_state` on a hardcoded CHAIN_STRIKE_COUNT=20 ("keep fast") and
    terrain on measured geometry — so the SAME ticker was analysed at two widths and the levels
    persisted to `snapshots` were narrower than the ones served on screen. Two widths is two
    answers; the width is now derived HERE and nowhere else.

    Right-sizing is not "always wider": MEASURED across 52 stored chains 2026-07-20, the old fixed
    count was wrong in BOTH directions — ~48 equities need UNDER 20 and were fetched at 40, while
    $SPX needs ~150 and got 40. Routing the console through this faucet therefore makes most
    tickers CHEAPER, not more expensive, and widens only where the +/-5% span requires it.

    Fail-closed: unknown geometry returns the cold-start default rather than a guessed width.
    The MAX is a VENDOR limit, not ours (Schwab 502s above it) — a ticker needing more is fetched
    at the ceiling and its levels self-report LOW_CONFIDENCE_NARROW_CHAIN rather than pretending.
    """
    tk = ticker_storage_key(ticker)   # Cursor-audit F1: bare index root ("SPX") -> "$SPX" so the
    #                                   faucet can't be bypassed by an un-normalized caller.
    if tk.startswith("$"):   # canonical index roots: $SPX/$VIX/$RUT/$NDX/$DJI
        # RC-494: index books are fetched over a bounded DTE horizon (_chain_to_date_for), so a
        # FIXED budget-safe width covers the whole near-term surface. Deterministic on purpose —
        # letting learned geometry drive the width recreated the RC-149 full-book feedback loop
        # that kept $SPX 502-ing. Paired with the to_date bound this is always well under budget.
        return INDEX_CHAIN_STRIKE_COUNT
    with _strike_geometry_lock:
        geom = _strike_geometry.get(tk)
        n_exp = _strike_expiry_count.get(tk)
    if geom is None:
        return TERRAIN_STRIKE_COUNT_COLD_START
    need = required_strike_count(geom[0], geom[1])
    if need is None:
        return TERRAIN_STRIKE_COUNT_COLD_START
    ceiling = TERRAIN_STRIKE_COUNT_MAX
    if n_exp and n_exp > 0:
        # RC-63: respect the VENDOR's contract budget, which is what actually 502s. A chain
        # returns ~ strikeCount * 2 (call+put) * expiries contracts, so an instrument listing 55
        # expiries ($SPX) must request a far smaller strikeCount than one listing 35 (SPY) to
        # return the same payload. Deriving the ceiling per ticker replaces a global constant
        # that was simultaneously too high for $SPX (502) and too low for everything else.
        ceiling = min(ceiling, max(TERRAIN_STRIKE_COUNT_MIN,
                                   SCHWAB_CHAIN_CONTRACT_BUDGET // (2 * n_exp)))
    return max(TERRAIN_STRIKE_COUNT_MIN, min(ceiling, need))


#: Back-compat alias — terrain's original name for the same authority.
_terrain_strike_count = resolve_chain_strike_count


def _chain_to_date_for(ticker: str, selected_expiry: str | None = None) -> date | None:
    """Bounded chain to_date as a `datetime.date` for index books, None for equities.

    RC-494: index option books ($SPX/$VIX/$RUT/...) list expirations out for years; fetching
    the FULL book blows Schwab's contract budget at any usable strike width (the $SPX 502).
    Capping the fetch to the near-term DTE horizon bounds the expiry count so
    resolve_chain_strike_count's fixed index width fits the budget. Equities return None (full
    book, unchanged). One authority for the index date bound, mirroring the strike-count faucet.

    If a caller EXPLICITLY selects a far-dated index expiry (beyond the horizon), to_date is
    extended to it — otherwise the downstream slice to that expiry would be empty and error
    (RC-494 robustness). Cursor-audit F2: extending to_date ALONE turned a one-expiry request
    into a today->far multi-expiry sweep (Schwab returns every expiry up to to_date), re-blowing
    the budget. The companion _chain_from_date_for bounds the NEAR edge to the same far date for
    that case, so the window is [sel, sel] — a single expiry (60*2=120 contracts). The auto/default
    path passes no expiry and gets the open-near-end horizon."""
    tk = ticker_storage_key(ticker)   # Cursor-audit F1: bare index root ("SPX") -> "$SPX"
    if not tk.startswith("$"):
        return None
    from datetime import date, timedelta

    from time_et import now_et

    horizon = (now_et() + timedelta(days=INDEX_CHAIN_DTE_HORIZON_DAYS)).date()
    if selected_expiry:
        try:
            sel = date.fromisoformat(str(selected_expiry)[:10])
            if sel > horizon:
                # RC-496: return the date OBJECT, not `.isoformat()`. schwab-py's
                # get_option_chain formats the date itself and _assert_type-rejects a
                # str (ValueError: expected datetime.date, got builtins.str), so the old
                # ISO-string return crashed every $-index chain fetch at the vendor
                # boundary. The sibling terrain ladder already passed a `.date()`, which
                # is why only the _fetch_state/enroll/charm paths went dark, not terrain.
                return sel
        except ValueError:
            pass
    return horizon


def _chain_from_date_for(ticker: str, selected_expiry: str | None = None) -> date | None:
    """Chain fetch from_date as a `datetime.date` — the NEAR edge of the window, normally None so
    Schwab defaults it to today.

    Cursor-audit F2: paired with _chain_to_date_for. When an operator explicitly selects an index
    expiry BEYOND the 45-day horizon, _chain_to_date_for pushes to_date out to it; without also
    bounding the near edge Schwab returns EVERY expiry from today through that far date
    (60 strikes * 2 * ~150 expiries = ~18,000 contracts >> SCHWAB_CHAIN_CONTRACT_BUDGET), the
    RC-491 502 — even though _fetch_state then slices to that ONE expiry and discards the rest.
    Bounding from_date to the same far date pulls only that expiry's strikes (60*2=120). Fires ONLY
    for a far index pick; equities, the auto path, and near picks (already inside the bounded
    horizon window) keep the open near end unchanged."""
    tk = ticker_storage_key(ticker)   # Cursor-audit F1: bare index root ("SPX") -> "$SPX"
    if not tk.startswith("$") or not selected_expiry:
        return None
    from datetime import date, timedelta

    from time_et import now_et

    horizon = (now_et() + timedelta(days=INDEX_CHAIN_DTE_HORIZON_DAYS)).date()
    try:
        sel = date.fromisoformat(str(selected_expiry)[:10])
    except ValueError:
        return None
    return sel if sel > horizon else None   # RC-496: date object, not `.isoformat()` (vendor formats it)
