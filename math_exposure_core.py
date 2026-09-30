"""
math_exposure_core.py
Base exposure engine — raw and normalized exposure values derived
from the chain and position structure.

Phase 2 extraction from math_exposure.py per Extraction Blueprint v1.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import math

from numeric_contract import float_finite_or_none, schwab_count, schwab_number


# Schwab options API missing-greek sentinel (documented wire value).
MISSING_GREEK_SENTINEL: float = -999.0




def schwab_iv_to_sigma(iv: float | None) -> float | None:
    """The ONE conversion from Schwab's `volatility` field (a PERCENT) to a decimal sigma.

    MEASURED 2026-09-27 on 49,244 contracts across the 43-ticker board: min 7.967, median 51.0,
    max 4,256.8 -- every value a percent. One fixed conversion; the old "> 3.0 means percent"
    guess would have read a real 2.5% IV as 250%. Schwab's IV is carried as sent; a model input
    needs sigma > 0, so 0 or less gives no sigma."""
    if iv is None or iv <= 0:
        return None
    return iv / 100.0


def book_net_gex(exposures: dict) -> float | None:
    """Net dealer GEX per 1% move at spot: the sum of every strike's net_gex_1pct -- Schwab's
    gamma as sent, +call/-put. The one gamma at spot (regime, headline, pin gate). None when no
    strike carried a valid gamma."""
    vals = [b["net_gex_1pct"] for b in exposures.values()
            if isinstance(b, dict) and b.get("has_valid_gamma") and b.get("net_gex_1pct") is not None]
    return sum(vals) if vals else None


def vendor_greeks_unavailable(iv: float | None) -> bool:
    """True when Schwab marks the contract's Greeks as having no value: volatility == -999."""
    return iv is not None and iv == MISSING_GREEK_SENTINEL


def greek_reported(value: float | None, *, iv: float | None = None) -> bool:
    """True when Schwab sent a value for this Greek: present and not Schwab's -999 no-value
    code (on the Greek itself or on the contract's volatility). Schwab's value is used exactly
    as sent -- no bound of ours overrides it."""
    return value is not None and value != MISSING_GREEK_SENTINEL and not vendor_greeks_unavailable(iv)



#: Bucket fields priced from Schwab's gamma / delta, and the flag that says a contract at the
#: strike carried one. A strike where no contract with OI carried a reported Greek has no value
#: for it -- its 0.0 initialiser is never read as data.
_GREEK_FIELD_FLAG = {
    **dict.fromkeys(("call_gamma", "put_gamma", "net_gamma",
                     "call_gex_1pct", "put_gex_1pct", "net_gex_1pct"), "has_valid_gamma"),
    **dict.fromkeys(("call_delta", "put_delta", "net_delta",
                     "call_dex_dollars", "put_dex_dollars", "net_dex_dollars"), "has_valid_delta"),
    **dict.fromkeys(("call_vanna", "put_vanna", "net_vanna"), "has_valid_vanna"),
}


def bucket_metric(bucket: dict, key: str) -> float | None:
    """One exposure-bucket field, or None when it is not known: absent, not finite, or a Greek
    field on a strike no reported Greek reached (see _GREEK_FIELD_FLAG)."""
    if not isinstance(bucket, dict) or key not in bucket:
        return None
    flag = _GREEK_FIELD_FLAG.get(key)
    if flag is not None and flag in bucket and not bucket[flag]:     # every priced strike carries it
        return None
    return float_finite_or_none(bucket[key])


def bucket_metric_abs(bucket: dict, key: str) -> float | None:
    v = bucket_metric(bucket, key)
    return abs(v) if v is not None else None


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExposureDiagnostics:
    contracts_total: int
    contracts_used: int
    greeks_missing: int
    note: str


# ── Exposure primitives ──────────────────────────────────────────────────────

