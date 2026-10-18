"""Per-strike composite for one expiry.

The exposure book and the charm map are the producers already computed for
that expiry. This module ranks them. It does not recompute a greek. The
per-strike volatility blend is produced here because Schwab sends a
volatility on each contract and not one number for the strike.
"""

from __future__ import annotations

import math
from typing import Any

from math_exposure_core import (
    bucket_metric, strike_total_oi, strike_total_volume, strike_volume_legs,
)
from numeric_contract import schwab_count, schwab_number

ABSENT = ("DGEXM", "FLOWM")
WINDOW = 7
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
        if span is None and present:
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
    """Seven listed strikes below the price, seven above, and the strike on the price."""
    below = sorted((s for s in strikes if s < spot), reverse=True)[:WINDOW]
    above = sorted(s for s in strikes if s > spot)[:WINDOW]
    at = [s for s in strikes if s == spot]
    return sorted(below + at + above)


def under_strike(price: float, strikes: list[float]) -> float | None:
    """The lowest listed strike at or above `price`, where a marker sits."""
    at_or_above = [s for s in strikes if s >= price]
    if not at_or_above:
        return None
    return min(at_or_above)


def _count_text(n: float) -> str:
    if float(n) == int(n):
        return str(int(n))
    return f"{n:g}"


def _text(n: float | None, digits: int) -> str | None:
    if n is None:
        return None
    return f"{n:.{digits}f}"


def _millions(n: float | None) -> str | None:
    if n is None:
        return None
    return f"{n / 1e6:.2f}"


def _thousands(n: float | None) -> str | None:
    if n is None:
        return None
    return f"{n / 1000:.2f}"


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
                 spot: float, dte: float, markers: list[dict]) -> dict:
    """The rows, the score, and the marker placement for one expiry's book."""
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
    shown = window_strikes(list(mags), spot)
    cap = ceiling(weights)
    spot_under = under_strike(spot, strikes)
    rows = []
    for strike in sorted(shown, reverse=True):
        factors = mags[strike]
        result = scored[strike]
        score = result["score"]
        rows.append({
            "strike": strike,
            "strike_text": _count_text(strike),
            "distance_text": _text(strike - spot, 2),
            "net_gex_text": _millions(factors["_net_gex"]),
            "oi_text": None if factors["OI"] is None else f"{factors['OI']:.0f}",
            "pc_gex_text": _text(factors["_pc_gex"], 2),
            "gross_text": _millions(factors["_gross"]),
            "dgex_text": None,
            "volume_text": None if factors["VOL"] is None else f"{factors['VOL']:.0f}",
            "pc_vol_text": _text(factors["_pc_vol"], 2),
            "vol_oi_text": _text(factors["_vol_oi"], 2),
            "flow_text": None,
            "dex_text": _millions(factors["_dex"]),
            "vanna_text": _millions(factors["_vanna"]),
            "iv_text": _text(factors["IV"], 1),
            "charm_text": _thousands(factors["_charm"]),
            "score": score,
            "score_text": None if score is None else str(int(round(score))),
            "heat_background": None if score is None or cap == 0 else (
                "rgba(47,107,255," + f"{0.15 + 0.55 * (score / cap):.3f}" + ")"),
            "spot_line": strike == spot_under,
            "missing": result["missing"],
            "contributions": [_factor_row(p) for p in result["contributions"]],
            "factors": [_factor_row(p) for p in result["factors"]],
            "markers": [m["label"] for m in markers if m.get("under_strike") == strike],
        })
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
        "weights_in_score": weights,
        "ceiling": cap,
        "notes": notes,
        "slopes": [
            {"label": _LABEL[k], "text": f"{100.0 * weights[k] / span:.2f}"}
            for k, span in spans.items() if span is not None and span != 0
        ],
        "spot_text": _count_text(spot),
        "rows": rows,
        "offscreen": [
            {"label": m["label"], "price_text": m["price_text"]}
            for m in markers if m.get("under_strike") not in shown
        ],
    }


def place_markers(markers: list[dict], strikes: list[float]) -> list[dict]:
    placed = []
    for marker in markers:
        price = marker.get("price")
        if price is None:
            continue
        under = under_strike(float(price), strikes)
        placed.append({
            "label": marker["label"],
            "price_text": _text(float(price), 2),
            "under_strike": under,
        })
    return placed
