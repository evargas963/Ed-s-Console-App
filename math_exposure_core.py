"""
math_exposure_core.py
Base exposure engine — raw and normalized exposure values derived
from the chain and position structure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime

from numeric_contract import float_finite_or_none
from option_contract import OptionContract, streamed_greek_set
from time_et import time_to_expiry_years

# ── Black-Scholes Greeks per share: the one place their formulas live ──

SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def bs_gamma(spot: float, strike: float, t_years: float, sigma: float) -> float | None:
    """Black-Scholes gamma per share, r = q = 0. The same gamma the profile sums."""
    if spot <= 0 or strike <= 0 or t_years <= 0 or sigma <= 0:
        return None
    vt = sigma * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + 0.5 * sigma * sigma * t_years) / vt
    if not math.isfinite(d1):
        return None
    g = _norm_pdf(d1) / (spot * vt)
    return g if math.isfinite(g) else None


def bs_delta(
    spot: float, strike: float, t_years: float, sigma: float, *, call: bool
) -> float | None:
    """Black-Scholes delta per share, r = q = 0. A put is the call delta minus one."""
    if spot <= 0 or strike <= 0 or t_years <= 0 or sigma <= 0:
        return None
    vt = sigma * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + 0.5 * sigma * sigma * t_years) / vt
    if not math.isfinite(d1):
        return None
    call_delta = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
    d = call_delta if call else call_delta - 1.0
    return d if math.isfinite(d) else None


def bs_vanna(
    spot: float, strike: float, t_years: float, sigma: float, rate: float = 0.0, div: float = 0.0
) -> float | None:
    """Black-Scholes vanna (dDelta/dSigma) per share — identical for calls and puts.

    Closed form: -e^(-qT) * phi(d1) * d2 / sigma. Sign is driven entirely by -d2, so it
    flips through SPOT (strikes above spot positive, below negative) — never through the
    call/put boundary. Equivalent forms: vanna = (vega/S)(1 - d1/(sigma*sqrt(T)))
    = -Gamma * S * sqrt(T) * d2.
    Units: delta-change per 1.00 of IV (100 vol points); multiply by 0.01 for per-vol-point
    — the sigma-scaling convention is LOCKED here beside the dealer convention.
    """
    if spot <= 0 or strike <= 0 or t_years <= 0 or sigma <= 0:
        return None
    vt = sigma * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (rate - div + 0.5 * sigma * sigma) * t_years) / vt
    d2 = d1 - vt
    v = -math.exp(-div * t_years) * _norm_pdf(d1) * d2 / sigma
    return v if math.isfinite(v) else None


def bs_charm(
    spot: float, strike: float, t_years: float, sigma: float, rate: float = 0.0
) -> float | None:
    """Black-Scholes charm (dDelta/dt, calendar time) per share, q=0.

    Textbook (Haug) charm is dDelta/dT = -phi(d1) * [ r/(sigma*sqrt(T)) - d2/(2T) ].
    Calendar-time charm is the negative of that. Callers that want the deliberate
    0DTE-stable r-omission (compute_net_charm) pass rate=0.0; the r term is otherwise
    retained and guarded by the t_years floor applied upstream.

    Identical for calls and puts at q=0: Delta_put = Delta_call - 1, and the constant
    vanishes under differentiation with respect to time.
    """
    if spot <= 0 or strike <= 0 or t_years <= 0 or sigma <= 0:
        return None
    vt = sigma * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * t_years) / vt
    d2 = d1 - vt
    # dDelta/dt (calendar time). Sign verified against a finite-difference
    # derivative of the BS delta.
    c = -_norm_pdf(d1) * (rate / vt - d2 / (2.0 * t_years))
    return c if math.isfinite(c) else None


def schwab_iv_to_sigma(iv: float | None) -> float | None:
    """The ONE conversion from Schwab's `volatility` field (a PERCENT) to a decimal sigma.

    Measured on 49,244 contracts across the 43-ticker board: min 7.967, median 51.0, max 4,256.8
    -- every value a percent, so one fixed conversion. Schwab's IV is carried as sent; a model input
    needs sigma > 0, so 0 or less gives no sigma."""
    if iv is None or iv <= 0:
        return None
    return iv / 100.0


def book_net_gex(exposures: dict) -> float | None:
    """Net dealer GEX per 1% move at spot: the sum of every strike's net_gex_1pct -- Schwab's
    gamma as sent, +call/-put. The one gamma at spot (regime, headline, pin gate). None when no
    strike carried a valid gamma."""
    vals = [v for b in exposures.values() if (v := bucket_metric(b, "net_gex_1pct")) is not None]
    return sum(vals) if vals else None


#: Bucket fields priced from Schwab's gamma / delta / volatility -> the counts of contracts on the
#: field's legs whose term is not known (see compute_exposures_by_strike). A leg with one has no
#: value for the field; every other sum is Schwab's inputs computed, 0 included.
_GREEK_FIELD_UNREPORTED = {
    f"{leg}_{field}": tuple(
        f"{s}_{greek}_unreported" for s in (("call", "put") if leg == "net" else (leg,))
    )
    for greek, fields in (
        ("gamma", ("gamma", "gex_1pct")),
        ("delta", ("delta", "dex_dollars")),
        ("vanna", ("vanna",)),
        ("oi_mult", ("oi_mult",)),
    )
    for field in fields
    for leg in ("call", "put", "net")
}


def bucket_metric(bucket: dict, key: str) -> float | None:
    """One exposure-bucket field, or None when it is not known: absent, not finite, or a Greek
    field on a leg where a contract's term is not known (see _GREEK_FIELD_UNREPORTED)."""
    if not isinstance(bucket, dict) or key not in bucket:
        return None
    if any(bucket.get(u) for u in _GREEK_FIELD_UNREPORTED.get(key, ())):
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