def _strike_bucket(exposures_by_strike: Dict[float, dict], strike: float) -> dict:
    if strike not in exposures_by_strike:
        exposures_by_strike[strike] = {
            # has_oi: a contract at this strike reported openInterest (a reported 0 counts:
            # operator ruling 2026-09-27, take what Schwab sends). Every accumulator below starts
            # at 0.0; a consumer checks has_oi before reading one as computed.
            "has_oi": False,
            # Contracts at this strike whose openInterest was NOT REPORTED (absent, -999, text);
            # strike_total_oi() reads this so no total treats unknown as zero.
            "oi_unreported": 0,
            # Same discipline for totalVolume: an unreported one is UNKNOWN, never zero.
            "volume_unreported": 0,
            # Operator directive (2026-09-15, canonical input-validity rules): has_oi answers
            # "did any contract clear the OI gate"; has_valid_gamma answers the INDEPENDENT
            # question "did any contract that cleared it ALSO report genuine, vendor-
            # confirmed-usable greeks" (see vendor_greeks_unavailable). A contract can have
            # real OI and simultaneously garbage greeks (live-reproduced: SPY/QQQ 0DTE ITM
            # puts, real OI, delta=-1.0/gamma=0.0) -- conflating the two meant a genuinely
            # invalid-greeks strike silently rendered as a computed $0 instead of an honest
            # absence. Never re-derived from call_gamma/put_gamma being nonzero (a REAL
            # position can net to a genuine zero too -- see net_gex_1pct's own honest-zero
            # test coverage).
            "has_valid_gamma": False,
            # Same honest-absence signal for delta: True only once a valid delta (with OI)
            # contributed. A bucket whose deltas were all invalid keeps net_delta 0.0 from its
            # initialiser -- that 0.0 is NOT data (audit M-01, 2026-09-23).
            "has_valid_delta": False,
            # True once a contract with OI priced a vanna (valid IV and time to expiry)
            "has_valid_vanna": False,
            # True when the book was built WITH spot, i.e. the *_dollars / *_gex_1pct fields are
            # real dollar values. Set explicitly at build; never inferred from values.
            "dollarized": False,
            "call_oi": None,
            "put_oi": None,
            "call_oi_mult": 0.0,
            "put_oi_mult": 0.0,
            # NOTE: These are exposure-scaled buckets (gamma*OI*mult, delta*OI*mult)
            "call_gamma": 0.0,
            "put_gamma": 0.0,
            "call_vanna": 0.0,
            "put_vanna": 0.0,
            "call_delta": 0.0,
            "put_delta": 0.0,
            "net_gamma": 0.0,
            "net_delta": 0.0,
            # Dollarized (institutional) exposures when spot is provided
            "call_dex_dollars": 0.0,
            "put_dex_dollars": 0.0,
            "net_dex_dollars": 0.0,
            "call_gex_1pct": 0.0,
            "put_gex_1pct": 0.0,
            "net_gex_1pct": 0.0,
            # traded contracts per leg (Schwab totalVolume)
            "call_volume": None,
            "put_volume": None,
        }
    return exposures_by_strike[strike]

