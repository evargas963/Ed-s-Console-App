"""Does Schwab's strikeCount change the LADDER, or only how much of it we see?

THE QUESTION. The console sizes every chain fetch with strikeCount=N, chosen by
server.resolve_chain_strike_count from an increment learned by math_levels.infer_strike_increment
-- which reads that increment off a chain we already fetched. If a narrow request returns a
COARSER ladder than the instrument really has, the learned increment is coarse, the next request
is sized for coarse spacing, and the console never discovers the finer strikes. Self-confirming,
and invisible from inside.

That is a question about the VENDOR's behaviour, so it cannot be answered by reading our code. This
fetches the SAME ticker at several widths and compares the ladders that come back.

WHAT WOULD PROVE WHAT:
  * If the strike SET at a small N is a SUBSET of the set at a large N, and the minimum adjacent
    gap is the same at both, then strikeCount only truncates the wings. Our narrow fetches lose
    SPAN but not RESOLUTION, and the learned increment is honest.
  * If a larger N reveals strikes BETWEEN strikes we already had -- a smaller minimum gap -- then
    strikeCount changes the sampling, our narrow fetches were coarsened by the request itself, and
    the learned-increment loop is measuring its own request rather than the instrument.

Read-only: it fetches and prints. It writes nothing, changes no state, and touches neither the
streamer nor the model stack.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def ladder(contracts: list[dict]) -> dict:
    strikes = sorted({float(c["strikePrice"]) for c in contracts
                      if isinstance(c, dict) and c.get("strikePrice") is not None})
    gaps = [round(b - a, 4) for a, b in zip(strikes, strikes[1:], strict=False) if b > a]
    return {
        "n_contracts": len(contracts),
        "n_strikes": len(strikes),
        "strikes": strikes,
        "min": strikes[0] if strikes else None,
        "max": strikes[-1] if strikes else None,
        "min_gap": min(gaps) if gaps else None,
        "max_gap": max(gaps) if gaps else None,
        "gap_hist": collections.Counter(gaps).most_common(6),
        "n_expiries": len({str(c.get("expirationDate"))[:10] for c in contracts
                           if isinstance(c, dict) and c.get("expirationDate")}),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe whether strikeCount changes the strike ladder")
    ap.add_argument("--tickers", default="TSLA,NVDA,SPY,AAPL")
    ap.add_argument("--counts", default="20,60,150")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    from schwab_client import safe_get_chain
    from server import get_client

    client = get_client()
    if client is None:
        print("FAIL: no Schwab client (auth unavailable) — cannot gather live evidence")
        return 2

    counts = [int(c) for c in args.counts.split(",") if c.strip()]
    out: dict[str, dict] = {}

    for tk in [t.strip().upper() for t in args.tickers.split(",") if t.strip()]:
        print(f"\n{'=' * 78}\n{tk}\n{'=' * 78}")
        per_count: dict[int, dict] = {}
        for n in counts:
            try:
                resp = safe_get_chain(client, tk, strike_count=n)
            except Exception as e:                      # noqa: BLE001
                print(f"  strikeCount={n:<4} ERROR {type(e).__name__}: {e}")
                continue
            if resp is None or getattr(resp, "status_code", None) != 200:
                print(f"  strikeCount={n:<4} vendor status "
                      f"{getattr(resp, 'status_code', None)}")
                continue
            body = resp.json()
            from server import flatten_chain_contracts
            contracts = flatten_chain_contracts(body)
            lad = ladder(contracts)
            lad["underlyingPrice"] = body.get("underlyingPrice")
            lad["isChainTruncated"] = body.get("isChainTruncated")
            lad["numberOfContracts"] = body.get("numberOfContracts")
            per_count[n] = lad
            print(f"  strikeCount={n:<4} contracts={lad['n_contracts']:<6} "
                  f"strikes={lad['n_strikes']:<5} range={lad['min']}..{lad['max']} "
                  f"min_gap={lad['min_gap']} expiries={lad['n_expiries']} "
                  f"truncated={lad['isChainTruncated']}")
            print(f"                  gaps: {lad['gap_hist']}")

        # THE COMPARISON that answers the question.
        if len(per_count) >= 2:
            ns = sorted(per_count)
            small, large = per_count[ns[0]], per_count[ns[-1]]
            s_set, l_set = set(small["strikes"]), set(large["strikes"])
            only_small = sorted(s_set - l_set)
            new_between = [k for k in sorted(l_set - s_set)
                           if small["min"] is not None and small["min"] < k < small["max"]]
            print(f"\n  --- strikeCount {ns[0]} vs {ns[-1]} ---")
            print(f"  small set is a subset of large set : {s_set <= l_set}")
            print(f"  strikes only in the SMALL set      : {only_small}")
            print(f"  NEW strikes INSIDE the small range : {len(new_between)} {new_between[:12]}")
            print(f"  min gap  small={small['min_gap']}  large={large['min_gap']}")
            if new_between or (large["min_gap"] or 9e9) < (small["min_gap"] or 9e9):
                print("  VERDICT: strikeCount CHANGES RESOLUTION — a narrow request returns a "
                      "COARSER ladder, so the learned increment measures our own request.")
            elif s_set <= l_set:
                print("  VERDICT: strikeCount only TRUNCATES THE WINGS — resolution preserved; "
                      "narrow fetches lose span, not strikes-between-strikes.")
            else:
                print("  VERDICT: ladders differ in a way neither hypothesis predicts — inspect.")
            out[tk] = {"per_count": {str(k): v for k, v in per_count.items()},
                       "small_subset_of_large": s_set <= l_set,
                       "new_strikes_inside_small_range": new_between,
                       "only_in_small": only_small}

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
        print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
