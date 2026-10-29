"""Per-strike composite for one expiry.

The exposure book, the charm map, and the volatility blend are already computed
for that expiry. This module ranks them. It does not recompute a greek or the blend.
"""

from __future__ import annotations

import math
from typing import Any

from math_exposure_core import (
    bucket_metric, strike_total_oi, strike_total_volume, strike_volume_legs,
)
from numeric_contract import price_text, schwab_count, schwab_number

ABSENT = ("DGEXM", "FLOWM")
WINDOW = 5
THIN_BOOK = 10

WRITTEN = {
    "0DTE": {
        "CHARMM": 0.22, "DGEXM": 0.18, "GEXM": 0.15, "VOL": 0.10, "OI": 0.10,
        "FLOWM": 0.10, "VANNAM": 0.05, "DEXM": 0.05, "IV": 0.05,
    },
    "WEEKLY": {
        "GEXM": 0.25, "OI": 0.15, "DGEXM": 0.15, "VOL": 0.10, "FLOWM": 0.10,
        "CHARMM": 0.08, "VANNAM": 0.07, "DEXM": 0.05, "IV": 0.05,
    },
    "MONTHLY": {
        "GEXM": 0.30, "OI": 0.20, "VANNAM": 0.10, "DEXM": 0.10, "DGEXM": 0.08,
        "VOL": 0.07, "FLOWM": 0.05, "CHARMM": 0.05, "IV": 0.05,
    },
}