def compute_exposures_by_strike(
    contracts: List[dict],
    *,
    spot: float | None = None,
    now=None,
) -> tuple[Dict[float, dict], ExposureDiagnostics]:
    """
    Produces per-strike aggregated, over the contracts that report open interest:
      - call/put OI
      - call/put delta exposure (scaled)
      - call/put gamma exposure (scaled)
      - net delta, net gamma (Call + Put; puts keep signed delta)

    Scaling (Option A):
      delta_exposure = delta * OI * multiplier
      gamma_exposure = gamma * OI * multiplier

    NOTE: Dollarized fields (DEX$, GEX$ per 1%) are computed when `spot` is provided. Net gamma follows Call - Put convention.
    """
    exposures: Dict[float, dict] = {}
    total = 0
    used = 0
    missing = 0

    # RC-345 / F13: T for the BS-vanna faucet comes from the ONE valuation-T authority,
    # time_et.time_to_expiry_years (intraday ACT/365 to session close), NOT a local
    # whole-day `dte / 365.0`. `now` is pinned once so every contract in the aggregate is
    # priced at one instant, and T is memoised per distinct expiry string. It is the CALLER's
    # valuation instant when given (a replay of a stored chain must price at the snapshot's
    # time -- 2026-09-25: compute_terrain(now=...) priced gamma at the snapshot but vanna at
    # the wall clock, so the same stored chain gave a different vanna on every run), else now.
    from time_et import time_to_expiry_years as _tte, now_et as _now_et
    _tte_now = now if now is not None else _now_et()
    _tte_cache: dict[tuple, float | None] = {}

    def _tte_memo(ct: dict) -> float | None:
        key = (str(ct.get("expirationDate")), ct.get("settlementType"))
        if key not in _tte_cache:
            _tte_cache[key] = _tte(key[0], now=_tte_now, settlement_type=key[1])
        return _tte_cache[key]

    for ct in contracts:
        total += 1
        strike = schwab_number(ct.get("strikePrice"))
        if strike is None:
            continue

        oi =schwab_count(ct.get("openInterest"))   # -999 / text / negative: unreported
        side = (ct.get("putCall") or "").upper()
        if side not in ("CALL", "PUT"):
            continue

        mult = schwab_number(ct.get("multiplier"))
        if mult is None or mult <= 0:
            missing += 1
            continue

        b = _strike_bucket(exposures, strike)
        vol = schwab_count(ct.get("totalVolume"))
        if vol is None:
            b["volume_unreported"] += 1
        else:
            k = "call_volume" if side == "CALL" else "put_volume"
            b[k] = vol if b[k] is None else float(b[k]) + vol

        if oi is None:
            missing += 1
            b["oi_unreported"] += 1
            continue

        delta = schwab_number(ct.get("delta"))
        gamma = schwab_number(ct.get("gamma"))
        iv = schwab_number(ct.get("volatility"))
        delta_ok = greek_reported(delta, iv=ct.get("volatility"))   # raw: a -999 IV voids its greeks
        gamma_ok = greek_reported(gamma, iv=ct.get("volatility"))
        if not delta_ok or not gamma_ok:
            missing += 1

        used += 1
        b["has_oi"] = True

        if side == "CALL":
            prev = b.get("call_oi")
            b["call_oi"] = oi if prev is None else float(prev) + oi
            b["call_oi_mult"] += oi * mult
            if delta_ok:
                b["call_delta"] += delta * oi * mult
                b["has_valid_delta"] = True
            if gamma_ok:
                b["call_gamma"] += gamma * oi * mult
                b["has_valid_gamma"] = True
            if spot is not None:
                spt = float(spot)
                if delta_ok:
                    b["call_dex_dollars"] += delta * oi * mult * spt
                if gamma_ok:
                    b["call_gex_1pct"] += gamma * oi * mult * spt * spt * 0.01  # $-GEX per 1% spot move
                # RC-211: exact BS vanna from the shared d1/d2 faucet (math_levels.bs_vanna,
                # independently FD-verified). The prior vega/(S*sigma) shortcut dropped the
                # -d2 factor: always positive, wrong sign below spot, wrong magnitude.
                _iv_ok = iv is not None and iv > 0 and iv != MISSING_GREEK_SENTINEL and math.isfinite(iv)
                _T = _tte_memo(ct)
                if _iv_ok and _T is not None and _T > 0:
                    from math_levels import bs_vanna as _bsv
                    # Cursor-audit F7: route through the ONE IV-conversion authority instead of an
                    # inline _iv/100.0. Charm (compute_net_charm) and levels (_contract_inputs)
                    # already use schwab_iv_to_sigma; vanna alone re-encoded the raw conversion,
                    # breaking the single-authority guarantee and lacking the >3.0 units-flip guard.
                    _sig = schwab_iv_to_sigma(iv)
                    _vn = _bsv(spt, float(strike), _T, _sig) if _sig is not None else None
                    if _vn is not None:
                        b["call_vanna"] += _vn * 0.01 * oi * mult   # per 1 vol point
                        b["has_valid_vanna"] = True
        else:
            prev = b.get("put_oi")
            b["put_oi"] = oi if prev is None else float(prev) + oi
            b["put_oi_mult"] += oi * mult
            if delta_ok:
                b["put_delta"] += delta * oi * mult
                b["has_valid_delta"] = True
            if gamma_ok:
                b["put_gamma"] += gamma * oi * mult
                b["has_valid_gamma"] = True
            if spot is not None:
                spt = float(spot)
                if delta_ok:
                    b["put_dex_dollars"] += delta * oi * mult * spt
                if gamma_ok:
                    b["put_gex_1pct"] += gamma * oi * mult * spt * spt * 0.01   # $-GEX per 1% spot move
                # RC-211: same exact-vanna faucet as the CALL side (vanna is IDENTICAL for
                # calls and puts at a strike/expiry — any split comes from OI, never math).
                _iv_ok = iv is not None and iv > 0 and iv != MISSING_GREEK_SENTINEL and math.isfinite(iv)
                _T = _tte_memo(ct)
                if _iv_ok and _T is not None and _T > 0:
                    from math_levels import bs_vanna as _bsv
                    # Cursor-audit F7: single IV-conversion authority (see CALL side above).
                    _sig = schwab_iv_to_sigma(iv)
                    _vn = _bsv(spt, float(strike), _T, _sig) if _sig is not None else None
                    if _vn is not None:
                        b["put_vanna"] += _vn * 0.01 * oi * mult    # per 1 vol point
                        b["has_valid_vanna"] = True

    for strike, b in exposures.items():
        b["dollarized"] = spot is not None
        b["net_gamma"] = b["call_gamma"] - b["put_gamma"]
        # dealer-signed (+call/-put), the same convention as net_gamma / net GEX and the
        # terrain's dex_dollars -- one meaning of DEX on every screen (2026-09-27: the bucket
        # summed call + put, the holder's side, while terrain subtracted)
        b["net_delta"] = b["call_delta"] - b["put_delta"]
        # net dealer vanna, delta-shares per vol point, +call/-put: THE per-strike net vanna the
        # heatmap, the vanna-by-strike rows and the book total all carry
        b["net_vanna"] = b["call_vanna"] - b["put_vanna"]
        # Dollarized net fields (remain 0.0 if spot is None)
        b["net_dex_dollars"] = b.get("call_dex_dollars", 0.0) - b.get("put_dex_dollars", 0.0)
        b["net_gex_1pct"] = b.get("call_gex_1pct", 0.0) - b.get("put_gex_1pct", 0.0)

    return exposures, _diagnostics(total, used, missing)


