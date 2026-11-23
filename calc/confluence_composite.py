"""Per-strike composite for one expiry.

The exposure book, the charm map, and the volatility blend are already computed
for that expiry. This module ranks them. It does not recompute a greek or the blend.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, TypedDict

from calc.math_exposure_core import (
    Bucket,
    bucket_metric,
    strike_total_oi,
    strike_total_volume,
    strike_volume_legs,
    total_gex_dollars_at_strike,
)
from calc.math_levels import CharmBucket
from numeric_contract import (
    compact_text,
    count_text,
    dollars_text,
    iv_text,
    price_text,
    schwab_number,
)
from option_contract import OptionContract

ABSENT = ("DGEXM", "FLOWM")
THIN_BOOK = 10


class FactorPart(TypedDict):
    """One scored factor's share of a strike's score (score_magnitudes)."""

    factor: str
    label: str
    raw: float | None
    normalized: float
    weight: float
    contribution: float


class Scored(TypedDict):
    """One strike's score with what it is missing (score_magnitudes)."""

    score: float | None
    missing: list[str]
    contributions: list[FactorPart]
    factors: list[FactorPart]


@dataclass(frozen=True)
class RankedStrike:
    """One strike of an expiry's ranking.

    Its factor magnitudes (magnitudes) and its score with what it is missing (score_magnitudes).
    """

    factors: dict[str, float | None]
    result: Scored


WRITTEN = {
    "0DTE": {
        "CHARMM": 0.22,
        "DGEXM": 0.18,
        "GEXM": 0.15,
        "VOL": 0.10,
        "OI": 0.10,
        "FLOWM": 0.10,
        "VANNAM": 0.05,
        "DEXM": 0.05,
        "IV": 0.05,
    },
    "WEEKLY": {
        "GEXM": 0.25,
        "OI": 0.15,
        "DGEXM": 0.15,
        "VOL": 0.10,
        "FLOWM": 0.10,
        "CHARMM": 0.08,
        "VANNAM": 0.07,
        "DEXM": 0.05,
        "IV": 0.05,
    },
    "MONTHLY": {
        "GEXM": 0.30,
        "OI": 0.20,
        "VANNAM": 0.10,
        "DEXM": 0.10,
        "DGEXM": 0.08,
        "VOL": 0.07,
        "FLOWM": 0.05,
        "CHARMM": 0.05,
        "IV": 0.05,
    },
}

_LABEL = {
    "GEXM": "net gamma",
    "OI": "open interest",
    "VOL": "volume",
    "DEXM": "delta",
    "VANNAM": "vanna",
    "IV": "volatility",
    "CHARMM": "charm",
    "DGEXM": "change in gamma",
    "FLOWM": "flow",
}


def preset_name(dte: float) -> str:
    if dte <= 0:
        return "0DTE"
    if dte <= 7:
        return "WEEKLY"
    return "MONTHLY"


def in_score_weights(name: str) -> dict[str, float]:
    written = WRITTEN[name]
    return {k: (0.0 if k in ABSENT else v) for k, v in written.items()}


def ceiling(weights: dict[str, float]) -> float:
    return 100.0 * sum(weights.values())


def percentile(values: list[float], p: float) -> float:
    """Hyndman-Fan type 7. `values` is non-empty and 0 <= p <= 1, so 1 <= h <= n."""
    xs = sorted(values)
    n = len(xs)
    if n == 1:
        return xs[0]
    h = 1.0 + (n - 1) * p
    lo = int(math.floor(h))
    hi = int(math.ceil(h))
    if lo == hi:
        return xs[lo - 1]
    frac = h - lo
    return xs[lo - 1] + frac * (xs[hi - 1] - xs[lo - 1])


def _normalize(present: list[tuple[float, float]]) -> tuple[dict[float, float], float | None]:
    """Map strike -> f'. The second value is p95 − p5, or None when the factor does not vary."""
    vals = [v for _s, v in present]
    if len(vals) == 0:
        return {}, None
    lo = percentile(vals, 0.05)
    hi = percentile(vals, 0.95)
    if hi == lo:
        return {s: 0.0 for s, _v in present}, None
    span = hi - lo
    out: dict[float, float] = {}
    for s, v in present:
        x = (v - lo) / span
        if x < 0.0:
            x = 0.0
        elif x > 1.0:
            x = 1.0
        out[s] = x
    return out, span