def _strike_bucket(exposures_by_strike: dict[float, dict], strike: float) -> dict:
    if strike not in exposures_by_strike:
        exposures_by_strike[strike] = {
            # Contracts at this strike whose openInterest was NOT REPORTED (absent, -999, text);
            # strike_total_oi() reads this so no total treats unknown as zero.
            "oi_unreported": 0,
            # Same discipline for totalVolume: an unreported one is UNKNOWN, never zero.
            "volume_unreported": 0,
            # Contracts on each leg whose gamma / delta / vanna term is not known: openInterest or
            # multiplier not reported, or open interest above 0 with no Greek (Schwab sent -999 or
            # none). That leg's sum of it is not known; a contract with open interest 0 adds 0.
            **{
                f"{s}_{g}_unreported": 0
                for s in ("call", "put")
                for g in ("gamma", "delta", "vanna", "oi_mult")
            },
            # True when the book was built WITH spot, i.e. the *_dollars / *_gex_1pct fields are
            # real dollar values. Set explicitly at build; never inferred from values.
            "dollarized": False,
            # each leg's sums: 0.0 over no contract; None once a contract's value was not sent
            "call_oi": 0.0,
            "put_oi": 0.0,
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
            "call_volume": 0.0,
            "put_volume": 0.0,
        }
    return exposures_by_strike[strike]


