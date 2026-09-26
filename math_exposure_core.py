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
import logging

from numeric_contract import float_finite_or_none, float_nonnegative_or_none

log = logging.getLogger(__name__)

# Schwab options API missing-greek sentinel (documented wire value).
MISSING_GREEK_SENTINEL: float = -999.0

#: Schwab's chain reports every Greek to 3 decimal places (measured 2026-09-26 on the SPY chain:
#: every gamma/delta/vega/theta has at most 3 decimals). A value may be off by this much.
GREEK_ROUNDING: float = 0.0005
#: Room over a contract's peak possible gamma for Schwab's own clock/rate basis. MEASURED
#: 2026-09-26 on 9,428 SPY contracts with OI: reported gamma / peak gamma p99 1.078; the one
#: contract above 1.5 reported 5.274 (222x its peak) -- impossible, and normal in the downloads
#: before and after.
GAMMA_PEAK_ROOM: float = 1.5

# compute_net_charm zero-used error when contracts matched expiry but failed OI/gamma/IV gates.
CHARM_QUALITY_GATE_ERROR_MARKER = "quality gates"


def schwab_iv_to_sigma(iv: float | None) -> float | None:
    """The ONE conversion from Schwab's `volatility` field to a decimal sigma.

    Schwab reports implied volatility in PERCENT. Verified 2026-07-19 on 1,600 contract
    greeks from the 40 most recent chain snapshots: min 23.7550, median 50.4315, max
    174.2260 — 1,600 of 1,600 above 3.0, none at or below it.

    The `> 3.0` test is a defensive guard against a silent vendor unit change (a 300%
    IV is possible but vanishingly rare; a 3.0 decimal sigma is not). It is kept because
    a units flip would otherwise corrupt every gamma silently rather than loudly.

    This existed as two different inline expressions — `iv / 100.0` unconditionally in
    compute_net_charm and the guarded form in math_levels._contract_inputs — i.e. two
    modules encoding different assumptions about one vendor field. One definition now.
    """
    if iv is None or iv <= 0:
        return None
    return iv / 100.0 if iv > 3.0 else iv


def vendor_greeks_unavailable(iv: float | None) -> bool:
    """True when Schwab marks the contract's Greeks missing: volatility == -999 (its documented
    missing-greek marker) invalidates every Greek on the contract."""
    return iv is not None and iv == MISSING_GREEK_SENTINEL


def gamma_is_plausible(gamma: float | None, *, iv: float | None = None, spot: float | None = None,
                       t_years: float | None = None) -> bool:
    """True when Schwab's reported gamma can be real: present, finite, not the -999 marker,
    not negative, and -- when spot, IV and time are known -- no larger than the contract's
    peak possible gamma, 1 / (sqrt(2 pi) * spot * sigma * sqrt(T)), with GAMMA_PEAK_ROOM for
    Schwab's basis and GREEK_ROUNDING for its rounding. Small values (Schwab's 0.000 / 0.001
    on deep in- or out-of-the-money contracts) are real: that is rounding, not bad data."""
    if vendor_greeks_unavailable(iv):
        return False
    if gamma is None or gamma == MISSING_GREEK_SENTINEL or not math.isfinite(gamma) or gamma < 0.0:
        return False
    sigma = schwab_iv_to_sigma(iv)
    if spot and sigma and t_years and t_years > 0:
        peak = 1.0 / (math.sqrt(2.0 * math.pi) * float(spot) * sigma * math.sqrt(t_years))
        if gamma > peak * GAMMA_PEAK_ROOM + GREEK_ROUNDING:
            return False
    return True


def delta_is_plausible(delta: float | None, *, iv: float | None = None) -> bool:
    """True when Schwab's reported delta can be real: present, finite, not the -999 marker,
    within [-1, 1] up to rounding."""
    if vendor_greeks_unavailable(iv):
        return False
    return (delta is not None and delta != MISSING_GREEK_SENTINEL and math.isfinite(delta)
            and abs(delta) <= 1.0 + GREEK_ROUNDING)


def charm_compute_unavailable_log_level(error: str | None) -> int:
    """Quality-gate failure log level:
      - quality-gate (any skip distribution — uniform or mixed) → DEBUG
      - expiry mismatch / empty input (not quality-gate) → WARNING
      - None / unrecognized error → WARNING (fail-loud)

    The failure path only fires when ``used == 0`` (server.py:3474 routes
    partial-quality outcomes to the success-log). Every emission is the same
    steady-state class: complete chain unusable for charm. The skip-distribution
    detail (gamma=40 vs gamma=37+oi=3) is preserved in the error string for
    operator inspection; it does not change the operator-actionable signal,
    so it does not need its own log level. Per-tick INFO for this class was
    log spam outside RTH / when chain greeks are -999.

    Reserve WARNING for the two non-quality-gate errors — those are different
    classes (chain misrouted to wrong expiry / no contracts received at all)
    and warrant operator attention.
    """
    if error and CHARM_QUALITY_GATE_ERROR_MARKER in error:
        return logging.DEBUG
    return logging.WARNING

# ── Formatting helpers ────────────────────────────────────────────────────────

def _f(x) -> float | None:
    return float_finite_or_none(x)


#: Bucket fields priced from Schwab's gamma / delta, and the flag that says the strike's value is
#: real. A strike with no contract carrying valid Greeks, or with any contract excluded for
#: invalid Greeks, has no value for them -- its 0.0 initialiser or partial sum is never read.
_GREEK_FIELD_FLAG = {
    **dict.fromkeys(("call_gamma", "put_gamma", "net_gamma",
                     "call_gex_1pct", "put_gex_1pct", "net_gex_1pct"), "has_valid_gamma"),
    **dict.fromkeys(("call_delta", "put_delta", "net_delta",
                     "call_dex_dollars", "put_dex_dollars", "net_dex_dollars"), "has_valid_delta"),
}
_EXCLUDABLE_FIELDS = frozenset({"call_vanna", "put_vanna"})


def bucket_metric(bucket: dict, key: str) -> float | None:
    """One exposure-bucket field, or None when it is not known: absent, not finite, or a Greek
    field on a strike whose Greeks are not valid (see _GREEK_FIELD_FLAG)."""
    if not isinstance(bucket, dict) or key not in bucket:
        return None
    flag = _GREEK_FIELD_FLAG.get(key)
    if flag is not None and flag in bucket and not bucket[flag]:     # every priced strike carries it
        return None
    if key in _EXCLUDABLE_FIELDS and bucket.get("greeks_invalid"):
        return None
    return _f(bucket[key])


def bucket_metric_abs(bucket: dict, key: str) -> float | None:
    v = bucket_metric(bucket, key)
    return abs(v) if v is not None else None


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ExposureRow:
    label: str                 # CONSENSUS, ±5, ±10, ±15, ±20
    window: int | None         # None = all (consensus)
    net_gamma: float | None
    net_delta: float | None
    net_gex_peak: float | None  # RC-417: |net GEX$| peak — never the total-gamma pin
    delta_inflection: float | None
    gamma_inflection: float | None
    oi_center: float | None
    pin_strength: str | None   # None = not measured (M-04)
    bias_signal: str | None    # None = not measured (M-05)

@dataclass(frozen=True)
class ExposureDiagnostics:
    contracts_total: int
    contracts_used: int
    greeks_missing: int
    note: str
    #: (symbol, strike, open interest) of every contract with OI whose Greeks were invalid --
    #: its whole strike is excluded from the Greek totals
    excluded: tuple = ()


# ── Exposure primitives ──────────────────────────────────────────────────────