def score_magnitudes(
    by_strike: dict[float, dict[str, float | None]], weights: dict[str, float]
) -> tuple[dict[float, Scored], list[str], dict[str, float | None]]:
    """One score per strike. A missing factor whose weight is above zero blanks that strike.

    The third value is p95 − p5 for each scored factor, None when that factor does not vary.
    """
    required = [k for k, w in weights.items() if w > 0]
    universe = [s for s, f in by_strike.items() if _in_universe(f)]
    norm: dict[str, dict[float, float]] = {}
    spans: dict[str, float | None] = {}
    flat: list[str] = []
    for name in required:
        present = [(s, v) for s in universe if (v := by_strike[s].get(name)) is not None]
        mapped, span = _normalize(present)
        norm[name] = mapped
        spans[name] = span
        if span is None and present and len(present) == len(universe):
            flat.append(name)
    scored: dict[float, Scored] = {}
    for strike, factors in by_strike.items():
        if strike not in universe:
            unreported = factors.get("OI") is None or factors.get("VOL") is None
            why = (
                "open interest or volume was not reported"
                if unreported
                else "no open interest and no volume"
            )
            scored[strike] = {"score": None, "missing": [why], "contributions": [], "factors": []}
            continue
        missing = [_LABEL[k] for k in required if factors.get(k) is None]
        if missing:
            scored[strike] = {"score": None, "missing": missing, "contributions": [], "factors": []}
            continue
        parts: list[FactorPart] = []
        total = 0.0
        for name in required:
            share = weights[name] * norm[name][strike]
            total += share
            parts.append(
                {
                    "factor": name,
                    "label": _LABEL[name],
                    "raw": factors[name],
                    "normalized": norm[name][strike],
                    "weight": weights[name],
                    "contribution": share,
                }
            )
        parts.sort(key=lambda p: p["contribution"], reverse=True)
        scored[strike] = {
            "score": 100.0 * total,
            "missing": [],
            "contributions": parts[:3],
            "factors": parts,
        }
    return scored, flat, spans


def _in_universe(factors: dict[str, float | None]) -> bool:
    oi = factors.get("OI")
    vol = factors.get("VOL")
    return (oi is not None and oi > 0) or (vol is not None and vol > 0)


def magnitudes(
    bucket: Bucket, charm: CharmBucket | None, iv: float | None, spot: float
) -> dict[str, float | None]:
    """Return the scored magnitudes, plus the signed numbers the columns show.

    Each leg's gamma is Schwab's as sent, whatever its sign (AGENTS rule 2).
    """
    call_gex = bucket_metric(bucket, "call_gex_1pct")
    put_gex = bucket_metric(bucket, "put_gex_1pct")
    net_gex = bucket_metric(bucket, "net_gex_1pct")
    dex = bucket_metric(bucket, "net_dex_dollars")
    vanna = bucket_metric(bucket, "net_vanna")
    oi = strike_total_oi(bucket)
    vol = strike_total_volume(bucket)
    charm_net = None if charm is None else schwab_number(charm["net_charm"])
    out = {
        "GEXM": None if net_gex is None else abs(net_gex),
        "OI": oi,
        "VOL": vol,
        "DEXM": None if dex is None else abs(dex),
        "VANNAM": None if vanna is None else abs(vanna * spot),
        "IV": iv,
        "CHARMM": None if charm_net is None else abs(charm_net),
    }
    out["_net_gex"] = net_gex
    out["_gross"] = total_gex_dollars_at_strike(bucket)  # the total gamma level's one producer
    out["_pc_gex"] = (
        None if call_gex is None or put_gex is None or call_gex == 0 else put_gex / call_gex
    )
    out["_dex"] = dex
    out["_vanna"] = None if vanna is None else vanna * spot
    out["_pc_vol"] = None
    vol_legs = strike_volume_legs(bucket)
    if vol_legs is not None and vol_legs[0] > 0:
        out["_pc_vol"] = vol_legs[1] / vol_legs[0]
    out["_vol_oi"] = None if oi is None or oi == 0 or vol is None else vol / oi
    out["_charm"] = charm_net
    return out


def iv_by_strike(contracts: list[OptionContract]) -> dict[float, float | None]:
    """(open interest + volume)-weighted Schwab volatility, in vol points."""
    grouped: dict[float, list[OptionContract]] = {}
    for c in contracts:
        if c.strike is not None:
            grouped.setdefault(float(c.strike), []).append(c)
    out: dict[float, float | None] = {}
    for strike, rows in grouped.items():
        weighted = 0.0
        weight = 0.0
        plain: list[float] = []
        for c in rows:
            iv = c.volatility
            if iv is None:
                continue
            plain.append(iv)
            oi, vol = c.open_interest, c.volume
            if oi is None or vol is None:
                continue
            w = float(oi) + float(vol)
            weighted += w * iv
            weight += w
        if plain and weight == 0:
            out[strike] = sum(plain) / len(plain)
        elif weight > 0:
            out[strike] = weighted / weight
        else:
            out[strike] = None
    return out