def compute_exposures_by_strike(
    contracts: list[OptionContract],
    *,
    spot: float | None = None,
    now: datetime,
    product: str = "EQO",
) -> tuple[dict[float, dict], ExposureDiagnostics]:
    """
    Produces per-strike aggregated, over every listed contract with a strike and a side:
      - call/put OI
      - call/put delta exposure (scaled)
      - call/put gamma exposure (scaled)
      - net delta, net gamma: call minus put (_finish_bucket), the dealer's position under the
        one assumption every net field makes (dealers long calls, short puts); a put keeps
        Schwab's signed delta, so a short put adds positive delta

    Scaling:
      delta_exposure = delta * OI * multiplier
      gamma_exposure = gamma * OI * multiplier

    The dollar fields (DEX$, GEX$ per 1%) are computed when `spot` is provided.
    """
    exposures: dict[float, dict] = {}
    total = 0
    used = 0
    missing = 0

    # T for the BS-vanna faucet comes from the ONE valuation-T authority,
    # time_et.time_to_expiry_years (intraday ACT/365 to session close), NOT a local
    # whole-day `dte / 365.0`. Every contract in the aggregate is priced at the caller's one
    # valuation instant `now` (a replay of a stored chain prices at the snapshot's time), and T
    # is memoised per distinct expiry string.
    _tte_cache: dict[tuple, float | None] = {}

    def _tte_memo(c: OptionContract) -> float | None:
        key = (str(c.expiration), c.settlement)
        if key not in _tte_cache:
            _tte_cache[key] = time_to_expiry_years(
                key[0], now=now, settlement_type=key[1], product=product
            )
        return _tte_cache[key]

    for c in contracts:
        total += 1
        strike = c.strike
        if strike is None or c.side is None:
            continue
        oi = c.open_interest
        b = _strike_bucket(exposures, strike)
        side = c.side
        leg = side.lower()
        vol = c.volume
        if vol is None:  # not sent: the leg's volume is not known
            b["volume_unreported"] += 1
            b[f"{leg}_volume"] = None
        elif b[f"{leg}_volume"] is not None:
            b[f"{leg}_volume"] += vol

        if oi is None:  # not sent: the leg's open interest is not known
            missing += 1
            b["oi_unreported"] += 1
            b[f"{leg}_oi"] = None
        elif b[f"{leg}_oi"] is not None:
            b[f"{leg}_oi"] += oi

        mult = c.multiplier
        if oi is None or mult is None:  # the contract's exposure terms are not known
            missing += oi is not None
            b[f"{leg}_oi_mult_unreported"] += 1
            for g in ("gamma", "delta", "vanna"):
                b[f"{leg}_{g}_unreported"] += 1
            continue

        delta, gamma, iv = c.delta, c.gamma, c.volatility
        delta_ok = delta is not None
        gamma_ok = gamma is not None
        if not delta_ok or not gamma_ok:
            missing += 1
        if oi > 0:  # open interest 0 adds a known 0 whatever its Greeks
            b[f"{leg}_gamma_unreported"] += not gamma_ok
            b[f"{leg}_delta_unreported"] += not delta_ok
        vanna_priced = False

        used += 1

        b[f"{leg}_oi_mult"] += oi * mult
        if delta_ok:
            b[f"{leg}_delta"] += delta * oi * mult
        if gamma_ok:
            b[f"{leg}_gamma"] += gamma * oi * mult
        if spot is not None:
            spt = float(spot)
            if delta_ok:
                b[f"{leg}_dex_dollars"] += delta * oi * mult * spt
            if gamma_ok:
                b[f"{leg}_gex_1pct"] += (
                    gamma * oi * mult * spt * spt * 0.01
                )  # $-GEX per 1% spot move
            # exact BS vanna from the shared d1/d2 faucet (math_levels.bs_vanna), per
            # vol point; vanna is the same for a call and a put at a strike and expiry.
            _T = _tte_memo(c)
            if _T is not None and _T > 0:
                _sig = schwab_iv_to_sigma(iv)
                _vn = bs_vanna(spt, float(strike), _T, _sig) if _sig is not None else None
                if _vn is not None:
                    b[f"{leg}_vanna"] += _vn * 0.01 * oi * mult  # per 1 vol point
                    vanna_priced = True
            # a contract with open interest and no vanna leaves its leg's vanna unknown
            if oi > 0 and not vanna_priced:
                b[f"{leg}_vanna_unreported"] += 1

    for b in exposures.values():
        b["dollarized"] = spot is not None
        if spot is None:  # the dollar fields and vanna need spot: none without it
            for f in ("dex_dollars", "gex_1pct", "vanna"):
                for s in ("call", "put"):
                    b[f"{s}_{f}"] = None
        _finish_bucket(b)

    return exposures, _diagnostics(total, used, missing)


def _finish_bucket(b: dict) -> None:
    """A strike bucket's net fields from its call and put legs, +call/-put (dealer-signed, the
    same convention as net GEX and the terrain's dex_dollars -- one meaning of each on every
    screen): the one place they are computed, for a book and for a merge of books. A dollar
    field or vanna needs spot (`dollarized`): none without it."""
    b["net_gamma"] = b["call_gamma"] - b["put_gamma"]
    b["net_delta"] = b["call_delta"] - b["put_delta"]
    for f in ("dex_dollars", "gex_1pct", "vanna"):
        b[f"net_{f}"] = b[f"call_{f}"] - b[f"put_{f}"] if b["dollarized"] else None


def _diagnostics(total: int, used: int, missing: int) -> ExposureDiagnostics:
    note = "OK"
    if used == 0:
        note = "No usable contracts (OI filtered or chain empty)."
    elif missing == used:
        note = (
            "All greeks missing (Schwab sent -999, or no quote came back). You will still get "
            "OI center; gamma/delta pin/inf may be N/A until RTH."
        )
    return ExposureDiagnostics(
        contracts_total=total, contracts_used=used, greeks_missing=missing, note=note
    )


