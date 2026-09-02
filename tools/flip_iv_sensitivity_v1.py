"""Flip-vs-IV sensitivity + OI-by-moneyness census (RC-43 correction, RC-53 fair-method).

WHY THIS EXISTS. RC-43 closed the "does IV treatment move the gamma flip?" question with
MEASURED figures (median 0.068 percent of spot, 85 percent within 0.1 percent, max 0.71) from a
ONE-OFF script that was never committed — so the numbers could not be re-run, which is the exact
RC-6 failure class (a sampled number presented as measured). This module is that measurement,
committed, so every figure in RC-43 is reproducible on demand.

It also carries the OI-by-moneyness census that corrects RC-53: the claim "far-OTM strikes carry
large open interest" was false, and was briefly "confirmed" by comparing a wide bucket's SUM to a
narrow one's. Hence `oi_by_moneyness` uses EQUAL-WIDTH bins and reports OI PER STRIKE alongside
totals — a share-of-total over unequal bins is a strike-count artifact, not a concentration.

Definitions (stated because they change the answer):
  * flip = zero crossing of the production dealer-gamma profile (math_levels.compute_gamma_profile
    -> gamma_flip_from_profile), nearest spot, computed at the snapshot's own clock.
  * shift = |flip(raw per-strike IV) - flip(counterfactual IV)| / spot * 100 (percent of spot).
  * counterfactuals: FLAT_ALL (one ATM IV everywhere — the most extreme, removes smile AND term
    structure), FLAT_PER_EXPIRY (each expiry keeps its own ATM IV — removes smile, keeps term),
    WINGS_ONLY (only |moneyness| > wing_pct is flattened to its expiry ATM IV), NEAR_ONLY (only
    |moneyness| <= wing_pct is flattened). WINGS_ONLY vs NEAR_ONLY isolates WHERE the sensitivity
    lives. All are aggressive flattenings, NOT a smooth arbitrage-free surface fit: they bound the
    sensitivity, they do not estimate the raw-vs-smoothed-surface difference.

Usage:  python tools/flip_iv_sensitivity_v1.py [db_path]   (default data/ed_console.db)
"""
from __future__ import annotations

import json
import os
import sqlite3
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Runnable as `python tools/flip_iv_sensitivity_v1.py` (its REPRODUCE contract) — the repo root
# must be importable for math_levels regardless of the invoking cwd.
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

MIN_CONTRACTS = 8
DEFAULT_WING_PCT = 0.03
DTE_LO, DTE_HI = 2, 40          # multi-day: the regime RC-43 was about (0DTE excluded)
BIN_WIDTH = 0.01                # equal-width moneyness bins for the OI census
MAX_BIN = 10


def _et_now(ts_utc: float):
    """UTC epoch -> ET datetime, using the ONE timezone authority (time_et.ET).

    Never re-declares the "America/New_York" literal: a second definition of the ET zone is a
    duplicate authority, which is exactly the class that produced the two-session-classifier bug
    (RC-48). Enforced by tests/test_coh_sa2_et_authority.py.
    """
    from app.domain.time_et import ET

    x = float(ts_utc)
    if x > 1e12:
        x /= 1000.0
    return datetime.fromtimestamp(x, tz=timezone.utc).astimezone(ET)


def usable_contracts(chain: Any, dte_lo: int = DTE_LO, dte_hi: int = DTE_HI) -> list[dict]:
    """Contracts with OI, a strike, and DTE in range; expirationDate normalised to YYYY-MM-DD
    (stored blobs carry full ISO, which time_to_expiry_years does not parse)."""
    if not isinstance(chain, list):
        return []
    out = []
    for x in chain:
        if not isinstance(x, dict):
            continue
        dte = x.get("daysToExpiration")
        if dte is None or not (dte_lo <= dte <= dte_hi):
            continue
        if not x.get("strikePrice") or not (x.get("openInterest") or 0) > 0:
            continue
        out.append(dict(x, expirationDate=str(x.get("expirationDate"))[:10]))
    return out


def oi_by_moneyness(chains: list[tuple[float, list[dict]]]) -> list[dict]:
    """EQUAL-WIDTH moneyness bins with OI PER STRIKE (RC-53 fair-method).

    A bucket's share of total OI is meaningless across unequal widths — the wide OTM region wins
    on strike COUNT alone. oi_per_strike is the concentration measure; share_pct is reported only
    beside n_strikes so the artifact is visible rather than hidden.
    """
    oi: dict[int, float] = {}
    n: dict[int, int] = {}
    for spot, cts in chains:
        if not spot or spot <= 0:
            continue
        for x in cts:
            m = abs(float(x["strikePrice"]) / spot - 1.0)
            b = min(int(m / BIN_WIDTH), MAX_BIN)
            oi[b] = oi.get(b, 0.0) + float(x.get("openInterest") or 0)
            n[b] = n.get(b, 0) + 1
    total = sum(oi.values()) or 1.0
    rows = []
    for b in range(MAX_BIN + 1):
        strikes = n.get(b, 0)
        rows.append({
            "bin": f"{b}-{b+1}%" if b < MAX_BIN else f"{MAX_BIN}%+",
            "total_oi": round(oi.get(b, 0.0)),
            "n_strikes": strikes,
            "oi_per_strike": round(oi.get(b, 0.0) / strikes) if strikes else 0,
            "share_pct": round(oi.get(b, 0.0) / total * 100, 1),
        })
    return rows