def _strike_bucket(exposures_by_strike: Dict[float, dict], strike: float) -> dict:
    if strike not in exposures_by_strike:
        exposures_by_strike[strike] = {
            # Operator directive (2026-09-14, live SPX reproduction): every accumulator below
            # (call_gamma, net_gex_1pct, ...) is pre-initialized to a real 0.0 so mid-loop `+=`
            # never needs a None-guard -- but that same 0.0 is indistinguishable from "every
            # contract at this strike/expiry was skipped by the require_oi gate" to any reader
            # who only looks at the accumulator itself (exactly the live SPX defect: Schwab's
            # chain returned openInterest=0 for every contract, so nothing here was EVER wrong
            # math, just a bucket that never had a chance to accumulate anything real). has_oi
            # is the ONE canonical "did any contract actually clear the OI gate" signal -- every
            # consumer of this bucket's dollar/gamma fields must check it before treating 0.0 as
            # a computed value, not re-derive presence from call_oi/put_oi being non-None
            # (equivalent today, but a second definition of the same fact is how these drift).
            "has_oi": False,
            # Contracts at this strike whose openInterest was NOT REPORTED (absent / invalid).
            # With the OI gate a leg with no positive-OI contract is a real zero, but a
            # contract that never reported OI is UNKNOWN -- strike_total_oi() reads this so
            # no total ever treats unknown as zero (audit T-04 / M-06..08, 2026-09-24).
            "oi_unreported": 0,
            # Same discipline for the flow fields (bidSize / askSize / totalVolume): Schwab
            # reports them on every contract (measured 2026-09-24, 568 real contracts), so an
            # absent side is a known zero and an unreported one is UNKNOWN.
            "size_unreported": 0,
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
            # contracts with OI whose Greeks were invalid: a strike with any is excluded whole
            "greeks_invalid": 0,
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
            "call_oi_dollars": 0.0,
            "put_oi_dollars": 0.0,
            "total_oi_dollars": 0.0,
            # Option-chain order flow (Schwab: bidSize, askSize, totalVolume per leg)
            "call_volume": None,
            "put_volume": None,
            "call_bid_size": 0.0,
            "call_ask_size": 0.0,
            "put_bid_size": 0.0,
            "put_ask_size": 0.0,
        }
    return exposures_by_strike[strike]

def compute_exposures_by_strike(
    contracts: List[dict],
    *,
    spot: float | None = None,
    use_only_dte_max: int | None = None,
    require_oi: bool = True,
    now=None,
) -> tuple[Dict[float, dict], ExposureDiagnostics]:
    """
    Produces per-strike aggregated:
      - call/put OI
      - call/put delta exposure (scaled)
      - call/put gamma exposure (scaled)
      - net delta, net gamma (Call + Put; puts keep signed delta)

    Scaling (Option A):
      delta_exposure = delta * OI * multiplier
      gamma_exposure = gamma * OI * multiplier

    NOTE: Dollarized fields (DEX$, GEX$ per 1%, OI$) are computed when `spot` is provided. Net gamma follows Call - Put convention.
    """
    exposures: Dict[float, dict] = {}
    total = 0
    used = 0
    missing = 0
    excluded: list = []

    # RC-345 / F13: T for the BS-vanna faucet comes from the ONE valuation-T authority,
    # time_et.time_to_expiry_years (intraday ACT/365 to session close), NOT a local
    # whole-day `dte / 365.0`. `now` is pinned once so every contract in the aggregate is
    # priced at one instant, and T is memoised per distinct expiry string. It is the CALLER's
    # valuation instant when given (a replay of a stored chain must price at the snapshot's
    # time -- 2026-09-25: compute_terrain(now=...) priced gamma at the snapshot but vanna at
    # the wall clock, so the same stored chain gave a different vanna on every run), else now.
    from time_et import time_to_expiry_years as _tte, now_et as _now_et
    _tte_now = now if now is not None else _now_et()
    _tte_cache: dict[str, float | None] = {}

    def _tte_memo(exp_raw) -> float | None:
        key = str(exp_raw)
        if key not in _tte_cache:
            _tte_cache[key] = _tte(exp_raw, now=_tte_now)
        return _tte_cache[key]

    for ct in contracts:
        total += 1
        strike = _f(ct.get("strikePrice"))
        if strike is None:
            continue

        dte = _f(ct.get("daysToExpiration"))
        if use_only_dte_max is not None and dte is not None and dte > use_only_dte_max:
            continue

        oi = _f(ct.get("openInterest"))
        side = (ct.get("putCall") or "").upper()
        if side not in ("CALL", "PUT"):
            continue

        mult = _f(ct.get("multiplier"))
        if mult is None or mult <= 0:
            missing += 1
            continue

        b = _strike_bucket(exposures, strike)
        vol = float_nonnegative_or_none(ct.get("totalVolume"))  # volume: 0 valid, negatives are corruption
        bsz = float_nonnegative_or_none(ct.get("bidSize"))   # a size is never negative
        asz = float_nonnegative_or_none(ct.get("askSize"))
        if bsz is None or asz is None:
            b["size_unreported"] += 1
        if vol is None:
            b["volume_unreported"] += 1
        if side == "CALL":
            if vol is not None:
                prev = b.get("call_volume")
                b["call_volume"] = vol if prev is None else float(prev) + vol
            if bsz is not None:
                b["call_bid_size"] = b.get("call_bid_size", 0.0) + bsz
            if asz is not None:
                b["call_ask_size"] = b.get("call_ask_size", 0.0) + asz
        else:
            if vol is not None:
                prev = b.get("put_volume")
                b["put_volume"] = vol if prev is None else float(prev) + vol
            if bsz is not None:
                b["put_bid_size"] = b.get("put_bid_size", 0.0) + bsz
            if asz is not None:
                b["put_ask_size"] = b.get("put_ask_size", 0.0) + asz

        if oi is None:
            missing += 1
            b["oi_unreported"] += 1
        if require_oi and (oi is None or oi <= 0):
            continue

        delta = _f(ct.get("delta"))
        gamma = _f(ct.get("gamma"))
        iv = _f(ct.get("volatility"))
        delta_ok = delta_is_plausible(delta, iv=iv)
        gamma_ok = gamma_is_plausible(gamma, iv=iv, spot=spot, t_years=_tte_memo(ct.get("expirationDate")))
        if not delta_ok or not gamma_ok:
            missing += 1
            if oi is not None and oi > 0:
                b["greeks_invalid"] += 1
                excluded.append((ct.get("symbol"), float(strike), oi))

        used += 1
        # The ONE canonical "did OI actually contribute here" signal (see _strike_bucket's own
        # comment) -- exactly the condition every OI-gated accumulation below already shares.
        if oi is not None:
            b["has_oi"] = True

        if side == "CALL":
            if oi is not None:
                prev = b.get("call_oi")
                b["call_oi"] = oi if prev is None else float(prev) + oi
                b["call_oi_mult"] += oi * mult
            if oi is not None and delta_ok:
                b["call_delta"] += delta * oi * mult
                b["has_valid_delta"] = True
            if oi is not None and gamma_ok:
                b["call_gamma"] += gamma * oi * mult
                b["has_valid_gamma"] = True
            if oi is not None and spot is not None:
                spt = float(spot)
                b["call_oi_dollars"] += oi * mult * spt
                if delta_ok:
                    b["call_dex_dollars"] += delta * oi * mult * spt
                if gamma_ok:
                    b["call_gex_1pct"] += gamma * oi * mult * spt * spt * 0.01  # $-GEX per 1% spot move
                # RC-211: exact BS vanna from the shared d1/d2 faucet (math_levels.bs_vanna,
                # independently FD-verified). The prior vega/(S*sigma) shortcut dropped the
                # -d2 factor: always positive, wrong sign below spot, wrong magnitude.
                _iv_ok = iv is not None and iv > 0 and iv != MISSING_GREEK_SENTINEL and math.isfinite(iv)
                _T = _tte_memo(ct.get("expirationDate"))
                if _iv_ok and _T is not None and _T > 0:
                    from math_levels import bs_vanna as _bsv
                    # Cursor-audit F7: route through the ONE IV-conversion authority instead of an
                    # inline _iv/100.0. Charm (compute_net_charm) and levels (_contract_inputs)
                    # already use schwab_iv_to_sigma; vanna alone re-encoded the raw conversion,
                    # breaking the single-authority guarantee and lacking the >3.0 units-flip guard.
                    _sig = schwab_iv_to_sigma(iv)
                    _vn = _bsv(spt, float(strike), _T, _sig) if _sig is not None else None
                    if _vn is not None:
                        b["call_vanna"] += _vn * oi * mult
        elif side == "PUT":
            if oi is not None:
                prev = b.get("put_oi")
                b["put_oi"] = oi if prev is None else float(prev) + oi
                b["put_oi_mult"] += oi * mult
            if oi is not None and delta_ok:
                b["put_delta"] += delta * oi * mult
                b["has_valid_delta"] = True
            if oi is not None and gamma_ok:
                b["put_gamma"] += gamma * oi * mult
                b["has_valid_gamma"] = True
            if oi is not None and spot is not None:
                spt = float(spot)
                b["put_oi_dollars"] += oi * mult * spt
                if delta_ok:
                    b["put_dex_dollars"] += delta * oi * mult * spt
                if gamma_ok:
                    b["put_gex_1pct"] += gamma * oi * mult * spt * spt * 0.01   # $-GEX per 1% spot move
                # RC-211: same exact-vanna faucet as the CALL side (vanna is IDENTICAL for
                # calls and puts at a strike/expiry — any split comes from OI, never math).
                _iv_ok = iv is not None and iv > 0 and iv != MISSING_GREEK_SENTINEL and math.isfinite(iv)
                _T = _tte_memo(ct.get("expirationDate"))
                if _iv_ok and _T is not None and _T > 0:
                    from math_levels import bs_vanna as _bsv
                    # Cursor-audit F7: single IV-conversion authority (see CALL side above).
                    _sig = schwab_iv_to_sigma(iv)
                    _vn = _bsv(spt, float(strike), _T, _sig) if _sig is not None else None
                    if _vn is not None:
                        b["put_vanna"] += _vn * oi * mult
        else:
            continue

    for strike, b in exposures.items():
        _exclude_if_invalid(b)
        b["dollarized"] = spot is not None
        b["net_gamma"] = b["call_gamma"] - b["put_gamma"]
        b["net_delta"] = b["call_delta"] + b["put_delta"]
        # Dollarized net fields (remain 0.0 if spot is None)
        b["net_dex_dollars"] = b.get("call_dex_dollars", 0.0) + b.get("put_dex_dollars", 0.0)
        b["net_gex_1pct"] = b.get("call_gex_1pct", 0.0) - b.get("put_gex_1pct", 0.0)
        b["total_oi_dollars"] = b.get("call_oi_dollars", 0.0) + b.get("put_oi_dollars", 0.0)

    return exposures, _diagnostics(total, used, missing, excluded)


