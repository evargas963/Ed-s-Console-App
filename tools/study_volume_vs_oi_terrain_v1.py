#!/usr/bin/env python3
"""REGISTERED TEST 2 (single-name sign row, due 2026-08-03): volume- vs OI-weighted
SPY terrain — measures the intraday-staleness cost of open interest directly.

DESIGN (register row spec: "recompute one week of SPY terrain VOLUME-weighted
(totalVolume already persisted per contract) vs OI-weighted and diff flips/walls"):
For each SPY wide morning capture (option_chain_morning_full), compute terrain TWICE
through the UNCHANGED production pipeline (`terrain_engine.compute_terrain`):
  A) as stored (OI-weighted — production behavior), and
  B) with each contract's openInterest REPLACED by its totalVolume (deep-copied
     contracts; production code untouched — no second exposure engine to drift).
Diff per day: gamma flip, call wall, put wall, regime sign at spot, confidence.

PRE-REGISTERED BARS — WRITTEN BEFORE THE FIRST RUN (2026-07-22, operator directive
"we build everything tonight"); anything else observed is post-hoc:
  PASS (OI-staleness acceptable for regime labels) requires BOTH, on days where
  both weightings produce a usable regime:
    (1) regime-sign agreement >= 75% of comparable days;
    (2) median |flip_vol - flip_oi| <= 0.5% of spot.
  Days where either side fails closed are COUNTED and DISCLOSED, excluded from
  the agreement denominator. n accrues daily with the 08:25 capture; a verdict
  on n < 5 trading days is PARTIAL by definition and says so.

HONESTY NOTES (disclosed, not discovered later): morning-capture volume is the
first ~30-60 min only (sparse — the substitution's own require-positive filter
keeps only traded contracts, measured ~23% of the wide chain on 2026-07-22);
2026-07-19 is a Sunday connectivity test (stale volume) and is flagged NON_TRADING.
Read-only on ed_console.db; writes only reports/.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from terrain_engine import compute_terrain  # noqa: E402

DB = ROOT / "data" / "ed_console.db"
OUT = ROOT / "reports" / "study_volume_vs_oi_terrain_v1.json"

REGIME_AGREE_MIN_PCT = 75.0        # pre-registered bar (1)
FLIP_DIFF_MAX_PCT_OF_SPOT = 0.5    # pre-registered bar (2)
THIN_DAY_MIN_VOL_CONTRACTS = 100   # disclosure threshold, not an exclusion


def volume_substituted(contracts: list[dict]) -> tuple[list[dict], int]:
    """Deep-copied contracts with openInterest := totalVolume.

    Fail-closed by construction: a contract with missing/zero totalVolume gets
    openInterest 0 and is dropped by the production require_oi filter — absence
    reads as absence, never as a fabricated weight. Returns (contracts, n_kept).
    """
    out = deepcopy(contracts)
    kept = 0
    for ct in out:
        v = ct.get("totalVolume")
        try:
            vf = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            vf = 0.0
        ct["openInterest"] = vf if vf > 0 else 0
        if vf > 0:
            kept += 1
    return out, kept


def _sign(x: float | None) -> str | None:
    if x is None or x == 0:
        return None
    return "LONG" if x > 0 else "SHORT"


def _compare_day(et_date: str, spot: float, chain_raw: str) -> dict:
    """OI vs volume-substituted terrain for one stored wide capture."""
    contracts = json.loads(chain_raw)
    oi_snap = compute_terrain("SPY", contracts, float(spot))
    vol_contracts, n_vol = volume_substituted(contracts)
    vol_snap = compute_terrain("SPY", vol_contracts, float(spot))
    oi_sign = _sign(oi_snap.net_gex_at_spot)
    vol_sign = _sign(vol_snap.net_gex_at_spot)
    flip_diff_pct = (
        round(abs(vol_snap.gamma_flip - oi_snap.gamma_flip) / float(spot) * 100, 4)
        if oi_snap.gamma_flip is not None and vol_snap.gamma_flip is not None
        else None)
    return {
        "day": et_date, "spot": float(spot),
        "non_trading_capture": date.fromisoformat(et_date).weekday() >= 5,
        "n_contracts": len(contracts), "n_volume_contracts": n_vol,
        "thin_volume_day": n_vol < THIN_DAY_MIN_VOL_CONTRACTS,
        "oi": {"flip": oi_snap.gamma_flip, "call_wall": oi_snap.call_wall,
                "put_wall": oi_snap.put_wall, "sign_at_spot": oi_sign,
                "confidence": oi_snap.confidence},
        "vol": {"flip": vol_snap.gamma_flip, "call_wall": vol_snap.call_wall,
                 "put_wall": vol_snap.put_wall, "sign_at_spot": vol_sign,
                 "confidence": vol_snap.confidence},
        "flip_diff_pct_of_spot": flip_diff_pct,
        "call_wall_same_strike": (oi_snap.call_wall == vol_snap.call_wall
                                  if oi_snap.call_wall is not None
                                  and vol_snap.call_wall is not None else None),
        "put_wall_same_strike": (oi_snap.put_wall == vol_snap.put_wall
                                 if oi_snap.put_wall is not None
                                 and vol_snap.put_wall is not None else None),
        "regime_sign_agrees": (oi_sign == vol_sign
                               if oi_sign is not None and vol_sign is not None
                               else None),
    }


def run() -> dict:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)
    rows = con.execute(
        "SELECT et_date, spot, chain_json FROM option_chain_morning_full "
        "WHERE ticker='SPY' ORDER BY et_date").fetchall()
    con.close()
    days = [_compare_day(et_date, spot, chain_raw) for et_date, spot, chain_raw in rows]

    trading = [d for d in days if not d["non_trading_capture"]]
    comparable = [d for d in trading if d["regime_sign_agrees"] is not None]
    agree_pct = (round(100 * sum(d["regime_sign_agrees"] for d in comparable)
                       / len(comparable), 1) if comparable else None)
    flip_diffs = [d["flip_diff_pct_of_spot"] for d in trading
                  if d["flip_diff_pct_of_spot"] is not None]
    med_flip = round(median(flip_diffs), 4) if flip_diffs else None

    n_td = len(trading)
    bars_met = (agree_pct is not None and agree_pct >= REGIME_AGREE_MIN_PCT
                and med_flip is not None and med_flip <= FLIP_DIFF_MAX_PCT_OF_SPOT)
    verdict = ("PASS_PARTIAL" if bars_met else "FAIL_PARTIAL") if n_td < 5 else \
              ("PASS" if bars_met else "FAIL")

    rep = {
        "study": "volume_vs_oi_terrain_v1", "ticker": "SPY",
        "pre_registered_bars": {
            "regime_agree_min_pct": REGIME_AGREE_MIN_PCT,
            "flip_diff_max_pct_of_spot": FLIP_DIFF_MAX_PCT_OF_SPOT,
            "partial_below_trading_days": 5,
        },
        "n_days_total": len(days), "n_trading_days": n_td,
        "n_comparable_regime_days": len(comparable),
        "regime_sign_agree_pct": agree_pct,
        "median_flip_diff_pct_of_spot": med_flip,
        "verdict": verdict,
        "days": days,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    return rep


def main() -> int:
    rep = run()
    print(json.dumps({k: v for k, v in rep.items() if k != "days"}, indent=2))
    for d in rep["days"]:
        print(f"{d['day']}{' (NON-TRADING)' if d['non_trading_capture'] else ''}"
              f"{' (THIN)' if d['thin_volume_day'] else ''}: "
              f"oi flip={d['oi']['flip']} vol flip={d['vol']['flip']} "
              f"diff={d['flip_diff_pct_of_spot']}% sign {d['oi']['sign_at_spot']}"
              f"->{d['vol']['sign_at_spot']} agree={d['regime_sign_agrees']} "
              f"vol_contracts={d['n_volume_contracts']}")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