def _atm_iv(cts: list[dict], spot: float):
    return min(cts, key=lambda c: abs(float(c["strikePrice"]) - spot)).get("volatility")


def counterfactual(cts: list[dict], spot: float, mode: str, wing_pct: float = DEFAULT_WING_PCT) -> list[dict]:
    """Return contracts with IV replaced per `mode` (see module docstring)."""
    if mode == "FLAT_ALL":
        iv = _atm_iv(cts, spot)
        return [dict(c, volatility=iv) for c in cts]
    by_exp: dict[str, list[dict]] = {}
    for c in cts:
        by_exp.setdefault(c["expirationDate"], []).append(c)
    aiv = {e: _atm_iv(v, spot) for e, v in by_exp.items()}
    out = []
    for c in cts:
        m = abs(float(c["strikePrice"]) / spot - 1.0)
        if mode == "FLAT_PER_EXPIRY":
            hit = True
        elif mode == "WINGS_ONLY":
            hit = m > wing_pct
        elif mode == "NEAR_ONLY":
            hit = m <= wing_pct
        else:
            raise ValueError(f"unknown mode {mode!r}")
        out.append(dict(c, volatility=aiv[c["expirationDate"]]) if hit else dict(c))
    return out


def flip_for(cts: list[dict], spot: float, now) -> float | None:
    from math_levels import compute_gamma_profile, gamma_flip_from_profile
    return gamma_flip_from_profile(compute_gamma_profile(cts, spot, now=now), spot)


def shift_stats(shifts: list[float]) -> dict[str, Any]:
    if not shifts:
        return {"n": 0}
    s = sorted(shifts)
    return {
        "n": len(s),
        "median_pct_of_spot": round(statistics.median(s), 4),
        "mean_pct_of_spot": round(statistics.mean(s), 4),
        "max_pct_of_spot": round(max(s), 4),
        "within_0_1pct_share": round(sum(1 for v in s if v <= 0.1) / len(s) * 100, 1),
    }


def load_wide_chains(db_path: str) -> list[tuple[float, float, list[dict]]]:
    """(spot, ts_utc, contracts) from the WIDE morning-full capture, TRADING DAYS ONLY.

    RC-54: the first run of this tool included weekend captures (35 Sat + 35 Sun + 2 Sun rows =
    33.5 percent of the source), whose spot is frozen and IV stale — market-closed rows drag every
    statistic toward "nothing moved". Non-trading dates are excluded here via the one calendar
    authority `time_et.is_trading_day_et`; there is deliberately NO opt-out parameter.
    """
    from app.domain.time_et import is_trading_day_et

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT spot, ts_utc, chain_json, et_date FROM option_chain_morning_full "
            "WHERE chain_json IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    out = []
    for spot, ts, blob, et_date in rows:
        if not spot or spot <= 0:
            continue
        if not is_trading_day_et(et_date):     # RC-54: market-closed capture -> never measured
            continue
        try:
            cts = usable_contracts(json.loads(blob))
        except (json.JSONDecodeError, TypeError):
            continue
        if len(cts) >= MIN_CONTRACTS:
            out.append((float(spot), float(ts), cts))
    return out


def run(db_path: str) -> dict[str, Any]:
    chains = load_wide_chains(db_path)
    modes = ("FLAT_ALL", "FLAT_PER_EXPIRY", "WINGS_ONLY", "NEAR_ONLY")
    shifts: dict[str, list[float]] = {m: [] for m in modes}
    n_flip = 0
    for spot, ts, cts in chains:
        now = _et_now(ts)
        raw = flip_for(cts, spot, now)
        if raw is None:
            continue
        n_flip += 1
        for m in modes:
            f = flip_for(counterfactual(cts, spot, m), spot, now)
            if f is not None:
                shifts[m].append(abs(raw - f) / spot * 100.0)
    return {
        "db_path": db_path,
        "source": "option_chain_morning_full (WIDE capture)",
        "dte_window": [DTE_LO, DTE_HI],
        "chains_loaded": len(chains),
        "chains_with_flip": n_flip,
        "oi_by_moneyness_equal_bins": oi_by_moneyness([(s, c) for s, _, c in chains]),
        "flip_shift_by_counterfactual": {m: shift_stats(v) for m, v in shifts.items()},
    }


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else os.path.join("data", "ed_console.db")
    print(json.dumps(run(path), indent=2))