def _diagnostics(total: int, used: int, missing: int, excluded: tuple = ()) -> ExposureDiagnostics:
    note = "OK"
    if used == 0:
        note = "No usable contracts (OI filtered or chain empty)."
    elif missing == used:
        note = "All greeks missing (-999). You will still get OI center; gamma/delta pin/inf may be N/A until RTH."
    return ExposureDiagnostics(contracts_total=total, contracts_used=used,
                               greeks_missing=missing, note=note, excluded=tuple(excluded))


def exposure_books(contracts: List[dict], *, spot: float | None, now=None
                   ) -> "Dict[tuple[str, float | None], tuple[Dict[float, dict], ExposureDiagnostics]]":
    """compute_exposures_by_strike (require_oi=True) once per (expiration date, days to
    expiry) group. Every contract is priced once; any subset of expiries is then a
    merge_exposure_books of its groups (the full book, 0DTE, the front expiry, <=7 / >7 days)."""
    groups: "dict[tuple[str, float | None], list]" = {}
    for ct in contracts or []:
        if isinstance(ct, dict):
            key = (str(ct.get("expirationDate") or "")[:10], _f(ct.get("daysToExpiration")))
            groups.setdefault(key, []).append(ct)
    return {k: compute_exposures_by_strike(cs, spot=spot, require_oi=True, now=now)
            for k, cs in groups.items()}


def merge_exposure_books(books) -> "tuple[Dict[float, dict], ExposureDiagnostics]":
    """One book from books over DISJOINT contracts -- the same result one
    compute_exposures_by_strike call over all their contracts gives (up to float addition
    order): every bucket field is a per-contract sum or an OR of a per-contract flag, and a
    leg no contract reported stays None (None + x = x)."""
    merged: Dict[float, dict] = {}
    total = used = missing = 0
    excluded: list = []
    for exposures, diag in books:
        total += diag.contracts_total
        used += diag.contracts_used
        missing += diag.greeks_missing
        excluded.extend(diag.excluded)
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
    for b in merged.values():
        _exclude_if_invalid(b)
    return merged, _diagnostics(total, used, missing, excluded)


def _exclude_if_invalid(b: dict) -> None:
    """A strike holding a contract with invalid Greeks has no valid gamma or delta: its Greek
    fields are a partial sum, never shown as the strike's value."""
    if b.get("greeks_invalid"):
        b["has_valid_gamma"] = False
        b["has_valid_delta"] = False


#: The per-strike bucket fields that are flags (OR-ed when books merge); every other field is
#: a sum, None when no contract reported it (_strike_bucket, compute_exposures_by_strike).
_BUCKET_FLAGS = frozenset({"has_oi", "has_valid_gamma", "has_valid_delta", "dollarized"})


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
_STREAMED_GREEK_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("gamma", "gamma", "gamma_ts_recv"),
    ("delta", "delta", "delta_ts_recv"),
    ("open_interest", "openInterest", "open_interest_ts_recv"),
    ("total_volume", "totalVolume", "total_volume_ts_recv"),
)


