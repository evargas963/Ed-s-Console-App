"""Phase 2A live acceptance: sample the two surfaces REPEATEDLY and compare identities.

WHY REPEATEDLY, AND WHY NOT ONE CURL
    The measured defect was intermittent. /api/levels and /api/liquidity-snapshot ran the
    same engine helpers over DIFFERENT bar inputs, so they agreed whenever the two inputs
    happened to coincide and diverged whenever they did not — overnight 773.3975/773.3975
    against 773.40/772.55 at one instant, prior-day value area disagreeing on and off. A
    single sample of an intermittent defect is a coin flip reported as a proof.

WHAT COUNTS AS A PASS
    For every canonical Phase 2A id present on both surfaces at the same generation, the
    two prices are EXACTLY equal (not "close"), or the id is honestly absent from both.
    A generation that advances between the two fetches of one round is not a failure — it
    is a new market input — so each round records the generation it compared under and a
    round is only judged when the two fetches share one.

Usage:  python tools/phase2a_live_sample_v1.py [--ticker SPY] [--rounds 8] [--base URL]
Exit 0 = agreement on every judged round; 1 = a real disagreement; 2 = nothing judgeable.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request

#: (canonical id on /api/levels, tag on /api/liquidity-snapshot raw_levels_used).
#: The liquidity snapshot publishes the same ids since Phase 2A; the map stays explicit so
#: a rename on one side shows up as "missing", never as a silently skipped comparison.
PHASE2A_IDS: tuple[str, ...] = (
    "PDH", "PDL", "PDC", "PD_POC", "PD_VAH", "PD_VAL",
    "OVERNIGHT_HIGH", "OVERNIGHT_LOW",
    "ORB_HIGH", "ORB_LOW", "ORB_MID",
    "VWAP", "VWAP_P1", "VWAP_M1", "VWAP_P2", "VWAP_M2",
    "TODAY_POC", "TODAY_VAH", "TODAY_VAL",
)


def _get(url: str, timeout: float = 15.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - local console
        return json.loads(r.read().decode("utf-8"))


def _levels_side(payload: dict) -> tuple[dict[str, float], object]:
    out: dict[str, float] = {}
    for row in payload.get("levels") or []:
        lid = str(row.get("id") or "")
        if lid in PHASE2A_IDS and isinstance(row.get("price"), (int, float)):
            out[lid] = float(row["price"])
    return out, payload.get("generation")


def _liquidity_side(payload: dict) -> tuple[dict[str, float], object]:
    out: dict[str, float] = {}
    for row in payload.get("raw_levels_used") or []:
        tag = str(row.get("tag") or "")
        if tag in PHASE2A_IDS and isinstance(row.get("value"), (int, float)):
            out[tag] = float(row["value"])
    return out, payload.get("level_generation")


def sample_once(base: str, ticker: str) -> dict:
    lv = _get(f"{base}/api/levels?ticker={ticker}")
    lq = _get(f"{base}/api/liquidity-snapshot?ticker={ticker}&snapshot=live")
    a, gen_a = _levels_side(lv)
    b, gen_b = _liquidity_side(lq)
    shared = sorted(set(a) & set(b))
    disagreements = [(k, a[k], b[k]) for k in shared if a[k] != b[k]]
    return {
        "generation_levels": gen_a,
        "generation_liquidity": gen_b,
        "comparable": gen_a is not None and gen_a == gen_b,
        "ids_compared": shared,
        "only_levels": sorted(set(a) - set(b)),
        "only_liquidity": sorted(set(b) - set(a)),
        "disagreements": disagreements,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="SPY")
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--sleep", type=float, default=1.5)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args(argv)

    judged = 0
    failed = 0
    for i in range(1, args.rounds + 1):
        try:
            r = sample_once(args.base, args.ticker)
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"round {i}: FETCH FAILED — {e}")
            time.sleep(args.sleep)
            continue
        state = "judged" if r["comparable"] else "SKIPPED (generations differ or absent)"
        print(f"round {i}: {state} gen levels={r['generation_levels']} "
              f"liquidity={r['generation_liquidity']} "
              f"compared={len(r['ids_compared'])} "
              f"only_levels={r['only_levels']} only_liquidity={r['only_liquidity']}")
        if r["comparable"]:
            judged += 1
            for lid, x, y in r["disagreements"]:
                failed += 1
                print(f"    DISAGREE {lid}: /api/levels {x!r} vs /api/liquidity-snapshot {y!r}")
        time.sleep(args.sleep)

    if judged == 0:
        print("RESULT: NOT JUDGEABLE — no round shared a generation. Either the server "
              "predates the Phase 2A change (no generation on the payload) or no bars "
              "exist for this ticker/session.")
        return 2
    if failed:
        print(f"RESULT: FAIL — {failed} disagreement(s) across {judged} judged round(s).")
        return 1
    print(f"RESULT: PASS — {judged} judged round(s), every shared id agreed exactly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