@dataclass(frozen=True)
class Matrix:
    """The ranking of one expiry's book (build_matrix).

    Its preset and score scale, its notes, every strike's ranking, each shaded column's peak, and
    the listed strikes, ascending.
    """

    preset: str
    scale_text: str
    ceiling: float
    notes: list[str]
    ranked: dict[float, RankedStrike]
    peaks: dict[str, float | None]
    strikes: list[float]


def window_rows(matrix: Matrix, shown: list[float]) -> list[dict[str, Any]]:
    """Return the rows of the ranked strikes `shown`, highest strike first.

    Each cell shades against its whole expiry's peak (the matrix's `peaks`).
    """
    return [_row(strike, matrix.ranked[strike]) for strike in sorted(shown, reverse=True)]


def under_strike(price: float, strikes: list[float]) -> float | None:
    """Return the lowest listed strike at or above `price`, where a marker sits."""
    at_or_above = [s for s in strikes if s >= price]
    if not at_or_above:
        return None
    return min(at_or_above)


def _text(n: float | None, digits: int) -> str | None:
    if n is None:
        return None
    return f"{n:.{digits}f}"


class Distance(TypedDict):
    """A price's distance from the live price: in dollars, and in the expiry's implied moves."""

    distance_text: str | None
    sigma: float | None
    sigma_text: str | None


def distance(price: float, spot: float | None, sigma_root_t: float | None) -> Distance:
    """Return `price`'s distance from the live price `spot`, in dollars and in implied moves.

    In dollars: the price less `spot`, signed. In implied moves (σ): ln(price / spot) over the
    expiry's at-the-money volatility times the square root of its time left (`sigma_root_t`),
    the distance options desks quote because it compares across tickers and expiries (the
    normalised strike, z = ln(K / F) / (σ √T); `Trading/matrix_research_key_levels_2026_11_23.md`).
    It is measured from the live price, the base of the dollar distance beside it, not the
    forward: the two differ by the interest to the expiry, under 0.1 σ for SPY within two months.
    Unknown without a price, or with no volatility or no time left.
    """
    sigma = None if spot is None or not sigma_root_t else math.log(price / spot) / sigma_root_t
    return {
        "distance_text": None if spot is None else _signed(price - spot, 2),
        "sigma": sigma,
        "sigma_text": None if sigma is None else f"{_signed(sigma, 1)}σ",
    }


def at_price(
    rows: list[dict[str, Any]],
    strikes: list[float],
    spot: float | None,
    sigma_root_t: float | None,
) -> dict[str, Any]:
    """Return the shown rows, each with its distance from the live price and its spot line.

    The spot line marks the strike the price sits under; the price and its text come with them.
    The matrix is ranked at the book's price, the price on screen is the live one; each row's
    distance is `distance`'s, in dollars and in the expiry's implied moves (`sigma_root_t`).
    Pure: the rows given are not changed.
    """
    under = None if spot is None else under_strike(spot, strikes)
    return {
        "rows": [
            {
                **row,
                **distance(row["strike"], spot, sigma_root_t),
                "spot_line": row["strike"] == under,
            }
            for row in rows
        ],
        "spot": spot,
        "spot_text": price_text(spot),
    }


def _signed(n: float | None, digits: int) -> str | None:
    """Format a number signed: a positive one keeps its plus. Zero and a rounded zero do not."""
    if n is None:
        return None
    shown = f"{float(n):.{digits}f}"
    if shown.startswith("-"):
        if float(shown) == 0:
            return shown[1:]
        return shown
    if float(shown) == 0:
        return shown
    return "+" + shown


def _peak(values: Iterable[float | None]) -> float | None:
    """Largest absolute value on this expiry: the column's scale, not a score."""
    peak = None
    for value in values:
        if not isinstance(value, (int, float)):
            continue
        size = abs(float(value))
        if peak is None or size > peak:
            peak = size
    return peak


#: each shaded column: the row's key for its number and the factor it carries
SHADED = {
    "net_gex": "_net_gex",
    "oi": "OI",
    "gross": "_gross",
    "volume": "VOL",
    "vol_oi": "_vol_oi",
    "dex": "_dex",
    "vanna": "_vanna",
    "iv": "IV",
    "charm": "_charm",
}
#: the put/call columns shade by 1 - put/call: positive call-heavy, negative put-heavy
LEANS = {"pc_gex_lean": "_pc_gex", "pc_vol_lean": "_pc_vol"}


def _shades(factors: dict[str, float | None]) -> dict[str, float | None]:
    """Return the numbers the page shades each column's cell by, against the column's peak."""
    out = {key: factors[name] for key, name in SHADED.items()}
    for key, name in LEANS.items():
        out[key] = None if (ratio := factors[name]) is None else 1 - ratio
    return out


def _absent(value: float | None, words: str) -> str | None:
    if isinstance(value, (int, float)):
        return None
    return words


FLOW_REASON = "no signed flow is produced"
DGEX_REASON = "no change in gamma is produced"