def _diagnostics(total: int, used: int, missing: int) -> ExposureDiagnostics:
    note = "OK"
    if used == 0:
        note = "No usable contracts (OI filtered or chain empty)."
    elif missing == used:
        note = "All greeks missing (-999). You will still get OI center; gamma/delta pin/inf may be N/A until RTH."
    return ExposureDiagnostics(contracts_total=total, contracts_used=used,
                               greeks_missing=missing, note=note)


def exposure_books(contracts: List[dict], *, spot: float | None, now=None
                   ) -> "Dict[tuple[str, float | None], tuple[Dict[float, dict], ExposureDiagnostics]]":
    """compute_exposures_by_strike once per (expiration date, days to
    expiry) group. Every contract is priced once; any subset of expiries is then a
    merge_exposure_books of its groups (the full book, 0DTE, the front expiry, <=7 / >7 days)."""
    groups: "dict[tuple[str, float | None], list]" = {}
    for ct in contracts or []:
        if isinstance(ct, dict):
            key = (str(ct.get("expirationDate") or "")[:10], schwab_number(ct.get("daysToExpiration")))
            groups.setdefault(key, []).append(ct)
    return {k: compute_exposures_by_strike(cs, spot=spot, now=now)
            for k, cs in groups.items()}


def merge_exposure_books(books) -> "tuple[Dict[float, dict], ExposureDiagnostics]":
    """One book from books over DISJOINT contracts -- the same result one
    compute_exposures_by_strike call over all their contracts gives (up to float addition
    order): every bucket field is a per-contract sum or an OR of a per-contract flag, and a
    leg no contract reported stays None (None + x = x)."""
    merged: Dict[float, dict] = {}
    total = used = missing = 0
    for exposures, diag in books:
        total += diag.contracts_total
        used += diag.contracts_used
        missing += diag.greeks_missing
        for strike, bucket in exposures.items():
            cur = merged.get(strike)
            if cur is None:
                merged[strike] = dict(bucket)
                continue
            for k, v in bucket.items():
                if k in _BUCKET_FLAGS:
                    cur[k] = cur.get(k, False) or v
                elif v is not None:
                    c = cur.get(k)
                    cur[k] = v if c is None else c + v
    return merged, _diagnostics(total, used, missing)


#: The per-strike bucket fields that are flags (OR-ed when books merge); every other field is
#: a sum, None when no contract reported it (_strike_bucket, compute_exposures_by_strike).
_BUCKET_FLAGS = frozenset({"has_oi", "has_valid_gamma", "has_valid_delta", "has_valid_vanna", "dollarized"})


#: streamed-state key -> (chain contract field it overlays, that field's own freshness key).
#: Native Schwab LEVELONE_OPTIONS fields (schwab-py's LevelOneOptionFields: DELTA=28, GAMMA=29,
#: OPEN_INTEREST=9, TOTAL_VOLUME=8) map onto the SAME field names compute_exposures_by_strike
#: already reads from a REST chain contract (`gamma`, `delta`, `openInterest`, `totalVolume`)
#: -- this overlay changes no formula and adds no second computation path; it only lets these
#: inputs be fresher than the chain snapshot they arrived in, for whichever contract is
#: actively streaming. `total_volume` closes the "near-instant options volume" requirement:
#: without it, a volume-only tick (no Greeks/OI change) never reached ANY display, since
#: _per_strike's volume column and compute_exposures_by_strike's own call/put volume both read
#: a contract's `totalVolume` directly, not the ticker-level ``_stream_volume`` cache.
_STREAMED_GREEK_FIELDS: tuple[tuple[str, str], ...] = (
    ("gamma", "gamma"),
    ("delta", "delta"),
    ("open_interest", "openInterest"),
    ("total_volume", "totalVolume"),
    ("volatility", "volatility"),
)


