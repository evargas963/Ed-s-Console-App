"""Does chain SPAN determine the at-spot dealer-gamma SIGN? (2026-08-26)

WHY THIS EXISTS: `math_levels.GAMMA_FLIP_MIN_SPAN_PCT = 0.05` gates whether terrain issues a REGIME
and a POSTURE at all — below it the verdict is LOW_CONFIDENCE_NARROW_CHAIN and everything is
withheld. The code justified that floor by asserting a chain narrower than it "cannot support even
the at-spot SIGN". That was never measured, and the flip-LEVEL convergence study
(`study_flip_span_convergence_v1.py`) does NOT establish it: that study measures
|windowed flip - full-chain flip|, a LEVEL distance, and is silent about the SIGN.

This measures the missing quantity directly.

METHOD: for each stored wide chain, compute dealer gamma AT SPOT on the FULL delivered strike set
(the reference), then recompute using only strikes within +/-X% of spot, and compare the two by
SIGN. The accumulation replicates `compute_gamma_profile`'s inner loop at the single price s=spot,
using the SAME production primitives (`_contract_inputs`, `_dealer_sign`, `bs_gamma`) so this is the
shipped math, not a re-derivation.

TWO GUARDS that keep the numbers honest:
  * A chain whose delivered span is already <= the rung is NOT truncated there — its "windowed"
    value IS the reference, so it would agree BY CONSTRUCTION. Those rows are EXCLUDED per rung
    rather than counted as agreement (the pass-through bias that flatters wide rungs).
  * Agreement is also reported CONDITIONED on how decisively signed the book is, because a sign
    flip when the net is ~0 is genuine ambiguity, not an error. `net/gross` =
    |net gamma at spot| / sum|per-contract contributions|.

Sampling is seed-fixed so a re-run reproduces the same cohort.

Usage:  python tools/study_at_spot_sign_stability_v1.py [db_path] [--sample N] [--seed S]
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

#: Ladder spans to test, as a fraction of spot. Brackets GAMMA_FLIP_MIN_SPAN_PCT (0.05) on both
#: sides so a cliff at the floor would be visible if one existed.
SPAN_LADDER = (0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.15)

#: Buckets for |net| / sum|contributions|, applied AT THE FLOOR RUNG ONLY. The low buckets are where
#: the book is nearly balanced, and there the sign is close to chance AT THAT WIDTH. This report does
#: NOT cross-tab concentration against span, so it cannot say whether a wider chain rescues such a
#: book — running that cross-tab is the open follow-up, not a conclusion available here.
NET_GROSS_BUCKETS = ((0.00, 0.02), (0.02, 0.05), (0.05, 0.10), (0.10, 1.01))

MIN_CONTRACTS_FOR_A_READ = 6


def at_spot_gamma(parsed: list, s: float) -> tuple[float | None, float | None]:
    """(net, gross) dealer gamma at price `s` — compute_gamma_profile's loop at one price.

    Returns (None, None) when no contract produced a usable gamma, mirroring the profile's
    empty-parse behaviour rather than reporting a fabricated zero.
    """
    from math_levels import SIGN_MODEL_NAIVE, _dealer_sign, bs_gamma

    total = 0.0
    gross = 0.0
    any_v = False
    for strike, oi, mult, t_years, sigma, sign in parsed:
        g = bs_gamma(s, strike, t_years, sigma)
        if g is None:
            continue
        contribution = g * oi * mult * s * s * 0.01
        total += _dealer_sign(sign, SIGN_MODEL_NAIVE) * contribution
        gross += abs(contribution)
        any_v = True
    return (total, gross) if any_v else (None, None)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval — the repo reports a rate with an interval, never a bare percentage."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def run(db_path: str, sample_n: int, seed: int) -> dict:
    from math_levels import _contract_inputs
    from tools.flip_iv_sensitivity_v1 import _et_now, load_wide_chains

    chains = load_wide_chains(db_path)          # trading days only (RC-54)
    rng = random.Random(seed)
    cohort = chains if sample_n <= 0 or sample_n >= len(chains) else rng.sample(chains, sample_n)

    per_span: dict[float, list[int]] = {s: [0, 0] for s in SPAN_LADDER}   # [agree, truncated]
    floor_rows: list[tuple[float, bool]] = []                            # (net/gross, agreed)
    floor = 0.05

    for spot, ts, contracts in cohort:
        now = _et_now(ts)
        parsed = [p for p in (_contract_inputs(c, now=now) for c in contracts
                              if isinstance(c, dict)) if p]
        if len(parsed) < MIN_CONTRACTS_FOR_A_READ:
            continue
        ref, ref_gross = at_spot_gamma(parsed, spot)
        if ref is None or not ref_gross or ref == 0:
            continue
        delivered = max(abs(strike / spot - 1.0) for strike, *_ in parsed)

        for span in SPAN_LADDER:
            if delivered <= span:               # not truncated -> agrees by construction -> excluded
                continue
            window = [p for p in parsed if abs(p[0] / spot - 1.0) <= span]
            if len(window) < MIN_CONTRACTS_FOR_A_READ:
                continue
            val, _ = at_spot_gamma(window, spot)
            if val is None or val == 0:
                continue
            agreed = (val > 0) == (ref > 0)
            per_span[span][1] += 1
            if agreed:
                per_span[span][0] += 1
            if span == floor:
                floor_rows.append((abs(ref) / ref_gross, agreed))

    return {
        "cohort_total": len(chains),
        "sampled": len(cohort),
        "seed": seed,
        "by_span": {
            f"{s:.2f}": {
                "n_truncated": per_span[s][1],
                "n_sign_agrees": per_span[s][0],
                "rate": (per_span[s][0] / per_span[s][1]) if per_span[s][1] else None,
                "ci95": wilson(per_span[s][0], per_span[s][1]) if per_span[s][1] else None,
            }
            for s in SPAN_LADDER
        },
        "at_floor_by_net_gross": _bucket_report(floor_rows),
    }


def _bucket_report(rows: list[tuple[float, bool]]) -> dict:
    out = {}
    for lo, hi in NET_GROSS_BUCKETS:
        sel = [agreed for ratio, agreed in rows if lo <= ratio < hi]
        k, n = sum(1 for a in sel if a), len(sel)
        out[f"{lo:.2f}-{min(hi, 1.0):.2f}"] = {
            "n": n, "n_sign_agrees": k,
            "rate": (k / n) if n else None,
            "ci95": wilson(k, n) if n else None,
        }
    return out


def main(argv: list[str] | None = None) -> int:
    import json

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("db_path", nargs="?", default=None)
    ap.add_argument("--sample", type=int, default=260,
                    help="chains to sample (0 = whole cohort; the full run is slow)")
    ap.add_argument("--seed", type=int, default=12345)
    args = ap.parse_args(argv)

    db = args.db_path
    if not db:
        from db import DB_PATH
        db = DB_PATH
    rep = run(db, args.sample, args.seed)
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