def _raw_text(name: str, raw: float | None) -> str | None:
    """Return a factor's magnitude as the screen shows it.

    Gamma, delta and vanna in dollars; volatility a percent; charm (delta-shares) compact; open
    interest and volume whole.
    """
    if name in ("GEXM", "DEXM", "VANNAM"):
        return dollars_text(raw)
    if name == "IV":
        return iv_text(raw)
    if name == "CHARMM":
        return compact_text(raw)
    return count_text(raw)


def _factor_row(part: FactorPart) -> dict[str, str | None]:
    return {
        "label": part["label"],
        "text": f"{100.0 * part['contribution']:.1f}",
        "raw_text": _raw_text(part["factor"], part["raw"]),
        "normalized_text": _text(part["normalized"], 2),
        "weight_text": _text(part["weight"], 2),
    }


def build_matrix(
    exposures: dict[float, Bucket],
    charm_by_strike: dict[float, CharmBucket],
    ivs: dict[float, float | None],
    spot: float,
    dte: float,
) -> Matrix:
    """Build the ranking of one expiry's book.

    Every strike's factors and score and the expiry's colour scales. The rows the page shows are
    drawn from it (window_rows).
    """
    name = preset_name(dte)
    weights = in_score_weights(name)
    strikes = sorted(float(s) for s in exposures)
    mags = {s: magnitudes(exposures[s], charm_by_strike.get(s), ivs.get(s), spot) for s in strikes}
    scored, flat, _spans = score_magnitudes(mags, weights)
    cap = ceiling(weights)
    shades = [_shades(f) for f in mags.values()]
    peaks = {key: _peak(s[key] for s in shades) for key in (*SHADED, *LEANS)}
    universe_n = sum(1 for f in mags.values() if _in_universe(f))
    flat_labels = [_LABEL[k] for k in flat]
    notes: list[str] = []
    if universe_n < THIN_BOOK:
        notes.append("Thin book: fewer than " + str(THIN_BOOK) + " strikes.")
    if flat_labels:
        notes.append(", ".join(flat_labels) + " does not vary, so it adds nothing.")
    return Matrix(
        preset=name,
        scale_text="0–" + f"{cap:g}",
        ceiling=cap,
        notes=notes,
        ranked={strike: RankedStrike(mags[strike], scored[strike]) for strike in mags},
        peaks=peaks,
        strikes=strikes,
    )


def _row(strike: float, ranked: RankedStrike) -> dict[str, Any]:
    """One strike's row of the matrix.

    Each column's text and the number its cell shades by (_shades), against the expiry's peaks.
    """
    factors, result = ranked.factors, ranked.result
    score = result["score"]
    pc_gex = factors["_pc_gex"]
    pc_vol = factors["_pc_vol"]
    return {
        "strike": strike,
        "strike_text": price_text(strike),
        **_shades(factors),
        "net_gex_text": dollars_text(factors["_net_gex"]),
        "net_reason": _absent(factors["_net_gex"], "net gamma is missing"),
        "oi_text": count_text(factors["OI"]),
        "oi_reason": _absent(factors["OI"], "open interest is missing"),
        "pc_gex_text": _text(pc_gex, 2),
        "pc_gex_reason": _absent(pc_gex, "put/call gamma is missing"),
        "gross_text": dollars_text(factors["_gross"]),
        "gross_reason": _absent(factors["_gross"], "gross gamma is missing"),
        "dgex_text": None,
        "dgex_reason": DGEX_REASON,
        "volume_text": count_text(factors["VOL"]),
        "volume_reason": _absent(factors["VOL"], "volume is missing"),
        "pc_vol_text": _text(pc_vol, 2),
        "pc_vol_reason": _absent(pc_vol, "put/call volume is missing"),
        "vol_oi_text": _text(factors["_vol_oi"], 2),
        "vol_oi_reason": _absent(factors["_vol_oi"], "volume/open interest is missing"),
        "flow_text": None,
        "flow_reason": FLOW_REASON,
        "dex_text": dollars_text(factors["_dex"]),
        "dex_reason": _absent(factors["_dex"], "delta exposure is missing"),
        "vanna_text": dollars_text(factors["_vanna"]),
        "vanna_reason": _absent(factors["_vanna"], "vanna is missing"),
        "iv_text": iv_text(factors["IV"]),
        "iv_reason": _absent(factors["IV"], "implied volatility is missing"),
        "charm_text": compact_text(factors["_charm"]),
        "charm_reason": _absent(factors["_charm"], "charm is missing"),
        "score": score,
        "score_text": None if score is None else str(int(round(score))),
        "missing": result["missing"],
        "contributions": [_factor_row(p) for p in result["contributions"]],
        "factors": [_factor_row(p) for p in result["factors"]],
    }