def overlay_streamed_contract_fields(
    contracts: List[dict],
    streamed_by_symbol: Dict[str, dict],
) -> tuple[List[dict], int]:
    """A live contract's streamed GAMMA/DELTA/OPEN_INTEREST/TOTAL_VOLUME/VOLATILITY onto the REST
    chain, matched by each contract's own `symbol` field.

    `streamed_by_symbol` holds only contracts the daemon holds live now (the caller applies
    live_market_plane.feed_live_for). For those the stream is the one owner of these fields:
    Schwab streams a field only when it changes, so its last streamed value IS the current value
    however long ago it arrived -- it is never compared with the chain's quote time (ONE-05,
    2026-09-28: that comparison dropped every streamed value after each chain download, and the
    heatmap flipped to all-stale while the feed was live). A field the stream has not sent keeps
    the chain's value; every other contract keeps the chain's values.

    Pure: `contracts` and its dicts are never mutated; only a contract that gets a field is
    copied. Returns (new_contracts, overlaid_count).
    """
    if not contracts:
        return [], 0
    if not streamed_by_symbol:
        return list(contracts), 0
    out: List[dict] = []
    overlaid = 0
    for ct in contracts:
        sym = ct.get("symbol") if isinstance(ct, dict) else None
        streamed = streamed_by_symbol.get(sym) if sym else None
        if not streamed:
            out.append(ct)
            continue
        new_ct = None
        for streamed_key, chain_key in _STREAMED_GREEK_FIELDS:
            val = streamed.get(streamed_key)
            if val is None:
                continue
            if new_ct is None:
                new_ct = dict(ct)
            new_ct[chain_key] = val
        if new_ct is not None:
            overlaid += 1
            out.append(new_ct)
        else:
            out.append(ct)
    return out, overlaid


# ── Strike selection helpers ─────────────────────────────────────────────────
# (foundational — used by both levels and volatility modules)





# Dollar GEX per 1% spot move: gamma × OI × mult × spot² × 0.01 (see compute_exposures_by_strike).




def strike_total_oi(bucket: dict) -> float | None:
    """THE total open interest at one strike, or None when it is not known.

    Known = every contract at the strike reported openInterest (oi_unreported == 0). A leg
    with no positive-OI contract then contributes a real 0 (its contracts reported 0 OI, or
    none is listed). Replaces three readers that disagreed: one required BOTH legs (dropping
    every one-sided strike from PCR / OI center / max pain), two counted a missing leg as 0
    whether or not its OI was reported (audit T-04 / M-06 / M-07 / M-08, 2026-09-24)."""
    legs = strike_oi_legs(bucket)
    if legs is None:
        return None
    call_oi, put_oi = legs
    return call_oi + put_oi


def strike_oi_legs(bucket: dict) -> tuple[float, float] | None:
    """(call OI, put OI) at one strike when its OI is known (see strike_total_oi), else None.
    A leg with no positive-OI contract is a KNOWN 0.0 -- every contract there reported OI."""
    if not isinstance(bucket, dict) or bucket.get("oi_unreported") != 0:
        return None
    legs = []
    for key in ("call_oi", "put_oi"):
        if bucket.get(key) is None:
            legs.append(0.0)      # known: no contract on this leg carried positive OI
            continue
        v = bucket_metric(bucket, key)
        if v is None:             # present but not a finite number -> not known
            return None
        legs.append(v)
    return legs[0], legs[1]


def strike_volume_legs(bucket: dict) -> tuple[float, float] | None:
    """(call, put) session volume at one strike when every contract there reported totalVolume
    (0 is a real zero), else None. A leg with no listed contract is a known 0.0. THE one reader:
    GEX-by-Strike rows, heatmap cells and the put/call volume ratio."""
    if not isinstance(bucket, dict) or bucket.get("volume_unreported") != 0:
        return None
    c, p = bucket.get("call_volume"), bucket.get("put_volume")
    return (0.0 if c is None else float(c)), (0.0 if p is None else float(p))


def strike_total_volume(bucket: dict) -> float | None:
    """THE total session volume at one strike, or None when a contract there did not report it."""
    legs = strike_volume_legs(bucket)
    if legs is None:
        return None
    call_volume, put_volume = legs
    return call_volume + put_volume


