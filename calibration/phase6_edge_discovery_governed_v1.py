#!/usr/bin/env python3
"""
Phase 6 — Edge discovery on governed 1m snapshots (BAR_ANCHOR_V1 schema 3).

Population: timeframe=1m, horizon_outcome_schema_version=3, all outcome_* and outcome_*_pts
present, valid bar anchor (same rule as anchor_audit).

  python -m calibration.phase6_edge_discovery_governed_v1 --db data/ed_console.db
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import random
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.analyze_phase4 import _directional_pnl
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB, ensure_artifacts_dir
from db import configure_sqlite_connection
from horizon_outcomes import OUTCOME_BAR_SPECS
from instrument_identity import ticker_storage_key

try:
    from scipy import stats as scipy_stats
except Exception:
    scipy_stats = None

HORIZONS: list[tuple[str, str, str, str]] = [
    # outcome_col, pts_col, pred prefix e.g. pred_5c_
    ("outcome_1c", "outcome_1c_pts", "pred_1c_", "1c"),
    ("outcome_5c", "outcome_5c_pts", "pred_5c_", "5c"),
    ("outcome_15c", "outcome_15c_pts", "pred_15c_", "15c"),
    ("outcome_60c", "outcome_60c_pts", "pred_60c_", "60c"),
]

MIN_N_TICKER = 1000
MIN_N_SLICE = 80
BOOT_N = 600
RNG_SEED = 42


def _mean(xs: list[float]) -> float:
    return float(sum(xs) / len(xs)) if xs else float("nan")


def _win_rate(pnls: list[float]) -> float:
    if not pnls:
        return float("nan")
    return sum(1 for p in pnls if p > 0) / len(pnls)


def _bootstrap_mean_diff(
    actual: list[float], baseline: list[float], *, n_boot: int = BOOT_N, seed: int = RNG_SEED
) -> dict[str, Any]:
    if len(actual) != len(baseline) or len(actual) < 2:
        return {"n": len(actual), "mean_diff": None, "ci95_low": None, "ci95_high": None, "p_value_approx": None}
    rng = random.Random(seed)
    diffs_full = [a - b for a, b in zip(actual, baseline)]
    obs = _mean(diffs_full)
    diffs = diffs_full
    if len(diffs) > 6000:
        pick = rng.sample(range(len(diffs)), 6000)
        diffs = [diffs[i] for i in pick]
    boot: list[float] = []
    n = len(diffs)
    n_boot_eff = min(n_boot, 400)
    for _ in range(n_boot_eff):
        boot.append(_mean([diffs[rng.randrange(n)] for _ in range(n)]))
    boot.sort()
    lo = boot[int(0.025 * len(boot))]
    hi = boot[int(0.975 * len(boot))]
    p_two = None
    if scipy_stats is not None:
        try:
            _, p_two = scipy_stats.ttest_1samp(diffs, 0.0)
        except Exception:
            p_two = None
    # simple percentile p: proportion of boot means <= 0 if obs > 0
    nb = len(boot)
    p_perm = sum(1 for b in boot if b <= 0) / nb if obs > 0 else sum(1 for b in boot if b >= 0) / nb
    return {
        "n": n,
        "mean_diff": round(obs, 8),
        "ci95_low": round(lo, 8),
        "ci95_high": round(hi, 8),
        "p_value_ttest": float(p_two) if p_two is not None else None,
        "p_value_bootstrap_extreme": round(min(p_perm, 1.0 - p_perm) * 2, 8),  # two-sided-ish
    }


def _pred_signal(pu: float | None, pd: float | None, pf: float | None) -> str | None:
    if pu is None or pd is None or pf is None:
        return None
    m = max(float(pu), float(pd), float(pf))
    if float(pu) == m:
        return "long"
    if float(pd) == m:
        return "short"
    return "flat"


def _pnl_directional(sig: str | None, outcome: str | None, pts: float | None) -> float | None:
    if pts is None or outcome is None:
        return None
    s = (sig or "").lower()
    if s == "flat":
        return 0.0
    if s not in ("long", "short"):
        return None
    return _directional_pnl(s, outcome, float(pts))


def _load_bar_ends(conn: sqlite3.Connection) -> dict[str, list[float]]:
    by_t: dict[str, list[float]] = defaultdict(list)
    for r in conn.execute("SELECT ticker, bar_end_ts_utc FROM price_bars_1m ORDER BY ticker, bar_end_ts_utc"):
        by_t[r["ticker"]].append(float(r["bar_end_ts_utc"]))
    return dict(by_t)


def _has_anchor(bar_ends: dict[str, list[float]], ticker: str, ts: float) -> bool:
    t = ticker_storage_key(ticker)
    ends = bar_ends.get(t)
    if not ends:
        return False
    i = bisect.bisect_right(ends, float(ts)) - 1
    return i >= 0


def _session_bucket(ms: str | None, sb: str | None) -> str:
    s = (ms or sb or "").strip().lower()
    if s == "rth":
        return "rth"
    if "pre" in s:
        return "premarket"
    if "after" in s:
        return "afterhours"
    if "closed" in s or s == "closed":
        return "closed"
    if s:
        return s
    return "unknown"


def _row_market_session(r: sqlite3.Row) -> str:
    from ml_data_common import row_market_session_from_ts_utc

    return row_market_session_from_ts_utc(r)


def load_rows(
    db_path: Path,
    *,
    min_ts_utc: float | None = None,
) -> tuple[list[sqlite3.Row], dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    bar_ends = _load_bar_ends(conn)

    q = """
    SELECT *
    FROM snapshots
    WHERE timeframe = '1m'
      AND COALESCE(horizon_outcome_schema_version, 3) = 3
      AND outcome_1c IS NOT NULL AND outcome_1c_pts IS NOT NULL
      AND outcome_5c IS NOT NULL AND outcome_5c_pts IS NOT NULL
      AND outcome_15c IS NOT NULL AND outcome_15c_pts IS NOT NULL
      AND outcome_60c IS NOT NULL AND outcome_60c_pts IS NOT NULL
    """
    raw = conn.execute(q).fetchall()
    rows: list[sqlite3.Row] = []
    excl = 0
    for r in raw:
        if _has_anchor(bar_ends, r["ticker"], float(r["ts_utc"])):
            rows.append(r)
        else:
            excl += 1
    if min_ts_utc is not None:
        floor = float(min_ts_utc)
        rows = [r for r in rows if float(r["ts_utc"]) >= floor]
    conn.close()
    meta = {
        "db": str(db_path.resolve()),
        "ts": time.time(),
        "snapshots_raw_all_outcomes": len(raw),
        "snapshots_after_anchor": len(rows),
        "excluded_no_anchor": excl,
        "min_ts_utc": min_ts_utc,
    }
    return rows, meta


def horizon_metrics(
    members: list[sqlite3.Row],
    ocol: str,
    pcol: str,
    prefix: str,
    *,
    with_bootstrap: bool = True,
) -> dict[str, Any]:
    pu_k, pd_k, pf_k = prefix + "up_prob", prefix + "down_prob", prefix + "flat_prob"
    act: list[float] = []
    long_b: list[float] = []
    short_b: list[float] = []
    rnd_b: list[float] = []
    correct = 0
    n_pred = 0
    for idx, r in enumerate(members):
        oc = r[ocol]
        pt = r[pcol]
        if pt is None or oc is None:
            continue
        pu, pd, pf = r[pu_k], r[pd_k], r[pf_k]
        sig = _pred_signal(
            float(pu) if pu is not None else None,
            float(pd) if pd is not None else None,
            float(pf) if pf is not None else None,
        )
        p_a = _pnl_directional(sig if sig != "flat" else "flat", oc, float(pt))
        p_l = _directional_pnl("long", oc, float(pt))
        p_s = _directional_pnl("short", oc, float(pt))
        if p_a is None or p_l is None or p_s is None:
            continue
        rng_i = random.Random(RNG_SEED + idx + hash(ocol) % 100000)
        rnd = float(p_l) if rng_i.random() < 0.5 else float(p_s)
        act.append(float(p_a))
        long_b.append(float(p_l))
        short_b.append(float(p_s))
        rnd_b.append(float(rnd))
        # directional accuracy: long/up, short/down
        if sig in ("long", "short"):
            n_pred += 1
            y = (oc or "").strip().lower()
            if sig == "long" and y == "up":
                correct += 1
            elif sig == "short" and y == "down":
                correct += 1

    n = len(act)
    boot_vs_long = _bootstrap_mean_diff(act, long_b) if n >= 2 and with_bootstrap else {}
    boot_vs_rnd = _bootstrap_mean_diff(act, rnd_b) if n >= 2 and with_bootstrap else {}
    acc = correct / n_pred if n_pred else float("nan")

    return {
        "n": n,
        "win_rate_model": round(_win_rate(act), 6),
        "win_rate_always_long": round(_win_rate(long_b), 6),
        "win_rate_always_short": round(_win_rate(short_b), 6),
        "win_rate_random_balanced": round(_win_rate(rnd_b), 6),
        "mean_ev_model": round(_mean(act), 8),
        "mean_ev_always_long": round(_mean(long_b), 8),
        "mean_ev_always_short": round(_mean(short_b), 8),
        "mean_ev_random_balanced": round(_mean(rnd_b), 8),
        "directional_accuracy_vs_outcome": round(acc, 6),
        "n_directional_predictions": n_pred,
        "bootstrap_model_minus_long": boot_vs_long,
        "bootstrap_model_minus_random": boot_vs_rnd,
    }


def split_time_quartiles(rows: list[sqlite3.Row]) -> dict[str, list[sqlite3.Row]]:
    if not rows:
        return {}
    ts = sorted(float(r["ts_utc"]) for r in rows)
    q1, q2, q3 = ts[len(ts) // 4], ts[len(ts) // 2], ts[(3 * len(ts)) // 4]

    def bkt(t: float) -> str:
        if t <= q1:
            return "early_q1"
        if t <= q2:
            return "mid_early_q2"
        if t <= q3:
            return "mid_late_q3"
        return "recent_q4"

    out: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        out[bkt(float(r["ts_utc"]))].append(r)
    return dict(out)


def run_phase6(db_path: Path, *, min_ts_utc: float | None = None) -> dict[str, Any]:
    rows, meta = load_rows(db_path, min_ts_utc=min_ts_utc)
    out: dict[str, Any] = {
        "meta": meta,
        "horizons": {},
        "ticker_ranking_by_horizon": {},
        "confidence_curves": {},
        "session_by_horizon": {},
        "regime_by_horizon": {},
        "combined_top_slices": [],
        "stability_quartiles": {},
        "notes": [],
    }

    if len(rows) < MIN_N_SLICE:
        out["error"] = "insufficient_rows"
        return out

    # --- Global per horizon ---
    for ocol, pcol, prefix, hid in HORIZONS:
        out["horizons"][hid] = horizon_metrics(rows, ocol, pcol, prefix)

    ref_h = "5c"
    ocol, pcol, prefix, _ = next(x for x in HORIZONS if x[3] == ref_h)

    # --- Ticker slices (>1000) ---
    by_t: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        by_t[str(r["ticker"])].append(r)

    ticker_rank: list[dict[str, Any]] = []
    for tkr, mem in by_t.items():
        if len(mem) < MIN_N_TICKER:
            continue
        hm = horizon_metrics(mem, ocol, pcol, prefix, with_bootstrap=False)
        dvl = hm.get("mean_ev_model")
        dbl = hm.get("mean_ev_always_long")
        delta = None
        if isinstance(dvl, float) and isinstance(dbl, float) and not math.isnan(dvl) and not math.isnan(dbl):
            delta = dvl - dbl
        ticker_rank.append(
            {
                "ticker": tkr,
                "n": len(mem),
                "mean_ev_model_5c": hm.get("mean_ev_model"),
                "mean_ev_long_5c": hm.get("mean_ev_always_long"),
                "delta_ev_vs_long_5c": delta,
                "win_rate_model_5c": hm.get("win_rate_model"),
            }
        )
    ticker_rank.sort(key=lambda x: (x.get("delta_ev_vs_long_5c") is not None, x.get("delta_ev_vs_long_5c") or 0.0), reverse=True)
    out["ticker_ranking_by_horizon"][ref_h] = ticker_rank

    # --- Confidence: fusion_dominant_prob quantile bins ---
    conf_rows: list[tuple[sqlite3.Row, float]] = []
    for r in rows:
        fp = r["fusion_dominant_prob"]
        if fp is None:
            continue
        conf_rows.append((r, float(fp)))
    conf_rows.sort(key=lambda x: -x[1])
    n_c = len(conf_rows)
    conf_curve: list[dict[str, Any]] = []
    if n_c >= 50:
        for pct in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
            k = max(1, int(n_c * pct / 100))
            chunk = [x[0] for x in conf_rows[:k]]
            hm = horizon_metrics(chunk, ocol, pcol, prefix)
            conf_curve.append({"top_pct": pct, "n": hm["n"], **{x: hm[x] for x in hm if x != "n"}})

    # per-horizon max-prob confidence
    conf_by_h: dict[str, list[dict[str, Any]]] = {}
    for ocol2, pcol2, prefix2, hid2 in HORIZONS:
        scored: list[tuple[sqlite3.Row, float]] = []
        for r in rows:
            pu, pd, pf = r[prefix2 + "up_prob"], r[prefix2 + "down_prob"], r[prefix2 + "flat_prob"]
            if pu is None or pd is None or pf is None:
                continue
            scored.append((r, max(float(pu), float(pd), float(pf))))
        scored.sort(key=lambda x: -x[1])
        n_s = len(scored)
        curve = []
        if n_s >= 50:
            for pct in (10, 20, 30, 50, 70, 100):
                k = max(1, int(n_s * pct / 100))
                ch = [x[0] for x in scored[:k]]
                hm = horizon_metrics(ch, ocol2, pcol2, prefix2, with_bootstrap=False)
                curve.append({"top_pct": pct, "n": hm["n"], "mean_ev_model": hm["mean_ev_model"], "mean_ev_long": hm["mean_ev_always_long"]})
        conf_by_h[hid2] = curve
    out["confidence_curves"]["fusion_dominant_prob_top_pct_5c"] = conf_curve
    out["confidence_curves"]["max_pred_prob_top_pct_by_horizon"] = conf_by_h

    # --- Session ---
    by_s: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        by_s[_session_bucket(_row_market_session(r), r["session_bucket"])].append(r)
    sess_h: dict[str, Any] = {}
    for ocol3, pcol3, prefix3, hid3 in HORIZONS:
        sess_h[hid3] = {}
        for sname, mem in by_s.items():
            if len(mem) < MIN_N_SLICE:
                continue
            sess_h[hid3][sname] = horizon_metrics(mem, ocol3, pcol3, prefix3, with_bootstrap=False)
    out["session_by_horizon"] = sess_h

    # --- Regime ---
    by_r: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        rp = (r["regime_primary"] or "unknown").strip() or "unknown"
        by_r[rp].append(r)
    reg_h: dict[str, Any] = {}
    for ocol4, pcol4, prefix4, hid4 in HORIZONS:
        reg_h[hid4] = {}
        for rname, mem in by_r.items():
            if len(mem) < MIN_N_SLICE:
                continue
            reg_h[hid4][rname] = horizon_metrics(mem, ocol4, pcol4, prefix4, with_bootstrap=False)
    out["regime_by_horizon"] = reg_h

    # --- Combined filters (sample of meaningful combos) ---
    combos: list[dict[str, Any]] = []
    for tkr, mem in by_t.items():
        if len(mem) < MIN_N_TICKER:
            continue
        by_s2: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for r in mem:
            by_s2[_session_bucket(_row_market_session(r), r["session_bucket"])].append(r)
        for sname, mem2 in by_s2.items():
            if len(mem2) < MIN_N_SLICE:
                continue
            hm = horizon_metrics(mem2, ocol, pcol, prefix, with_bootstrap=False)
            combos.append(
                {
                    "slice": f"ticker={tkr}|session={sname}",
                    "n": hm["n"],
                    "mean_ev_model": hm["mean_ev_model"],
                    "mean_ev_long": hm["mean_ev_always_long"],
                    "delta_vs_long": (hm["mean_ev_model"] - hm["mean_ev_always_long"])
                    if hm.get("mean_ev_model") is not None
                    else None,
                    "bootstrap": hm.get("bootstrap_model_minus_long"),
                }
            )
        # ticker + regime
        by_r2: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for r in mem:
            by_r2[(r["regime_primary"] or "unknown").strip() or "unknown"].append(r)
        for rname, mem3 in by_r2.items():
            if len(mem3) < MIN_N_SLICE:
                continue
            hm = horizon_metrics(mem3, ocol, pcol, prefix, with_bootstrap=False)
            combos.append(
                {
                    "slice": f"ticker={tkr}|regime={rname}",
                    "n": hm["n"],
                    "mean_ev_model": hm["mean_ev_model"],
                    "mean_ev_long": hm["mean_ev_always_long"],
                    "delta_vs_long": (hm["mean_ev_model"] - hm["mean_ev_always_long"])
                    if hm.get("mean_ev_model") is not None
                    else None,
                    "bootstrap": hm.get("bootstrap_model_minus_long"),
                }
            )

    combos.sort(
        key=lambda x: (x.get("delta_vs_long") is not None, x.get("delta_vs_long") or 0.0),
        reverse=True,
    )
    out["combined_top_slices"] = combos[:40]

    # --- Stability ---
    tq = split_time_quartiles(rows)
    stab: dict[str, Any] = {}
    for name, mem in tq.items():
        stab[name] = {
            h[3]: horizon_metrics(mem, h[0], h[1], h[2], with_bootstrap=(h[3] == "5c")) for h in HORIZONS
        }
    out["stability_quartiles"] = stab

    # --- Classification ---
    strong = 0
    weak = 0
    for hid, hm in out["horizons"].items():
        b = hm.get("bootstrap_model_minus_long") or {}
        if b.get("ci95_low") is not None and b.get("ci95_low", 0) > 0 and (hm.get("n") or 0) >= MIN_N_SLICE:
            strong += 1
        elif b.get("mean_diff") is not None and b.get("mean_diff", 0) > 0:
            weak += 1

    edge_tickers = sum(
        1
        for t in ticker_rank
        if t.get("delta_ev_vs_long_5c") is not None and float(t["delta_ev_vs_long_5c"]) > 0
    )
    conf_monotonic = True
    evs = [x.get("mean_ev_model") for x in conf_curve if x.get("n", 0) >= MIN_N_SLICE]
    for i in range(1, len(evs)):
        if evs[i] < evs[i - 1]:
            conf_monotonic = False
            break

    if strong >= 2 and edge_tickers >= 3:
        final = "C_STRONG_EDGE"
    elif strong >= 1 or weak >= 3 or edge_tickers >= 5:
        final = "B_WEAK_CONDITIONAL_EDGE"
    else:
        final = "A_NO_EDGE"

    out["final_classification"] = {
        "label": final,
        "horizons_with_ci95_gt0_vs_long": strong,
        "horizons_with_positive_mean_delta_vs_long": weak,
        "tickers_with_positive_delta_ev_5c": edge_tickers,
        "confidence_curve_monotonic_ev_fusion_top_pct": conf_monotonic,
    }
    out["notes"].append(
        "Model signal = argmax(pred_up, pred_down, pred_flat); flat -> 0 PnL. Baselines: always long, always short, random balanced (same as edge_validation)."
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--calibration-widen-cohort",
        action="store_true",
        help="Restrict to ts_utc >= COH-I-A fix landing (99ea0e0 / time_et.COH_I_A_ET_AUTHORITY_TS_UTC)",
    )
    ap.add_argument(
        "--min-ts-utc",
        type=float,
        default=None,
        help="Explicit ts_utc floor (overrides --calibration-widen-cohort when set)",
    )
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="phase6_edge_discovery_governed_v1", write_capable=False)
    db_path = args.db.resolve()
    if not db_path.is_file():
        print(json.dumps({"error": f"missing db {db_path}"}))
        return 2
    min_ts: float | None = args.min_ts_utc
    if min_ts is None and args.calibration_widen_cohort:
        from ml_data_common import calibration_widen_min_ts_utc

        min_ts = calibration_widen_min_ts_utc()
    rep = run_phase6(db_path, min_ts_utc=min_ts)
    ensure_artifacts_dir()
    outp = ROOT / "data" / "phase6_edge_discovery_governed_v1_report.json"
    outp.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"wrote": str(outp), "final": rep.get("final_classification"), "n_rows": rep.get("meta", {}).get("snapshots_after_anchor")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
