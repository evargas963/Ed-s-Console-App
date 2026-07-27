"""Derive the gamma-flip span requirement from DATA instead of asserting it (RC-62).

WHY: `math_levels.GAMMA_FLIP_MIN_SPAN_PCT = 0.05` is a bare magic number — its only
justification is a comment restating it. It decides (a) how many strikes every live chain fetch
requests and (b) whether the operator is told the flip is TRUSTED or LOW_CONFIDENCE_NARROW_CHAIN.
A number with that much authority must be measured.

METHOD (convergence, the standard way to size a numerical window): for each stored WIDE chain,
compute the flip on the FULL delivered strike set (the reference), then recompute it using only
strikes within +/-X% of spot for a ladder of X. The flip error vs the reference falls as X grows
and flattens once the excluded strikes carry no material gamma. The smallest X at which the error
is tolerably small AND stops improving is the justified span requirement.

Honest limits, stated: the reference is the widest chain WE HAVE (Schwab caps strikeCount, so it
is not the true full chain) — this measures convergence toward our widest available view, which
BOUNDS the requirement from below. Trading days only (RC-54), multi-day contracts with real OI.

Usage:  python tools/study_flip_span_convergence_v1.py [db_path]
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

SPAN_LADDER = (0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.15)
#: "Materially identical" for a level the operator trades off. 0.05% of spot is ~$0.37 on a
#: $740 SPY — well inside one strike increment, so a difference this small cannot change which
#: strike the flip sits between.
TOLERANCE_PCT_OF_SPOT = 0.05


def flip_within_span(contracts: list[dict], spot: float, now, span: float | None) -> float | None:
    """Flip computed using only strikes within +/-span of spot (None = all strikes)."""
    from math_levels import compute_gamma_profile, gamma_flip_from_profile
    if span is not None:
        contracts = [c for c in contracts
                     if abs(float(c["strikePrice"]) / spot - 1.0) <= span]
    if len(contracts) < 6:
        return None
    return gamma_flip_from_profile(compute_gamma_profile(contracts, spot, now=now), spot)


def run(db_path: str) -> dict:
    from tools.flip_iv_sensitivity_v1 import _et_now, load_wide_chains

    chains = load_wide_chains(db_path)          # trading days only, RC-54
    errs: dict[float, list[float]] = {s: [] for s in SPAN_LADDER}
    n_ref = 0
    n_complete = 0
    for spot, ts, cts in chains:
        now = _et_now(ts)
        ref = flip_within_span(cts, spot, now, None)      # full delivered chain
        if ref is None:
            continue
        n_ref += 1
        # FIXED SUBSET (methodology): a chain counts only if it yields a flip at EVERY ladder
        # point. Otherwise the sample GROWS with span — narrow windows often have no crossing —
        # and each row would describe a different, self-selected set of chains, so the medians
        # would not be comparable. Convergence must be measured on one constant cohort.
        per_span = {s: flip_within_span(cts, spot, now, s) for s in SPAN_LADDER}
        if any(v is None for v in per_span.values()):
            continue
        n_complete += 1
        for span, f in per_span.items():
            errs[span].append(abs(f - ref) / spot * 100.0)

    rows = []
    for span in SPAN_LADDER:
        v = sorted(errs[span])
        if not v:
            rows.append({"span_pct": span * 100, "n": 0})
            continue
        rows.append({
            "span_pct": round(span * 100, 1),
            "n": len(v),
            "median_err_pct_of_spot": round(statistics.median(v), 4),
            "p90_err_pct_of_spot": round(v[int(len(v) * 0.9) - 1] if len(v) > 1 else v[0], 4),
            "max_err_pct_of_spot": round(max(v), 4),
            "share_within_tolerance": round(
                sum(1 for x in v if x <= TOLERANCE_PCT_OF_SPOT) / len(v) * 100, 1),
        })

    # The justified span: smallest ladder point where >=95% of chains are within tolerance.
    justified = next((r["span_pct"] for r in rows
                      if r.get("share_within_tolerance", 0) >= 95.0), None)
    return {
        "db_path": db_path,
        "chains_with_reference_flip": n_ref,
        "chains_in_fixed_cohort": n_complete,
        "cohort_note": "every ladder row describes the SAME chains; a chain lacking a flip at any "
                       "ladder point is excluded so the medians are comparable",
        "tolerance_pct_of_spot": TOLERANCE_PCT_OF_SPOT,
        "reference": "flip on the FULL delivered strike set of each stored wide chain",
        "ladder": rows,
        "justified_span_pct": justified,
        "current_constant_pct": 5.0,
    }


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    print(json.dumps(run(args[0] if args else os.path.join("data", "ed_console.db")), indent=2))