def exposure_books(
    contracts: list[OptionContract],
    *,
    spot: float | None,
    now: datetime,
    product: str = "EQO",
) -> dict[tuple[str, float | None], tuple[dict[float, dict], ExposureDiagnostics]]:
    """compute_exposures_by_strike once per (expiry, days to expiry) group. Every contract is
    priced once; any subset of expiries is then a merge_exposure_books of its groups (the full
    book, 0DTE, the front expiry, <=7 / >7 days)."""
    groups: dict[tuple[str, float | None], list] = {}
    for c in contracts:
        groups.setdefault((c.expiry, c.days_to_expiry), []).append(c)
    return {
        k: compute_exposures_by_strike(cs, spot=spot, now=now, product=product)
        for k, cs in groups.items()
    }


def merge_exposure_books(books) -> tuple[dict[float, dict], ExposureDiagnostics]:
    """One book from books over DISJOINT contracts: every leg field a sum of the books' legs (a
    sum not known in one book is not known in the merge), each flag an OR, and each net field
    computed from the merged legs by the book's own rule (_finish_bucket). The legs are the same
    sums one compute_exposures_by_strike call over all the contracts gives, up to float addition
    order."""
    merged: dict[float, dict] = {}
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
                    cur[k] = cur[k] or v
                elif not k.startswith("net_"):
                    cur[k] = None if v is None or cur[k] is None else cur[k] + v
    for b in merged.values():
        _finish_bucket(b)
    return merged, _diagnostics(total, used, missing)


#: The per-strike bucket fields that are flags (OR-ed when books merge); every other field is
#: a sum, None when no contract reported it (_strike_bucket, compute_exposures_by_strike).
_BUCKET_FLAGS = frozenset({"dollarized"})


def overlay_streamed_contract_fields(
    contracts: list[OptionContract], streamed_by_symbol: dict[str, dict], held: set[str]
) -> tuple[list[OptionContract], int]:
    """Each contract Schwab streams (`held`) with the values the stream pushed it
    (`streamed_by_symbol`, its newest streamed record): the pushed field is its one producer
    (AGENTS.md rule 3). Its volume is the stream's `total_volume`, None until the stream sends one.
    Its Greeks and volatility are the stream's newest once the stream holds all six (the set the
    chain sweep takes, option_contract.streamed_greek_set); until then they are the chain's, which
    the sweep asked /quotes for because the stream had not sent them. Every other contract keeps
    the chain's. Open interest is the chain's for every contract (the stream does not send it for
    every contract it streams).

    Pure: a streamed contract is a new record, every other the same one. Returns
    (new_contracts, streamed_count).
    """
    out: list[OptionContract] = []
    for c in contracts:
        if c.symbol not in held:
            out.append(c)
        elif c.symbol in streamed_by_symbol:
            sent = streamed_by_symbol[c.symbol]
            pushed = {"volume": sent.get("total_volume")}
            greeks = streamed_greek_set(sent)
            if greeks is not None:
                pushed.update(greeks)
            out.append(replace(c, **pushed))
        else:
            out.append(replace(c, volume=None))
    return out, len(out) - sum(new is old for new, old in zip(out, contracts))


def strike_total_oi(bucket: dict) -> float | None:
    """THE total open interest at one strike, or None when it is not known.

    Known = every contract at the strike reported openInterest (oi_unreported == 0). A leg
    with no positive-OI contract then contributes a real 0 (its contracts reported 0 OI, or
    none is listed)."""
    legs = strike_oi_legs(bucket)
    if legs is None:
        return None
    call_oi, put_oi = legs
    return call_oi + put_oi


def strike_oi_legs(bucket: dict) -> tuple[float, float] | None:
    """(call OI, put OI) at one strike when its OI is known (see strike_total_oi), else None.
    A leg with no contract listed is a known 0.0, the sum of none."""
    if bucket["oi_unreported"] != 0:
        return None
    return bucket["call_oi"], bucket["put_oi"]


def strike_volume_legs(bucket: dict) -> tuple[float, float] | None:
    """(call, put) session volume at one strike when every contract there reported totalVolume
    (0 is a real zero), else None. A leg with no listed contract is a known 0.0. THE one reader:
    GEX-by-Strike rows, heatmap cells and the put/call volume ratio."""
    if bucket["volume_unreported"] != 0:
        return None
    return bucket["call_volume"], bucket["put_volume"]