def book_total_oi(exposures: Dict[float, dict]) -> float | None:
    """Total OI of the whole book, or None if ANY strike's OI is unknown."""
    if not exposures:
        return None
    total = 0.0
    for b in exposures.values():
        t = strike_total_oi(b)
        if t is None:
            return None
        total += t
    return total


def put_call_oi_ratio(exposures: Dict[float, dict]) -> float | None:
    """Total put OI / total call OI of the book -- the positions held; None if any strike's OI is
    unknown or call OI is 0."""
    legs = [strike_oi_legs(b) for b in exposures.values()]
    if not legs or None in legs:
        return None
    calls = sum(c for c, _ in legs)
    return sum(p for _, p in legs) / calls if calls > 0 else None


def put_call_volume_ratio(exposures: Dict[float, dict]) -> float | None:
    """Total put volume / total call volume of the book -- today's trading, Cboe's convention
    (https://cdn.cboe.com/resources/us/options/market_statistics/daily/cone/archive/html/2002-05-17.html).
    None when any contract in the book did not report its volume, or no call traded. A strike with
    no call (or put) contract listed has no volume on that side, not a zero."""
    legs = [strike_volume_legs(b) for b in (exposures or {}).values()]
    if not legs or None in legs:
        return None
    calls = sum(c for c, _ in legs)
    return sum(p for _, p in legs) / calls if calls > 0 else None


def exposures_have_dollar_gex(exposures: Dict[float, dict]) -> bool:
    """True when the book was built WITH spot (its dollar fields are real). Read from the
    explicit `dollarized` flag -- it used to be inferred from "any strike has non-zero dollar
    GEX", so a spot-built book whose gammas were all invalid looked un-dollarized and every
    consumer silently fell through to raw-gamma units (audit, 2026-09-24)."""
    for b in exposures.values():
        if isinstance(b, dict) and "dollarized" in b:
            return bool(b["dollarized"])
    return False


def key_level_strikes_with_oi(exposures: Dict[float, dict]) -> List[float]:
    """Strikes whose OI is KNOWN and positive (strike_total_oi -- the one reader). It used to
    require BOTH legs, silently dropping every one-sided strike from the grid (M-06/M-08)."""
    out: List[float] = []
    for s in sorted(float(k) for k in exposures.keys()):
        tot = strike_total_oi(exposures.get(s, {}))
        if tot is not None and tot > 0:
            out.append(s)
    return out


def key_level_strikes_with_gamma(exposures: Dict[float, dict]) -> List[float]:
    """Strikes with usable gamma buckets (excludes OI-only / invalid-greek tails)."""
    if not exposures:
        return []
    dollar = exposures_have_dollar_gex(exposures)
    out: List[float] = []
    for s in sorted(float(k) for k in exposures.keys()):
        b = exposures.get(s, {})
        if dollar:
            tg = total_gex_dollars_at_strike(b)
            ng = net_gex_dollars_at_strike(b)
            if (tg is not None and tg > 0) or (
                ng is not None and abs(ng) > 1e-12
            ):
                out.append(s)
        else:
            tg = total_gamma_raw_at_strike(b)
            if tg is not None and tg > 0:
                out.append(s)
    return out


def total_gex_dollars_at_strike(bucket: dict) -> float | None:
    """Peak gamma concentration: |call GEX$| + |put GEX$| per 1% move."""
    c = bucket_metric_abs(bucket, "call_gex_1pct")
    p = bucket_metric_abs(bucket, "put_gex_1pct")
    return None if c is None or p is None else c + p


def net_gex_dollars_at_strike(bucket: dict) -> float | None:
    return bucket_metric(bucket, "net_gex_1pct")


def compute_net_vanna(exposures: dict, spot: float | None) -> dict | None:
    """RC-362: aggregate dealer vanna — how much dealer DELTA shifts per IV point.

    Same naive dealer-sign model (dealer +calls/−puts): net vanna Δ-shares per 1.00 vol
    = Σ net_vanna over the ONE exposures book (each strike's net_vanna from
    compute_exposures_by_strike: exact Black-Scholes bs_vanna, per vol point, ·OI·mult);
    dollars per vol-pt = × spot. Positive net: IV UP forces dealer delta up → they SELL
    into vol spikes; IV DOWN (crush) → they BUY, the vanna-tailwind rally mechanic.
    FAIL-CLOSED: None on an empty/valueless book or missing spot.
    """
    if not exposures or spot is None or spot <= 0:
        return None
    nets = [v for b in exposures.values() if (v := bucket_metric(b, "net_vanna")) is not None]
    if not nets:
        return None
    net_shares_per_volpt = sum(nets)                 # the book is already per vol point
    return {"net_vanna_dollars_per_volpt": round(net_shares_per_volpt * float(spot), 2),
            "net_vanna_shares_per_volpt": round(net_shares_per_volpt, 2)}