def overlay_streamed_contract_fields(
    contracts: List[dict],
    streamed_by_symbol: Dict[str, dict],
    *,
    newer_than_ts: float | None = None,
    max_staleness_sec: float | None = None,
    now: float | None = None,
) -> tuple[List[dict], int]:
    """Merge freshly-streamed GAMMA/DELTA/OPEN_INTEREST onto a base REST chain contract list,
    matched by each contract's own `symbol` field (the same OSI-style option symbol the
    streaming daemon subscribes and app.options.order_flow.state keys its per-symbol state by).

    Sparse, non-destructive, and PURE (returns a new list; `contracts` and its dicts are never
    mutated): a contract absent from `streamed_by_symbol`, or one whose streamed entry carries
    none of the three fields, is passed through UNCHANGED (same dict, not a copy) -- only a
    contract that actually gets at least one field overlaid is copied. This is the same "fill
    fresher, never fabricate" discipline as live_market_plane's quote overlay, applied to the
    exposure faucet's own inputs instead of a second exposure computation.

    `newer_than_ts` is the FALLBACK precedence baseline, used only for a contract that
    carries no native vendor observation time of its own (see `quoteTimeInLong` below) --
    e.g. a test fixture or non-Schwab-shaped dict. Independent-review finding (2026-09-12):
    "being received within ten seconds does not establish that a stream value is newer than
    the REST input it replaces." A streamed value 8 seconds old is not "fresher" than a REST
    snapshot fetched 2 seconds ago just because 8 < some absolute bound; it is fresher only
    when it is more recent than the baseline it would override.

    A FIFTH independent review (2026-09-13), REPRODUCED: a single scalar `newer_than_ts`
    (the REST FETCH's own completion instant, the same for every contract in the response)
    is the wrong baseline whenever the vendor's OWN report for a SPECIFIC contract already
    lagged behind that instant -- Schwab's chain contracts each carry their own
    `quoteTimeInLong` (epoch ms), and an illiquid strike can genuinely go un-requoted for
    tens of seconds inside one otherwise-fresh chain response. Reproduced: REST fetch
    completes "now", but this contract's own `quoteTimeInLong` is "now-30s" (its last real
    quote); a stream tick for the SAME contract received at "now-1s" is genuinely newer than
    what the vendor itself last reported for it -- yet comparing against the fetch's
    completion instant ("now") wrongly rejected it as not-newer-enough. Fixed: each
    contract's own native `quoteTimeInLong`, when present, IS this contract's precedence
    baseline (never the shared fetch-completion instant); `newer_than_ts` only fills in for
    a contract that has no native observation time to compare against.

    `max_staleness_sec`, when given, is a SEPARATE, secondary absolute-age guard (relative
    to `now`, defaulting to the real clock) -- a streamed value can be newer than a
    long-stale baseline while still being, in absolute terms, too old for any consumer to
    trust (e.g. the REST cycle itself has been down for an hour). Composable with
    `newer_than_ts`; either, both, or neither may be supplied.

    Returns (new_contracts, overlaid_count) -- the count is for tests and latency/coverage
    diagnostics, never load-bearing for the projection itself.
    """
    if not contracts:
        return [], 0
    if not streamed_by_symbol:
        return list(contracts), 0
    if max_staleness_sec is not None and now is None:
        import time as _time
        now = _time.time()
    out: List[dict] = []
    overlaid = 0
    for ct in contracts:
        sym = ct.get("symbol") if isinstance(ct, dict) else None
        streamed = streamed_by_symbol.get(sym) if sym else None
        if not streamed:
            out.append(ct)
            continue
        # This contract's OWN vendor-reported observation time, not the shared REST-fetch
        # instant -- see the docstring's fifth-review finding. Schwab reports
        # `quoteTimeInLong` in epoch milliseconds; `_ts_recv` values are epoch seconds.
        native_qt = ct.get("quoteTimeInLong") if isinstance(ct, dict) else None  # external-key-ok: Schwab option-chain contract field (vendor wire, epoch ms)
        try:
            native_baseline = float(native_qt) / 1000.0 if native_qt else None
        except (TypeError, ValueError):
            native_baseline = None
        baseline = native_baseline if native_baseline is not None else newer_than_ts
        new_ct = None
        for streamed_key, chain_key, ts_key in _STREAMED_GREEK_FIELDS:
            val = streamed.get(streamed_key)
            if val is None:
                continue
            ts = streamed.get(ts_key)
            if baseline is not None and (ts is None or ts <= baseline):
                continue
            if max_staleness_sec is not None and (ts is None or (now - ts) > max_staleness_sec):
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

def _nearest_strike(strikes: List[float], spot: float) -> float:
    # Deterministic tie-break: lower strike if equal distance
    best = None
    best_d = None
    for s in sorted(strikes):
        d = abs(s - spot)
        if best is None or d < best_d:
            best = s
            best_d = d
    return float(best)

def _window_strikes(strikes: List[float], spot: float, window: int) -> List[float]:
    strikes_sorted = sorted(strikes)
    center = _nearest_strike(strikes_sorted, spot)
    idx = strikes_sorted.index(center)
    lo = max(0, idx - window)
    hi = min(len(strikes_sorted), idx + window + 1)
    return strikes_sorted[lo:hi]


# ── Institutional key-level primitives (single source of truth) ───────────────
# Window policy for UI/chart key levels: full option chain (CONSENSUS), not ATM±N.
KEY_LEVEL_STRIKE_WINDOW: int | None = None

# Dollar GEX per 1% spot move: gamma × OI × mult × spot² × 0.01 (see compute_exposures_by_strike).


def strike_flow_legs(bucket: dict) -> dict[str, float] | None:
    """{call_bid, call_ask, put_bid, put_ask, call_volume, put_volume} at one strike when every
    contract there reported its sizes and volume; None otherwise. An absent side is a known 0
    (no contract on it). The ONE reader for option-flow sums (2026-09-24)."""
    if (not isinstance(bucket, dict) or bucket.get("size_unreported") != 0
            or bucket.get("volume_unreported") != 0):
        return None
    out: dict[str, float] = {}
    for key, name in (("call_bid_size", "call_bid"), ("call_ask_size", "call_ask"),
                      ("put_bid_size", "put_bid"), ("put_ask_size", "put_ask"),
                      ("call_volume", "call_volume"), ("put_volume", "put_volume")):
        if bucket.get(key) is None:
            out[name] = 0.0
            continue
        v = bucket_metric(bucket, key)
        if v is None:
            return None
        out[name] = v
    return out