def strike_total_volume(bucket: dict) -> float | None:
    """THE total session volume at one strike, or None when a contract there did not report it."""
    legs = strike_volume_legs(bucket)
    if legs is None:
        return None
    call_volume, put_volume = legs
    return call_volume + put_volume


def book_total_oi(exposures: dict[float, dict]) -> float | None:
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


def put_call_oi_ratio(exposures: dict[float, dict]) -> float | None:
    """Total put OI / total call OI of the book -- the positions held; None if any strike's OI is
    unknown or call OI is 0."""
    legs = [strike_oi_legs(b) for b in exposures.values()]
    if not legs or None in legs:
        return None
    calls = sum(c for c, _ in legs)
    return sum(p for _, p in legs) / calls if calls > 0 else None


def put_call_volume_ratio(exposures: dict[float, dict]) -> float | None:
    """Total put volume / total call volume of the book -- today's trading, Cboe's convention
    (https://cdn.cboe.com/resources/us/options/market_statistics/daily/cone/archive/html/2002-05-17.html).
    None when any contract in the book did not report its volume, or no call traded. A strike with
    no call (or put) contract listed has no volume on that side, not a zero."""
    legs = [strike_volume_legs(b) for b in (exposures or {}).values()]
    if not legs or None in legs:
        return None
    calls = sum(c for c, _ in legs)
    return sum(p for _, p in legs) / calls if calls > 0 else None


def exposures_have_dollar_gex(exposures: dict[float, dict]) -> bool:
    """True when the book was built WITH spot (its dollar fields are real). Read from the
    explicit `dollarized` flag, never inferred from the dollar GEX values, so a spot-built book
    whose gammas are all invalid still reads as dollarized."""
    for b in exposures.values():
        if isinstance(b, dict) and "dollarized" in b:
            return bool(b["dollarized"])
    return False