def compute_zero_dte_gamma_share(
    exposures_all: dict, exposures_0dte: dict
) -> float | None:
    """RC-357: % of the dealer gamma book from SAME-DAY expiry — the level-persistence read.

    share = sum(|net_gex_1pct|) over the 0DTE book / sum(|net_gex_1pct|) over the full book,
    BOTH books from the ONE producer (compute_exposures_by_strike; the 0DTE book merges
    exposure_books' same-day groups). High share
    means today's walls/flip decay into the close (0DTE gamma dies at 4pm); low share means
    the levels are carried by dated gamma and persist. FAIL-CLOSED: None when the full book
    is empty or has no measurable gamma — never a fabricated 0%.
    """
    if not exposures_all:
        return None
    # RC-369: a bucket MISSING its net-GEX field must not contribute a fabricated zero
    # weight to a share-of-book ratio — absence WITHHOLDS the whole metric.
    total = 0.0
    for v in exposures_all.values():
        x = bucket_metric(v, "net_gex_1pct")
        if x is not None:
            total += abs(x)
    if total <= 0:
        return None
    zero = 0.0
    for v in (exposures_0dte or {}).values():
        x = bucket_metric(v, "net_gex_1pct")
        if x is not None:
            zero += abs(x)
    return round(100.0 * zero / total, 1)


def total_gamma_raw_at_strike(bucket: dict) -> float | None:
    c = bucket_metric_abs(bucket, "call_gamma")
    p = bucket_metric_abs(bucket, "put_gamma")
    return None if c is None or p is None else c + p




def _pick_strike_max_metric(
    exposures: Dict[float, dict],
    strikes: List[float],
    metric_fn,
) -> tuple[float | None, float | None]:
    best_s: float | None = None
    best_v: float | None = None
    for s in strikes:
        b = exposures.get(s, {})
        v = metric_fn(b)
        if v is None or v <= 0:
            continue
        if best_v is None or v > best_v:
            best_s = float(s)
            best_v = float(v)
    return best_s, best_v


def pick_pin_and_strength(
    exposures: Dict[float, dict], strikes: List[float]
) -> tuple[float | None, float | None]:
    """RC-124/RC-315/RC-320: max TOTAL gamma — a GROSS GAMMA CONCENTRATION, plus its
    decisiveness. NOT a demonstrated magnet.

    WHAT IT MEASURES. The strike carrying the largest absolute call GEX dollars plus
    absolute put GEX dollars — i.e. where the most dealer re-hedging activity sits. This is
    the quantity SpotGamma publishes as Absolute Gamma.

    WHAT IT DOES NOT ESTABLISH, and what this docstring wrongly claimed until RC-320. The
    previous text read "hedging MAGNITUDE pins price regardless of net sign, so
    calls-plus-puts is the magnet measure". That does not follow. Magnitude sets the SIZE of
    the hedging flow at a strike; the SIGN of the dealer position sets whether that flow is
    stabilising or destabilising — a dealer long gamma sells rallies and buys dips, a dealer
    short gamma does the opposite — and this metric discards the sign. Two strikes with equal
    absolute gamma can behave oppositely. The sign is also not observable: public open
    interest does not reveal contract ownership
    (https://spotgamma.com/what-is-gex-gamma-exposure/), so dealer direction is MODELLED.
    Expiration-date clustering in the literature turns on NET positioning — Ni, Pearson and
    Poteshman, Journal of Financial Economics, doi:10.1016/j.jfineco.2004.08.005.

    Cursor's independent audit refuted the original sentence on 2026-08-09; RC-315 corrected
    the derivation register and MISSED this docstring, which is where the register's wording
    came from. Treat the result as a pin CANDIDATE.

    The NET book (calls minus puts) is a different question — where the signed book leans —
    and lives under its own name as net_gex_peak (pick_net_gex_peak_strike below).

    strength_pct = the leader's margin over the runner-up on the same metric. A 1% lead is a
    coin flip and the label should say so; a 40% lead is a decisive CONCENTRATION, which is
    still not a claim about where price goes.
    Fail-closed: no dollarized GEX -> (None, None), never a raw-gamma fallback.
    """
    if not exposures_have_dollar_gex(exposures):
        return None, None
    s, v = _pick_strike_max_metric(exposures, strikes, total_gex_dollars_at_strike)
    if s is None or v is None or v <= 0:
        return None, None
    second = 0.0
    for k in strikes:
        if float(k) == s:
            continue
        t = total_gex_dollars_at_strike(exposures.get(k, {}))
        if t is not None and t > second:
            second = t
    return round(s, 2), round((v - second) / v * 100.0, 1)