def strike_total_oi(bucket: dict) -> float | None:
    """THE total open interest at one strike, or None when it is not known.

    Known = every contract at the strike reported openInterest (oi_unreported == 0). A leg
    with no positive-OI contract then contributes a real 0 (its contracts reported 0 OI, or
    none is listed). Replaces three readers that disagreed: one required BOTH legs (dropping
    every one-sided strike from PCR / OI center / max pain), two counted a missing leg as 0
    whether or not its OI was reported (audit T-04 / M-06 / M-07 / M-08, 2026-09-24)."""
    legs = strike_oi_legs(bucket)
    return None if legs is None else legs[0] + legs[1]


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
    = Σ call_vanna − Σ put_vanna over the ONE exposures book (per-strike values are the
    exact Black-Scholes bs_vanna since RC-211, accumulated ·OI·mult at parse time). Per VOL-POINT = /100;
    dollars per vol-pt = × spot. Positive net: IV UP forces dealer delta up → they SELL
    into vol spikes; IV DOWN (crush) → they BUY, the vanna-tailwind rally mechanic.
    FAIL-CLOSED: None on an empty/valueless book or missing spot.
    """
    if not exposures or spot is None or spot <= 0:
        return None
    call_v = 0.0
    put_v = 0.0
    seen = False
    for b in exposures.values():
        if not isinstance(b, dict) or b.get("greeks_invalid"):
            continue                        # an excluded strike is excluded from every total
        c = b.get("call_vanna")
        p = b.get("put_vanna")
        if c is not None:
            call_v += float(c); seen = True
        if p is not None:
            put_v += float(p); seen = True
    if not seen:
        return None
    net_shares_per_volpt = (call_v - put_v) / 100.0
    return {"net_vanna_dollars_per_volpt": round(net_shares_per_volpt * float(spot), 2),
            "net_vanna_shares_per_volpt": round(net_shares_per_volpt, 2)}


def compute_net_dex_dollars(exposures: dict) -> dict | None:
    """RC-361: aggregate dealer DELTA notional (DEX $) — the directional complement to GEX.

    Same naive dealer-sign model as GEX (dealer long calls, short puts): the dealer's net
    delta book = Σ call_dex_dollars − Σ put_dex_dollars over the ONE exposures book (put
    deltas are negative, so subtracting the put leg flips it to the dealer's side
    correctly). FAIL-CLOSED: None on an empty/degenerate book — never a fabricated $0.
    Returns {net_dex, call_dex, put_dex} in dollars.
    """
    if not exposures:
        return None
    call_dex = 0.0
    put_dex = 0.0
    seen = False
    for b in exposures.values():
        if not isinstance(b, dict):
            continue
        c = b.get("call_dex_dollars")
        p = b.get("put_dex_dollars")
        if c is not None:
            call_dex += float(c); seen = True
        if p is not None:
            put_dex += float(p); seen = True
    if not seen:
        return None
    return {"net_dex": round(call_dex - put_dex, 2),
            "call_dex": round(call_dex, 2), "put_dex": round(put_dex, 2)}


def compute_delta_oi_walls(
    today: dict[float, tuple[float | None, float | None]],
    prev: dict[float, tuple[float | None, float | None]],
) -> dict | None:
    """RC-359: overnight ΔOI walls — where positioning BUILT (defend) vs UNWOUND (fade).

    today/prev = {strike: (call_oi, put_oi)} from the SAME exposures book, banked daily. Only a
    strike present in BOTH days has a change: a strike missing from yesterday's bank is not
    known to have had zero (the bank before 2026-09-25 held only a strike window).
    FAIL-CLOSED: None when no prior session is banked or today is empty.
    Returns {call_build_strike, call_build_doi, put_build_strike, put_build_doi,
             unwind_strike, unwind_doi} — build fields None when nothing grew.
    """
    if not prev or not today:
        return None
    d_call: dict[float, float] = {}
    d_put: dict[float, float] = {}
    for k, (c, p) in today.items():
        if k not in prev:
            continue
        pc, pp = prev[k]
        if c is not None and pc is not None:
            d_call[k] = float(c) - float(pc)
        if p is not None and pp is not None:
            d_put[k] = float(p) - float(pp)
    out: dict[str, float | None] = {
        "call_build_strike": None, "call_build_doi": None,
        "put_build_strike": None, "put_build_doi": None,
        "unwind_strike": None, "unwind_doi": None,
    }
    grew_c = {k: v for k, v in d_call.items() if v > 0}
    grew_p = {k: v for k, v in d_put.items() if v > 0}
    if grew_c:
        k = max(grew_c, key=lambda s: grew_c[s])
        out["call_build_strike"], out["call_build_doi"] = k, round(grew_c[k])
    if grew_p:
        k = max(grew_p, key=lambda s: grew_p[s])
        out["put_build_strike"], out["put_build_doi"] = k, round(grew_p[k])
    total = {k: d_call.get(k, 0.0) + d_put.get(k, 0.0) for k in set(d_call) | set(d_put)}
    shrank = {k: v for k, v in total.items() if v < 0}
    if shrank:
        k = min(shrank, key=lambda s: shrank[s])
        out["unwind_strike"], out["unwind_doi"] = k, round(shrank[k])
    return out


def compute_zero_dte_gamma_share(
    exposures_all: dict, exposures_0dte: dict
) -> float | None:
    """RC-357: % of the dealer gamma book from SAME-DAY expiry — the level-persistence read.

    share = sum(|net_gex_1pct|) over the 0DTE book / sum(|net_gex_1pct|) over the full book,
    BOTH books from the ONE producer (compute_exposures_by_strike; the 0DTE book is the same
    call with use_only_dte_max=0 — same parser, same sign model, zero new math). High share
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


def net_gamma_raw_at_strike(bucket: dict) -> float | None:
    return bucket_metric(bucket, "net_gamma")


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


def pick_net_gex_peak_strike(
    exposures: Dict[float, dict],
    strikes: List[float],
    *,
    institutional: bool = True,
) -> float | None:
    """
    Net-GEX peak: strike with largest |net GEX$| per 1% (calls minus puts).
    RC-124: this WAS displayed as "gamma pin" — a non-standard use of that name; the standard
    pin is total gamma (pick_pin_and_strength). The net peak remains a real measure of where
    the SIGNED book concentrates, and it keeps its row under its own name.
    When institutional=True and spot/dollar GEX unavailable, returns None (no raw fallback).
  """
    if exposures_have_dollar_gex(exposures):
        s, _ = _pick_strike_max_metric(
            exposures, strikes, lambda b: bucket_metric_abs(b, "net_gex_1pct")
        )
        return round(s, 2) if s is not None else None
    if institutional:
        return None
    s, _ = _pick_strike_max_metric(
        exposures, strikes, lambda b: bucket_metric_abs(b, "net_gamma")
    )
    return round(s, 2) if s is not None else None


def pick_hvl_strike(exposures: Dict[float, dict], strikes: List[float]) -> float | None:
    """
    HVL: strike with largest total gamma concentration.
    Institutional: max (|call GEX$| + |put GEX$|); fallback: max (|call_γ| + |put_γ|).
    """
    if exposures_have_dollar_gex(exposures):
        s, _ = _pick_strike_max_metric(exposures, strikes, total_gex_dollars_at_strike)
        return round(s, 2) if s is not None else None
    s, _ = _pick_strike_max_metric(exposures, strikes, total_gamma_raw_at_strike)
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
    """Call/put gamma walls: max |side GEX$| (or |side γ| fallback)."""
    if exposures_have_dollar_gex(exposures):
        return (
            _pick_strike_max_metric(
                exposures, strikes, lambda b: bucket_metric_abs(b, "call_gex_1pct")
            ),
            _pick_strike_max_metric(
                exposures, strikes, lambda b: bucket_metric_abs(b, "put_gex_1pct")
            ),
        )
    return (
        _pick_strike_max_metric(
            exposures, strikes, lambda b: bucket_metric_abs(b, "call_gamma")
        ),
        _pick_strike_max_metric(
            exposures, strikes, lambda b: bucket_metric_abs(b, "put_gamma")
        ),
    )


def pick_delta_wall_strikes(
    exposures: Dict[float, dict], strikes: List[float]
) -> tuple[tuple[float | None, float | None], tuple[float | None, float | None]]:
    if exposures_have_dollar_gex(exposures):
        return (
            _pick_strike_max_metric(
                exposures, strikes, lambda b: bucket_metric_abs(b, "call_dex_dollars")
            ),
            _pick_strike_max_metric(
                exposures, strikes, lambda b: bucket_metric_abs(b, "put_dex_dollars")
            ),
        )
    return (
        _pick_strike_max_metric(
            exposures, strikes, lambda b: bucket_metric_abs(b, "call_delta")
        ),
        _pick_strike_max_metric(
            exposures, strikes, lambda b: bucket_metric_abs(b, "put_delta")
        ),
    )


def aggregate_net_gex(exposures: Dict[float, dict], strikes: List[float]) -> float | None:
    """Chain-aggregate net GEX$ = sum of net_gex_1pct over strikes whose gamma was VALID, on a
    spot-built (dollarized) book. None when there is no such strike or no spot -- never a raw
    net_gamma total in other units, never the 0.0 an all-invalid bucket carries from its
    initialiser (audit M-02, 2026-09-24: no fallbacks)."""
    if not strikes or not exposures_have_dollar_gex(exposures):
        return None
    total = 0.0
    any_v = False
    for s in strikes:
        b = exposures.get(s, {})
        if not b.get("has_valid_gamma"):
            continue
        v = net_gex_dollars_at_strike(b)
        if v is not None:
            total += v
            any_v = True
    return float(total) if any_v else None


def aggregate_net_dex(exposures: Dict[float, dict], strikes: List[float]) -> float | None:
    """Chain-aggregate net DEX$ = sum of net_dex_dollars over strikes whose delta was VALID,
    on a dollarized book. None otherwise. It used to pick its units on a GAMMA test and fall
    to raw net_delta (shares), and an all-invalid-delta book read 0.0 -- which The Call's
    regime vote reads as "net delta >= 0" = a LONG vote from no data (audit M-01)."""
    if not strikes or not exposures_have_dollar_gex(exposures):
        return None
    total = 0.0
    any_v = False
    for s in strikes:
        b = exposures.get(s, {})
        if not b.get("has_valid_delta"):
            continue
        v = bucket_metric(b, "net_dex_dollars")
        if v is not None:
            total += v
            any_v = True
    return float(total) if any_v else None