_LABEL = {
    "GEXM": "net gamma", "OI": "open interest", "VOL": "volume", "DEXM": "delta",
    "VANNAM": "vanna", "IV": "volatility", "CHARMM": "charm",
    "DGEXM": "change in gamma", "FLOWM": "flow",
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
    """Hyndman-Fan type 7. `values` is non-empty."""
    xs = sorted(values)
    n = len(xs)
    if n == 1:
        return xs[0]
    h = 1.0 + (n - 1) * p
    lo = int(math.floor(h))
    hi = int(math.ceil(h))
    if lo < 1:
        lo = 1
    if hi > n:
        hi = n
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
    out = {}
    for s, v in present:
        x = (v - lo) / span
        if x < 0.0:
            x = 0.0
        elif x > 1.0:
            x = 1.0
        out[s] = x
    return out, span


def score_magnitudes(by_strike: dict[float, dict[str, float | None]],
                     weights: dict[str, float]
                     ) -> tuple[dict[float, dict[str, Any]], list[str], dict[str, float | None]]:
    """One score per strike. A missing factor whose weight is above zero blanks that strike.

    The third value is p95 − p5 for each scored factor, None when that factor does not vary.
    """
    required = [k for k, w in weights.items() if w > 0]
    universe = [s for s, f in by_strike.items() if _in_universe(f)]
    norm: dict[str, dict[float, float]] = {}
    spans: dict[str, float | None] = {}
    flat: list[str] = []
    for name in required:
        present = [(s, by_strike[s][name]) for s in universe
                   if by_strike[s].get(name) is not None]
        mapped, span = _normalize(present)
        norm[name] = mapped
        spans[name] = span
        if span is None and present and len(present) == len(universe):
            flat.append(name)
    scored: dict[float, dict[str, Any]] = {}
    for strike, factors in by_strike.items():
        if strike not in universe:
            unreported = factors.get("OI") is None or factors.get("VOL") is None
            why = ("open interest or volume was not reported" if unreported
                   else "no open interest and no volume")
            scored[strike] = {"score": None, "missing": [why],
                              "contributions": [], "factors": []}
            continue
        missing = [_LABEL[k] for k in required if factors.get(k) is None]
        if missing:
            scored[strike] = {"score": None, "missing": missing, "contributions": [], "factors": []}
            continue
        parts = []
        total = 0.0
        for name in required:
            share = weights[name] * norm[name][strike]
            total += share
            parts.append({
                "factor": name, "label": _LABEL[name], "raw": factors[name],
                "normalized": norm[name][strike], "weight": weights[name], "contribution": share,
            })
        parts.sort(key=lambda p: p["contribution"], reverse=True)
        scored[strike] = {"score": 100.0 * total, "missing": [], "contributions": parts[:3],
                          "factors": parts}
    return scored, flat, spans


def _in_universe(factors: dict[str, float | None]) -> bool:
    oi = factors.get("OI")
    vol = factors.get("VOL")
    return (oi is not None and oi > 0) or (vol is not None and vol > 0)


def _legs_ok(bucket: dict, call_key: str, put_key: str) -> tuple[float, float] | None:
    call = bucket_metric(bucket, call_key)
    put = bucket_metric(bucket, put_key)
    if call is None or put is None or call < 0 or put < 0:
        return None
    return call, put


def magnitudes(bucket: dict, charm: dict | None, iv: float | None, spot: float
               ) -> dict[str, float | None]:
    """The scored magnitudes, plus the signed numbers the columns show."""
    gex = _legs_ok(bucket, "call_gex_1pct", "put_gex_1pct")
    net_gex = bucket_metric(bucket, "net_gex_1pct")
    dex = bucket_metric(bucket, "net_dex_dollars")
    vanna = bucket_metric(bucket, "net_vanna")
    oi = strike_total_oi(bucket)
    vol = strike_total_volume(bucket)
    charm_net = None
    if charm is None and oi == 0:
        charm_net = 0.0
    elif charm is not None:
        charm_net = schwab_number(charm.get("net_charm"))
    out = {
        "GEXM": None if gex is None or net_gex is None else abs(net_gex),
        "OI": oi,
        "VOL": vol,
        "DEXM": None if dex is None else abs(dex),
        "VANNAM": None if vanna is None else abs(vanna * spot),
        "IV": iv,
        "CHARMM": None if charm_net is None else abs(charm_net),
        "DGEXM": None,
        "FLOWM": None,
    }
    out["_net_gex"] = None if gex is None else net_gex
    out["_gross"] = None if gex is None else gex[0] + gex[1]
    out["_pc_gex"] = None if gex is None or gex[0] == 0 else gex[1] / gex[0]
    out["_dex"] = dex
    out["_vanna"] = None if vanna is None else vanna * spot
    out["_pc_vol"] = None
    vol_legs = strike_volume_legs(bucket)
    if vol_legs is not None and vol_legs[0] > 0:
        out["_pc_vol"] = vol_legs[1] / vol_legs[0]
    out["_vol_oi"] = None if oi is None or oi == 0 or vol is None else vol / oi
    out["_charm"] = charm_net
    return out


def iv_by_strike(contracts: list) -> dict[float, float | None]:
    """(open interest + volume)-weighted Schwab volatility, in vol points."""
    grouped: dict[float, list] = {}
    for ct in contracts:
        if not isinstance(ct, dict):
            continue
        strike = schwab_number(ct.get("strikePrice"))
        if strike is None:
            continue
        grouped.setdefault(float(strike), []).append(ct)
    out: dict[float, float | None] = {}
    for strike, rows in grouped.items():
        weighted = 0.0
        weight = 0.0
        plain: list[float] = []
        for ct in rows:
            iv = schwab_number(ct.get("volatility"))
            if iv is None:
                continue
            plain.append(iv)
            oi = schwab_count(ct.get("openInterest"))
            vol = schwab_count(ct.get("totalVolume"))
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


def window_strikes(strikes: list[float], spot: float) -> list[float]:
    """Five listed strikes below the price, five above, and the strike on the price."""
    below = sorted((s for s in strikes if s < spot), reverse=True)[:WINDOW]
    above = sorted(s for s in strikes if s > spot)[:WINDOW]
    at = [s for s in strikes if s == spot]
    return sorted(below + at + above)


def window_rows(matrix: dict, price: float) -> list[dict]:
    """The rows of the strikes window_strikes chooses at `price`, highest strike first, each
    coloured on its whole expiry's scale."""
    ranked = matrix["ranked"]
    shown = window_strikes(list(ranked), price)
    return [_row(strike, ranked[strike], matrix["peaks"]) for strike in sorted(shown, reverse=True)]


def under_strike(price: float, strikes: list[float]) -> float | None:
    """The lowest listed strike at or above `price`, where a marker sits."""
    at_or_above = [s for s in strikes if s >= price]
    if not at_or_above:
        return None
    return min(at_or_above)


def _text(n: float | None, digits: int) -> str | None:
    if n is None:
        return None
    return f"{n:.{digits}f}"


def at_price(rows: list[dict], strikes: list[float], spot: float | None) -> dict:
    """Each shown row's distance from the live price and the strike the price sits under, and the
    price's text: the matrix is ranked at the book's price, the price on screen is the live one."""
    under = None if spot is None else under_strike(spot, strikes)
    for row in rows:
        row["distance_text"] = None if spot is None else _signed(row["strike"] - spot, 2)
        row["spot_line"] = row["strike"] == under
    return {"spot": spot, "spot_text": price_text(spot)}


def _signed(n: float | None, digits: int) -> str | None:
    """A positive number keeps its plus. Zero and a rounded zero do not."""
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


def _millions(n: float | None) -> str | None:
    if n is None:
        return None
    return f"{n / 1e6:.2f}"


def _signed_millions(n: float | None) -> str | None:
    if n is None:
        return None
    return _signed(float(n) / 1e6, 2)


def _signed_thousands(n: float | None) -> str | None:
    if n is None:
        return None
    return _signed(float(n) / 1000, 2)


def _thousands(n: float | None) -> str | None:
    if n is None:
        return None
    return f"{n / 1000:.2f}"


def _peak(values) -> float | None:
    """Largest absolute value on this expiry. The color ramp's own scale, not a score."""
    peak = None
    for value in values:
        if not isinstance(value, (int, float)):
            continue
        size = abs(float(value))
        if peak is None or size > peak:
            peak = size
    return peak


def _ramp(value, peak, signed: bool) -> str | None:
    """Neutral toward red or green. The page paints this string and does not scale it."""
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number == 0 or not isinstance(peak, (int, float)) or peak == 0:
        return "background:#111822;font-weight:550"
    t = abs(number) / float(peak)
    if t > 1:
        t = 1.0
    if signed and number < 0:
        end = (224, 35, 47)
    else:
        end = (9, 166, 67)
    neutral = (17, 24, 34)
    channels = [str(int(round(neutral[i] * (1 - t) + end[i] * t))) for i in range(3)]
    weight = "750" if t > 0.65 else "550"
    return "background:rgb(" + ",".join(channels) + ");font-weight:" + weight


def _absent(value, words: str) -> str | None:
    if isinstance(value, (int, float)):
        return None
    return words


FLOW_REASON = "no signed flow is produced"
DGEX_REASON = "no change in gamma is produced"


def _raw_text(name: str, raw: float | None) -> str | None:
    if name in ("GEXM", "DEXM", "VANNAM"):
        return _millions(raw)
    if name == "CHARMM":
        return _thousands(raw)
    if name == "IV":
        return _text(raw, 1)
    if raw is None:
        return None
    return f"{raw:.0f}"


def _factor_row(part: dict) -> dict:
    return {
        "label": part["label"],
        "text": f"{100.0 * part['contribution']:.1f}",
        "raw_text": _raw_text(part["factor"], part["raw"]),
        "normalized_text": _text(part["normalized"], 2),
        "weight_text": _text(part["weight"], 2),
    }


def build_matrix(exposures: dict, charm_by_strike: dict, ivs: dict[float, float | None],
                 spot: float, dte: float) -> dict:
    """The ranking of one expiry's book: every strike's factors and score and the expiry's colour
    scales. The rows the page shows are drawn from it at the price (window_rows)."""
    name = preset_name(dte)
    weights = in_score_weights(name)
    strikes = sorted(float(s) for s in exposures.keys())
    mags = {}
    for strike in strikes:
        bucket = exposures.get(strike)
        if not isinstance(bucket, dict):
            continue
        mags[strike] = magnitudes(bucket, charm_by_strike.get(strike), ivs.get(strike), spot)
    scored, flat, spans = score_magnitudes(
        {s: {k: v for k, v in f.items() if not str(k).startswith("_")} for s, f in mags.items()},
        weights,
    )
    cap = ceiling(weights)
    peaks = {key: _peak(f[key] for f in mags.values())
             for key in ("_net_gex", "OI", "_gross", "VOL", "_dex", "_vanna", "IV", "_charm", "_vol_oi")}
    peaks.update({key: _peak(None if f[key] is None else 1 - f[key] for f in mags.values())
                  for key in ("_pc_gex", "_pc_vol")})
    peaks["score"] = cap
    universe_n = sum(1 for s in mags if _in_universe(
        {k: v for k, v in mags[s].items() if not k.startswith("_")}))
    flat_labels = [_LABEL[k] for k in flat]
    notes = []
    if universe_n < THIN_BOOK:
        notes.append("Thin book: fewer than " + str(THIN_BOOK) + " strikes.")
    if flat_labels:
        notes.append(", ".join(flat_labels) + " does not vary, so it adds nothing.")
    return {
        "preset": name,
        "preset_text": name + " · ceiling " + f"{cap:g}",
        "scale_text": "0–" + f"{cap:g}",
        "weights_in_score": weights,
        "ceiling": cap,
        "notes": notes,
        "slopes": [
            {"label": _LABEL[k], "text": f"{100.0 * weights[k] / span:.2f}"}
            for k, span in spans.items() if span is not None and span != 0
        ],
        "ranked": {strike: (mags[strike], scored[strike]) for strike in mags},
        "peaks": peaks,
        "strikes": strikes,
    }


def _row(strike: float, ranked: tuple[dict, dict], peaks: dict) -> dict:
    """One strike's row of the matrix, its colours on the expiry's scales."""
    factors, result = ranked
    score = result["score"]
    pc_gex = factors["_pc_gex"]
    pc_vol = factors["_pc_vol"]
    return {
        "strike": strike,
        "strike_text": price_text(strike),
        "net_gex_text": _signed_millions(factors["_net_gex"]),
        "net_style": _ramp(factors["_net_gex"], peaks["_net_gex"], True),
        "net_reason": _absent(factors["_net_gex"], "net gamma is missing"),
        "oi_text": None if factors["OI"] is None else f"{factors['OI']:.0f}",
        "oi_style": _ramp(factors["OI"], peaks["OI"], False),
        "oi_reason": _absent(factors["OI"], "open interest is missing"),
        "pc_gex_text": _text(pc_gex, 2),
        "pc_gex_style": _ramp(None if pc_gex is None else 1 - pc_gex, peaks["_pc_gex"], True),
        "pc_gex_reason": _absent(pc_gex, "put/call gamma is missing"),
        "gross_text": _millions(factors["_gross"]),
        "gross_style": _ramp(factors["_gross"], peaks["_gross"], False),
        "gross_reason": _absent(factors["_gross"], "gross gamma is missing"),
        "dgex_text": None,
        "dgex_reason": DGEX_REASON,
        "volume_text": None if factors["VOL"] is None else f"{factors['VOL']:.0f}",
        "volume_style": _ramp(factors["VOL"], peaks["VOL"], False),
        "volume_reason": _absent(factors["VOL"], "volume is missing"),
        "pc_vol_text": _text(pc_vol, 2),
        "pc_vol_style": _ramp(None if pc_vol is None else 1 - pc_vol, peaks["_pc_vol"], True),
        "pc_vol_reason": _absent(pc_vol, "put/call volume is missing"),
        "vol_oi_text": _text(factors["_vol_oi"], 2),
        "vol_oi_style": _ramp(factors["_vol_oi"], peaks["_vol_oi"], False),
        "vol_oi_reason": _absent(factors["_vol_oi"], "volume/open interest is missing"),
        "flow_text": None,
        "flow_reason": FLOW_REASON,
        "dex_text": _signed_millions(factors["_dex"]),
        "dex_style": _ramp(factors["_dex"], peaks["_dex"], True),
        "dex_reason": _absent(factors["_dex"], "delta exposure is missing"),
        "vanna_text": _signed_millions(factors["_vanna"]),
        "vanna_style": _ramp(factors["_vanna"], peaks["_vanna"], True),
        "vanna_reason": _absent(factors["_vanna"], "vanna is missing"),
        "iv_text": _text(factors["IV"], 1),
        "iv_style": _ramp(factors["IV"], peaks["IV"], False),
        "iv_reason": _absent(factors["IV"], "implied volatility is missing"),
        "charm_text": _signed_thousands(factors["_charm"]),
        "charm_style": _ramp(factors["_charm"], peaks["_charm"], True),
        "charm_reason": _absent(factors["_charm"], "charm is missing"),
        "score": score,
        "score_text": None if score is None else str(int(round(score))),
        "heat_background": _ramp(score, peaks["score"], False),
        "missing": result["missing"],
        "contributions": [_factor_row(p) for p in result["contributions"]],
        "factors": [_factor_row(p) for p in result["factors"]],
    }