def pick_net_gex_peak_strike(exposures: Dict[float, dict], strikes: List[float]) -> float | None:
    """
    Net-GEX peak: strike with largest |net GEX$| per 1% (calls minus puts) -- where the SIGNED
    book concentrates (the standard pin is total gamma, pick_pin_and_strength). None when the
    book has no dollar GEX (no spot).
    """
    if not exposures_have_dollar_gex(exposures):
        return None
    s, _ = _pick_strike_max_metric(
        exposures, strikes, lambda b: bucket_metric_abs(b, "net_gex_1pct")
    )
    return round(s, 2) if s is not None else None


def pick_key_delta_strike(
    exposures: Dict[float, dict], strikes: List[float]
) -> float | None:
    """Key Delta Strike: largest total delta notional (|call DEX$| + |put DEX$|).

    Institutional only — no raw-delta fallback: delta notional needs spot, and a
    unit mix here would rank strikes on incomparable numbers.
    """
    if not exposures_have_dollar_gex(exposures):
        return None

    def _total_dex(b: dict) -> float | None:
        c = bucket_metric_abs(b, "call_dex_dollars")
        p = bucket_metric_abs(b, "put_dex_dollars")
        if c is None and p is None:
            return None
        return (c or 0.0) + (p or 0.0)

    s, _ = _pick_strike_max_metric(exposures, strikes, _total_dex)
    return round(s, 2) if s is not None else None


def pick_volatility_point_strikes(
    exposures: Dict[float, dict], strikes: List[float]
) -> tuple[float | None, float | None]:
    """(HVP, LVP): strike holding the most NEGATIVE / most POSITIVE net GEX$.

    Signed extremes, not magnitudes: HVP exists only where net dealer gamma is
    actually negative at some strike (amplification pocket), LVP only where
    positive (damping pocket). A one-sided chain returns None for the absent side.
    """
    if not exposures_have_dollar_gex(exposures):
        return None, None
    hvp_s: float | None = None
    hvp_v: float | None = None
    lvp_s: float | None = None
    lvp_v: float | None = None
    for s in strikes:
        v = net_gex_dollars_at_strike(exposures.get(s, {}))
        if v is None:
            continue
        if v < 0 and (hvp_v is None or v < hvp_v):
            hvp_s, hvp_v = float(s), float(v)
        if v > 0 and (lvp_v is None or v > lvp_v):
            lvp_s, lvp_v = float(s), float(v)
    return (
        round(hvp_s, 2) if hvp_s is not None else None,
        round(lvp_s, 2) if lvp_s is not None else None,
    )


def pick_gamma_wall_strikes(
    exposures: Dict[float, dict], strikes: List[float]
) -> tuple[tuple[float | None, float | None], tuple[float | None, float | None]]:
    """Call/put gamma walls: max |side GEX$|; none without a dollarized book (no spot)."""
    if not exposures_have_dollar_gex(exposures):
        return (None, None), (None, None)
    return (
        _pick_strike_max_metric(exposures, strikes, lambda b: bucket_metric_abs(b, "call_gex_1pct")),
        _pick_strike_max_metric(exposures, strikes, lambda b: bucket_metric_abs(b, "put_gex_1pct")),
    )


def pick_delta_wall_strikes(
    exposures: Dict[float, dict], strikes: List[float]
) -> tuple[tuple[float | None, float | None], tuple[float | None, float | None]]:
    """Call/put delta walls: max |side DEX$|; none without a dollarized book (no spot)."""
    if not exposures_have_dollar_gex(exposures):
        return (None, None), (None, None)
    return (
        _pick_strike_max_metric(exposures, strikes, lambda b: bucket_metric_abs(b, "call_dex_dollars")),
        _pick_strike_max_metric(exposures, strikes, lambda b: bucket_metric_abs(b, "put_dex_dollars")),
    )










# ── Validation / sanitization ────────────────────────────────────────────────





# ── Exposure aggregation ─────────────────────────────────────────────────────




# ── Charm ─────────────────────────────────────────────────────────────────────



# ── Greek bias ────────────────────────────────────────────────────────────────




# ── Beta / returns ────────────────────────────────────────────────────────────