def gex_magnitude_label(net_gex: float | None) -> str | None:
    """None when there is no net GEX -- absent is never labelled "negligible" (audit,
    2026-09-23)."""
    if net_gex is None:
        return None
    a = abs(float(net_gex))
    if a >= 50_000_000:
        return "large"
    if a >= 10_000_000:
        return "moderate"
    if a >= 1_000_000:
        return "small"
    return "negligible"


def gex_regime_label(net_gex: float | None) -> str:
    if net_gex is None or abs(float(net_gex)) < 1e-6:
        return "neutral"
    return "positive" if float(net_gex) > 0 else "negative"


# ── Validation / sanitization ────────────────────────────────────────────────

def greeks_validity(contracts_used: int, greeks_missing: int) -> bool:
    """Return True if dealer metrics (DEX/GEX) are usable based on greek availability."""
    try:
        cu = int(contracts_used)
        gm = int(greeks_missing)
    except Exception:
        return False
    if cu <= 0:
        return False
    if gm >= cu:
        return False
    return True


def sanitize_dealer_metrics(net_dex_dollars, net_gex_1pct, *, contracts_used: int, greeks_missing: int):
    """Return (net_dex, net_gex, dealer_valid). If not valid, net_dex/net_gex are None."""
    valid = greeks_validity(contracts_used, greeks_missing)
    if not valid:
        return None, None, False
    return net_dex_dollars, net_gex_1pct, True


# ── Exposure aggregation ─────────────────────────────────────────────────────

def window_summary(exposures_by_strike: dict[float, dict], spot: float, strike_window: int) -> dict[str, float]:
    """Aggregate exposure outputs across an ATM-centered strike window.

    This is *math layer* because it is part of the exposure aggregation pipeline and must be consistent across UIs.
    """
    strikes = sorted([float(k) for k in (exposures_by_strike or {}).keys()])
    if not strikes:
        return {"spot": float(spot), "atm": float(spot), "net_gex_1pct": 0.0, "net_dex_dollars": 0.0, "total_oi_dollars": 0.0}
    atm = min(strikes, key=lambda x: abs(x - float(spot)))
    lo = atm - float(strike_window)
    hi = atm + float(strike_window)
    use = [k for k in strikes if lo <= k <= hi]
    net_gex = net_dex = tot_oi = 0.0
    for k in use:
        b = exposures_by_strike.get(k, {}) or {}
        g = bucket_metric(b, "net_gex_1pct")
        d = bucket_metric(b, "net_dex_dollars")
        o = bucket_metric(b, "total_oi_dollars")
        if g is not None:
            net_gex += float(g)
        if d is not None:
            net_dex += float(d)
        if o is not None:
            tot_oi += float(o)
    return {"spot": float(spot), "atm": float(atm), "net_gex_1pct": float(net_gex), "net_dex_dollars": float(net_dex), "total_oi_dollars": float(tot_oi)}

def strike_agg(exposures, strike):
    return dict(exposures.get(float(strike), {}))


# ── Charm ─────────────────────────────────────────────────────────────────────