def key_level_strikes_with_oi(exposures: dict[float, dict]) -> list[float]:
    """Strikes whose OI is KNOWN and positive (strike_total_oi -- the one reader)."""
    out: list[float] = []
    for s in sorted(float(k) for k in exposures):
        tot = strike_total_oi(exposures.get(s, {}))
        if tot is not None and tot > 0:
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
    """Aggregate dealer vanna — how much dealer DELTA shifts per IV point.

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
    net_shares_per_volpt = sum(nets)  # the book is already per vol point
    return {
        "net_vanna_dollars_per_volpt": net_shares_per_volpt * float(spot),
        "net_vanna_shares_per_volpt": net_shares_per_volpt,
    }


def compute_zero_dte_gamma_share(exposures_all: dict, exposures_0dte: dict) -> float | None:
    """% of the dealer gamma book from SAME-DAY expiry — the level-persistence read.

    share = sum(|net_gex_1pct|) over the 0DTE book / sum(|net_gex_1pct|) over the full book,
    BOTH books from the ONE producer (compute_exposures_by_strike; the 0DTE book merges
    exposure_books' same-day groups). High share
    means today's walls/flip decay into the close (0DTE gamma dies at 4pm); low share means
    the levels are carried by dated gamma and persist. FAIL-CLOSED: None when the full book
    is empty or has no measurable gamma — never a fabricated 0%.
    """
    if not exposures_all:
        return None
    # a bucket MISSING its net-GEX field must not contribute a fabricated zero
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
    return 100.0 * zero / total


def _pick_strike_max_metric(
    exposures: dict[float, dict],
    metric_fn,
) -> tuple[float | None, float | None]:
    best_s: float | None = None
    best_v: float | None = None
    for s in sorted(exposures):
        v = metric_fn(exposures[s])
        if v is None or v <= 0:
            continue
        if best_v is None or v > best_v:
            best_s = float(s)
            best_v = float(v)
    return best_s, best_v


def pick_pin_and_strength(exposures: dict[float, dict]) -> tuple[float | None, float | None]:
    """Max TOTAL gamma — a GROSS GAMMA CONCENTRATION, plus its
    decisiveness. NOT a demonstrated magnet.

    WHAT IT MEASURES. The strike carrying the largest absolute call GEX dollars plus
    absolute put GEX dollars — i.e. where the most dealer re-hedging activity sits. This is
    the quantity SpotGamma publishes as Absolute Gamma.

    WHAT IT DOES NOT ESTABLISH: that hedging MAGNITUDE pins price regardless of net sign, so
    calls-plus-puts is the magnet measure. That does not follow. Magnitude sets the SIZE of
    the hedging flow at a strike; the SIGN of the dealer position sets whether that flow is
    stabilising or destabilising — a dealer long gamma sells rallies and buys dips, a dealer
    short gamma does the opposite — and this metric discards the sign. Two strikes with equal
    absolute gamma can behave oppositely. The sign is also not observable: public open
    interest does not reveal contract ownership
    (https://spotgamma.com/what-is-gex-gamma-exposure/), so dealer direction is MODELLED.
    Expiration-date clustering in the literature turns on NET positioning — Ni, Pearson and
    Poteshman, Journal of Financial Economics, doi:10.1016/j.jfineco.2004.08.005.

    Treat the result as a pin CANDIDATE.

    The NET book (calls minus puts) is a different question — where the signed book leans —
    and lives under its own name as net_gex_peak (pick_net_gex_peak_strike below).

    strength_pct = the leader's margin over the runner-up on the same metric. A 1% lead is a
    coin flip and the label should say so; a 40% lead is a decisive CONCENTRATION, which is
    still not a claim about where price goes.
    Fail-closed: no dollarized GEX -> (None, None), never a raw-gamma fallback.
    """
    if not exposures_have_dollar_gex(exposures):
        return None, None
    s, v = _pick_strike_max_metric(exposures, total_gex_dollars_at_strike)
    if s is None or v is None or v <= 0:
        return None, None
    second = 0.0
    for k, bucket in exposures.items():
        if float(k) == s:
            continue
        t = total_gex_dollars_at_strike(bucket)
        if t is not None and t > second:
            second = t
    return s, (v - second) / v * 100.0


def pick_net_gex_peak_strike(exposures: dict[float, dict]) -> float | None:
    """
    Net-GEX peak: strike with largest |net GEX$| per 1% (calls minus puts) -- where the SIGNED
    book concentrates (the standard pin is total gamma, pick_pin_and_strength). None when the
    book has no dollar GEX (no spot).
    """
    if not exposures_have_dollar_gex(exposures):
        return None
    s, _ = _pick_strike_max_metric(exposures, lambda b: bucket_metric_abs(b, "net_gex_1pct"))
    return s


def pick_key_delta_strike(exposures: dict[float, dict]) -> float | None:
    """Key Delta Strike: largest total delta notional (|call DEX$| + |put DEX$|).

    Institutional only — no raw-delta fallback: delta notional needs spot, and a
    unit mix here would rank strikes on incomparable numbers.
    """
    if not exposures_have_dollar_gex(exposures):
        return None

    def _total_dex(b: dict) -> float | None:
        c = bucket_metric_abs(b, "call_dex_dollars")
        p = bucket_metric_abs(b, "put_dex_dollars")
        return None if c is None or p is None else c + p

    s, _ = _pick_strike_max_metric(exposures, _total_dex)
    return s


def pick_volatility_point_strikes(
    exposures: dict[float, dict],
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
    for s in sorted(exposures):
        v = net_gex_dollars_at_strike(exposures[s])
        if v is None:
            continue
        if v < 0 and (hvp_v is None or v < hvp_v):
            hvp_s, hvp_v = float(s), float(v)
        if v > 0 and (lvp_v is None or v > lvp_v):
            lvp_s, lvp_v = float(s), float(v)
    return hvp_s, lvp_s


def pick_gamma_wall_strikes(
    exposures: dict[float, dict],
) -> tuple[tuple[float | None, float | None], tuple[float | None, float | None]]:
    """Call/put gamma walls: max |side GEX$|; none without a dollarized book (no spot)."""
    if not exposures_have_dollar_gex(exposures):
        return (None, None), (None, None)
    return (
        _pick_strike_max_metric(exposures, lambda b: bucket_metric_abs(b, "call_gex_1pct")),
        _pick_strike_max_metric(exposures, lambda b: bucket_metric_abs(b, "put_gex_1pct")),
    )


def pick_delta_wall_strikes(
    exposures: dict[float, dict],
) -> tuple[tuple[float | None, float | None], tuple[float | None, float | None]]:
    """Call/put delta walls: max |side DEX$|; none without a dollarized book (no spot)."""
    if not exposures_have_dollar_gex(exposures):
        return (None, None), (None, None)
    return (
        _pick_strike_max_metric(exposures, lambda b: bucket_metric_abs(b, "call_dex_dollars")),
        _pick_strike_max_metric(exposures, lambda b: bucket_metric_abs(b, "put_dex_dollars")),
    )