def compute_net_charm(
    contracts: list,
    spot: float,
    expiry: str,
    *,
    rate: float = 0.05,
    drift_toward_strike: float | None = None,
    now=None,
) -> dict:
    """
    Compute dealer net charm exposure for a given expiry.

    CHARM = dDelta/dt — the rate at which dealer delta hedges decay with time.
    As expiry approaches, dealers must unwind their delta hedges. The NET direction
    of that unwind creates mechanical buying or selling pressure independent of price.

    Formula ACTUALLY IMPLEMENTED (see line ~788) — corrected 2026-07-19 to match the code:

        charm_unit = -phi(d1) * d2 / (2*T)          # delta per YEAR
        d1 = [ln(S/K) + (iv^2/2)*T] / (iv*sqrt(T))
        d2 = d1 - iv*sqrt(T)
        phi = standard normal PDF

    Relation to the textbook (Haug) charm, dDelta/dT for a call with q=0:

        dDelta/dT = -phi(d1) * [ r/(iv*sqrt(T)) - d2/(2T) ]

    Ours is dDelta/dt (CALENDAR time — as the trading day passes and T shrinks), with the
    r/(iv*sqrt(T)) term DELIBERATELY OMITTED because it explodes as T->0 (0DTE). At r=0
    that leaves  charm = +phi(d1) * d2 / (2T)  — exactly the formula above evaluated at
    r=0, which IS the calendar-time charm.
    SIGN CORRECTED 2026-07-25: a prior revision negated this to -phi*d2/(2T) on the claim
    "ours = -dDelta/dT", which INVERTED the direction — charm_direction reported "buying"
    when the dealer flow was selling (measured: sign-inverted vs the correct convention on
    70-79% of real SPY/QQQ/IWM states, exact-negation of the per-strike bs_charm path). A
    direct finite-difference of Black-Scholes delta as calendar time advances,
    (delta(T-1d)-delta(T))/dt, proves calendar charm = +phi*d2/(2T) (= math_levels.bs_charm
    at r=0) for ATM/ITM/OTM alike. The r-omission still costs accuracy that grows with T and
    rate (~6% 0DTE ATM, ~17% 7d, ~71% 3-month ATM at r=0.05); acceptable for the near-expiry
    use this feeds. The scalar here and the per-strike compute_charm_by_strike agree on
    DIRECTION and, since RC-42 unified both on time_et.time_to_expiry_years, on T as well —
    the once-tracked "hours-to-close vs 0.5-day floor" magnitude gap no longer exists in
    code (RC-179 closed it as a stale claim; parity measured at 0.02% on a real 0DTE book).

    NOTE: the ``rate`` parameter is therefore NOT used in the charm computation.

    Put charm: with q=0, Delta_put = Delta_call - 1, and the constant vanishes under
    d/dt, so charm_put == charm_call. That identity is why both sides use one formula.
    AGGREGATION IS DEALER-SIGNED (RC-179, convention pinned 2026-08-01 by operator order):
    ``net = call_charm - put_charm`` — the SAME +call/-put dealer book assumption as net
    GEX and the per-strike compute_charm_by_strike path, so ``net_charm_daily`` IS a
    dealer-signed directional flow and its sign may be read as dealer direction. An older
    revision of this paragraph claimed the two sides were summed with the same sign; the
    code below never did that after the 2026-07-25 correction, and the claim survived only
    in prose. MEASURED parity on the real SPY 2026-07-31 0DTE book (put-heavy, 782,222 put
    OI vs 530,996 call): scalar -3,529,621.8 vs per-strike dealer-signed sum -3,528,882.8
    (0.02%, the scalar's extra plausibility gates account for the gap), against a same-sign
    gross of +5,907,087.6 — the sign itself is the proof the dealer convention is live.
    Locked by tests/test_charm_sign_finite_difference.py (parity + put-heavy sign-flip).

    Dealer position: market makers are typically SHORT options (sold to retail).

    RC-296 — READ THIS BEFORE WRITING A PER-SIDE HEDGING STORY HERE. Two previous
    revisions of this paragraph were wrong in opposite ways: the original inverted both
    hedge legs, and RC-294's correction replaced that with "calls sell, puts buy", which
    is also false. Both mistakes came from reasoning about the option SIDE instead of
    reading the function that computes the number.

    PER-CONTRACT CHARM IS SIDE-INDEPENDENT. `math_levels.bs_charm(spot, strike, t_years,
    sigma, rate)` takes NO call/put argument — one strike yields one charm value — and at
    q=0 charm_put equals charm_call, which the DEALER SIGN CONVENTION comment further down
    has always said. There is no "call behaviour" and "put behaviour" to describe.

    ITS SIGN IS A FUNCTION OF MONEYNESS, not of side. MEASURED at spot 100, T=0.08,
    sigma=0.20: K=90 → +0.7654, K=100 → −0.0705, K=105 → −1.5684. Positive below spot,
    negative above.

    DEALER DIRECTION ENTERS ONLY THROUGH THE BOOK. Because the per-contract value is equal
    on both sides, the direction in `net = call_charm - put_charm` comes from the OI
    IMBALANCE between the call and put books at each strike — not from a story about how
    one side hedges. That convention (+call/−put, shared with net GEX) is RC-179-locked and
    measured; see the parity figures above and tests/test_charm_sign_finite_difference.py.
    Correcting this prose does not and must not move the arithmetic.

    Net charm > 0 → net dealer delta buying  → Bullish flow
    Net charm < 0 → net dealer delta selling → Bearish flow

    drift_toward_strike: caller-supplied, and the caller (server.py `_institutional_pin`)
        passes `pick_net_gex_peak_strike` over the SELECTED EXPIRY — NOT
        `pick_pin_and_strength`, which is terrain's max-TOTAL-gamma strike over the wide
        multi-expiry book. This docstring named the wrong function until RC-294 and the
        two differ whenever magnitude and signed-net peak separate (RC-292).
        Charm performs NO computation with this value: it is republished unchanged, under
        the single name `drift_toward` (RC-302 deleted the `gamma_pin` duplicate; this
        paragraph still claimed both names until RC-315, contradicting the Returns section
        four lines below it). Charm measures directional hedge DECAY; it does not compute a
        price attractor, so treat this as a caller's label travelling through, never as
        charm's own target. RC-315: charm should publish NO "toward" strike at all without
        an independently validated directional mechanism — neither the net-GEX peak nor the
        absolute-gamma strike is a demonstrated magnet. RC-345 / F18: the server caller now
        passes drift_toward_strike=None (the net-GEX-peak substitution was removed end-to-end,
        including the Key Levels "Charm Drift" UI row), so drift_toward is WITHHELD. Charm
        publishes DIRECTION (charm_direction / net_charm sign), never a borrowed target strike.

    Returns:
        net_charm_daily  : net delta-equivalents unwound per day (negative = selling)
        charm_direction  : "buying" | "selling" | "neutral"  (for signals engine)
        drift_toward     : drift_toward_strike when provided — the caller's strike,
                           republished unchanged. RC-302 removed the duplicate `gamma_pin`
                           key that carried the same value under terrain's name.
        contracts_used   : number of contracts that contributed
    """
    try:
        _target_exp = str(expiry)[:10]
        if len(_target_exp) != 10:
            _target_exp = None
    except Exception:
        _target_exp = None

    # SINGLE SOURCE of T: intraday time-to-session-close (time_et.time_to_expiry_years),
    # ACT/365, from `now` (defaults to now_et()). Replaces the old hours-to-close / day-count
    # split — the 0DTE branch only approximated it (hardcoded 16:00, 0.5h floor) and the
    # dte/365 branch ignored the intraday fraction entirely, so the two charm engines
    # disagreed near expiry (RC-42 / RC-37; validated against Schwab-reported gamma).
    from time_et import time_to_expiry_years as _tte
    # RC-224 / census #6: unit charm from the ONE greek-formula faucet (not inline).
    from math_levels import bs_charm as _bs_charm

    # RC-245: T is a pure function of (expirationDate, now) and every contract in this
    # aggregate resolves the SAME expiry, so the per-contract call did the work of one 188
    # times (MEASURED: 21% of warm runtime). Worse than the cost: with now=None each call
    # re-read the clock, so contracts summed into ONE number were priced at instants that
    # drifted across the loop. Pinning `now` once makes the aggregate internally consistent
    # — a single figure now describes a single moment — and memoising per distinct expiry
    # string makes it cheap. Values are unchanged: same inputs, same formula, same faucet.
    if now is None:
        from time_et import now_et as _now_et

        now = _now_et()
    _tte_cache: dict[str, float | None] = {}

    def _tte_memo(exp_raw) -> float | None:
        key = str(exp_raw)
        if key not in _tte_cache:
            _tte_cache[key] = _tte(exp_raw, now=now)
        return _tte_cache[key]

    call_charm = put_charm = 0.0
    used = 0
    _input_n = len(contracts)
    _skip_expiry = _skip_side = _skip_fields = _skip_oi = _skip_mult = 0
    _skip_gamma = _skip_iv = _skip_T = _skip_math = 0

    for ct in contracts:
        # Filter to target expiry
        ct_exp = ct.get("expirationDate")
        if ct_exp and _target_exp:
            if str(ct_exp)[:10] != _target_exp:
                _skip_expiry += 1
                continue
        elif _target_exp:
            _skip_expiry += 1
            continue

        side    = (ct.get("putCall") or "").upper().strip()
        if side not in ("CALL", "PUT"):
            _skip_side += 1
            continue

        strike  = _f(ct.get("strikePrice"))
        gamma   = _f(ct.get("gamma"))
        iv      = _f(ct.get("volatility"))
        oi      = _f(ct.get("openInterest"))
        mult    = _f(ct.get("multiplier"))

        if gamma is None or strike is None:
            _skip_fields += 1
            continue
        if oi is None or oi <= 0:
            _skip_oi += 1
            continue
        if mult is None or mult <= 0:
            _skip_mult += 1
            continue
        if not gamma_is_plausible(gamma, iv=iv):
            _skip_gamma += 1
            continue
        if iv is None or iv <= 0 or iv == MISSING_GREEK_SENTINEL or not math.isfinite(iv):
            _skip_iv += 1
            continue

        T = _tte_memo(ct.get("expirationDate"))
        if T is None or T <= 0:
            _skip_T += 1
            continue

        iv_dec = schwab_iv_to_sigma(iv)
        if iv_dec is None or iv_dec <= 0:
            _skip_iv += 1
            continue
        S      = float(spot)
        K      = float(strike)

        # RC-224 / census #6: ONE greek-formula faucet — math_levels.bs_charm.
        # rate=0 keeps the deliberate r-term omission for 0DTE stability (same numeric
        # identity the prior inline +phi(d1)*d2/(2T) encoded; RC-179 parity locks).
        charm_unit = _bs_charm(S, K, float(T), float(iv_dec), rate=0.0)
        if charm_unit is None:
            _skip_math += 1
            continue

        # For puts: by put-call parity, charm_put = charm_call (same sign, same magnitude
        # at ATM; put delta decays symmetrically to call delta). Use same formula.
        # Daily aggregate: charm_unit/365 * OI * mult
        weighted = charm_unit / 365.0 * oi * mult

        if side == "CALL":
            call_charm += weighted
        else:
            put_charm  += weighted
        del weighted  # summed with the dealer convention below, never here

        used += 1

    if used <= 0:
        if _input_n == 0:
            _err = f"No contracts provided for expiry={_target_exp}"
        elif _skip_expiry == _input_n:
            _err = f"No contracts with expirationDate matching expiry={_target_exp} (input={_input_n})"
        else:
            _err = (
                f"No contracts passed charm quality gates for expiry={_target_exp} "
                f"(input={_input_n}, skipped: expiry={_skip_expiry}, oi={_skip_oi}, "
                f"gamma={_skip_gamma}, iv={_skip_iv}, mult={_skip_mult}, T={_skip_T}, "
                f"fields={_skip_fields}, side={_skip_side}, math={_skip_math})"
            )
        return {
            "net_charm_daily": None,
            "call_charm_daily": None,
            "put_charm_daily": None,
            "charm_direction": None,
            "charm_magnitude": None,
            # RC-302: `gamma_pin` REMOVED. It duplicated drift_toward exactly, had zero
            # readers repo-wide, and collided with terrain's gamma_pin — which is the
            # max-TOTAL-gamma strike over the wide book, a different metric on a different
            # chain scope from the selected-expiry net-GEX peak charm is handed here.
            "drift_toward": drift_toward_strike,
            "contracts_used": 0,
            "error": _err,
        }

    # DEALER SIGN CONVENTION (fixed 2026-07-19 — was `call_charm + put_charm`).
    #
    # charm_put == charm_call per contract (q=0), so summing the two sides produced an
    # OI-WEIGHTED MAGNITUDE with no dealer direction in it, while `charm_direction`
    # below labelled its sign "buying"/"selling" and fed that to the signals engine.
    # A prior comment claimed the sign difference was "captured in net_delta" — net_delta
    # is never referenced in this function, so no such compensation occurred.
    #
    # Charm exposure must use the SAME dealer book assumption as net GEX (+call / -put;
    # see math_levels.compute_gamma_profile). Per-strike charm exposure with this
    # convention is standard institutional practice (SpotGamma / Unusual Whales publish
    # it, and attribute the end-of-day pin to charm pressure).
    net = call_charm - put_charm

    # Direction: positive net = dealers net buying delta (bullish), negative = selling (bearish)
    direction = "neutral" if abs(net) < 1.0 else ("buying" if net > 0 else "selling")
    abs_net = abs(net)
    if abs_net >= 5000:
        magnitude = "large"
    elif abs_net >= 1000:
        magnitude = "moderate"
    elif abs_net >= 100:
        magnitude = "small"
    else:
        magnitude = "negligible"

    return {
        "net_charm_daily": round(net, 2),
        "call_charm_daily": round(call_charm, 2),
        "put_charm_daily": round(put_charm, 2),
        "charm_direction": direction,
        "charm_magnitude": magnitude,
        # RC-302: ONE name for a value charm republishes but does not compute. The
        # `gamma_pin` alias and its intermediate variable are gone — zero readers, and the
        # name belongs to terrain's max-total-gamma strike over the wide book.
        "drift_toward": drift_toward_strike,
        "contracts_used": used,
        "error": "",
    }


# ── Greek bias ────────────────────────────────────────────────────────────────

GREEK_BIAS_DELTA_WEIGHT = 1.0
GREEK_BIAS_CHARM_WEIGHT = 0.5
GREEK_BIAS_PCOI_WEIGHT  = 0.5
GREEK_BIAS_PCOI_BEARISH = 1.3
GREEK_BIAS_PCOI_BULLISH = 0.8
GREEK_BIAS_THRESHOLD    = 0.5

def greek_bias(net_delta: float | None, charm_direction: str | None,
               put_call_oi_ratio: float | None,
               dex_magnitude: str | None = None,
               charm_magnitude: str | None = None) -> str:
    """A leg whose magnitude is unknown (None, or a label outside MAG_SCALE) contributes
    NOTHING -- it used to be scored as "moderate" (0.7), a guessed magnitude (audit P0,
    2026-09-23: no fallbacks)."""
    MAG_SCALE = {"large": 1.0, "moderate": 0.7, "small": 0.3, "negligible": 0.0}
    score = 0.0
    delta_scale = MAG_SCALE.get(dex_magnitude, 0.0) if dex_magnitude is not None else 0.0
    if net_delta is not None and delta_scale > 0:
        if net_delta > 0:
            score += GREEK_BIAS_DELTA_WEIGHT * delta_scale
        elif net_delta < 0:
            score -= GREEK_BIAS_DELTA_WEIGHT * delta_scale
    charm_scale = MAG_SCALE.get(charm_magnitude, 0.0) if charm_magnitude is not None else 0.0
    if charm_direction == "buying":
        score += GREEK_BIAS_CHARM_WEIGHT * charm_scale
    elif charm_direction == "selling":
        score -= GREEK_BIAS_CHARM_WEIGHT * charm_scale
    if put_call_oi_ratio is not None:
        if put_call_oi_ratio > GREEK_BIAS_PCOI_BEARISH:
            score -= GREEK_BIAS_PCOI_WEIGHT
        elif put_call_oi_ratio < GREEK_BIAS_PCOI_BULLISH:
            score += GREEK_BIAS_PCOI_WEIGHT
    if score > GREEK_BIAS_THRESHOLD:
        return "bullish"
    elif score < -GREEK_BIAS_THRESHOLD:
        return "bearish"
    return "neutral"


# ── Beta / returns ────────────────────────────────────────────────────────────


def compute_beta(ticker_returns: list, spy_returns: list) -> dict:
    """Compute beta from paired daily returns via OLS regression.

    Beta = Cov(ticker, SPY) / Var(SPY)

    Args:
        ticker_returns: list of float (daily % returns, e.g. [0.5, -1.2, ...])
        spy_returns:    list of float (same length, same dates)

    Returns:
        {"beta": float, "r_squared": float, "n": int}
        or {"beta": None, ...} if insufficient data.
    """

    n = min(len(ticker_returns), len(spy_returns))
    if n < 5:
        return {"beta": None, "r_squared": None, "n": n,
                "error": f"Need 5+ paired returns, have {n}"}

    tr = ticker_returns[-n:]
    sr = spy_returns[-n:]

    mean_t = sum(tr) / n
    mean_s = sum(sr) / n

    cov = sum((tr[i] - mean_t) * (sr[i] - mean_s) for i in range(n)) / n
    var_s = sum((sr[i] - mean_s) ** 2 for i in range(n)) / n

    if var_s < 1e-12:
        return {"beta": None, "r_squared": None, "n": n,
                "error": "SPY variance near zero"}

    beta = round(cov / var_s, 4)

    # R-squared
    var_t = sum((tr[i] - mean_t) ** 2 for i in range(n)) / n
    r_sq = round((cov ** 2) / (var_s * var_t), 4) if var_t > 1e-12 else None

    return {"beta": beta, "r_squared": r_sq, "n": n, "error": ""}


def compute_beta_residual(ticker_chg_pct: float, spy_chg_pct: float,
                          beta: float) -> float:
    """Beta-adjusted residual: how much the ticker moved beyond what beta implies.

    residual = ticker_chg - (spy_chg × beta)
    Positive = outperforming (stronger than market implies)
    Negative = underperforming (weaker than market implies)
    """
    return round(ticker_chg_pct - (spy_chg_pct * beta), 4)

def returns_from_candles(candles: list) -> list:
    """Extract daily close-to-close % returns from 1-min candle list.

    Groups candles by date, takes last close per day, computes daily return.
    Expects candles with 'datetime' (epoch ms) and 'close' fields.
    """
    from datetime import datetime, timezone
    from collections import OrderedDict

    daily_close = OrderedDict()
    for c in candles:
        dt_ms = c.get("datetime")
        close = c.get("close")
        if close is None or dt_ms is None:
            continue
        try:
            dt_ms = float(dt_ms)
        except (TypeError, ValueError):
            continue
        if dt_ms <= 0:
            continue
        dt = datetime.fromtimestamp(dt_ms / 1000, tz=timezone.utc)
        day = dt.strftime("%Y-%m-%d")
        daily_close[day] = float(close)  # last candle of each day wins

    closes = list(daily_close.values())
    if len(closes) < 2:
        return []

    returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            ret = (closes[i] - closes[i - 1]) / closes[i - 1] * 100.0
            returns.append(round(ret, 4))
    return returns

