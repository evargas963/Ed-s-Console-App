"""Phase 2A acceptance against the CODE ON DISK, when the live process predates it.

WHY THIS EXISTS ALONGSIDE tools/phase2a_live_sample_v1.py
    The live sampler talks HTTP to whatever process is listening. When that process was
    started before the Phase 2A change it serves the old code, and its payload carries no
    `generation` at all, so every round is unjudgeable — an honest NOT JUDGEABLE, but not
    evidence about the fix. This harness calls the SAME two endpoint functions in-process
    from the current tree, over the SAME banked 1m bars the live console reads, and
    samples repeatedly for the same reason: the defect was intermittent, and one sample of
    an intermittent defect is a coin flip reported as a proof.

WHAT IT DOES NOT DO
    It does not open the console DB through EdDB. EdDB's constructor runs schema init and
    migrations, i.e. WRITES, and the live server is holding that 29 GB file open right now;
    a second process migrating it to satisfy a read is not an acceptable cost of a
    measurement. Only a read-only sqlite connection is used, via a stand-in that carries
    the canonical path and nothing else.

Usage:  python tools/phase2a_inprocess_sample_v1.py [--ticker SPY] [--rounds 6]
Exit 0 = every judged round agreed exactly; 1 = a disagreement; 2 = nothing judgeable.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
#: The console DB the live server reads. Named explicitly rather than resolved through
#: db.DB_PATH, because ED_AGENT_ROLE routes that to a per-agent side DB which holds none
#: of the banked bars — reading it would report "absent" for reasons that have nothing to
#: do with the code under test.
CONSOLE_DB = REPO / "data" / "ed_console.db"


class _ReadOnlyDBHandle:
    """Carries the canonical path. Deliberately has no write surface at all."""

    def __init__(self, path: Path) -> None:
        self.db_path = path


def _body(resp) -> dict:
    return json.loads(bytes(resp.body)) if hasattr(resp, "body") else resp


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="SPY")
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args(argv)

    if not CONSOLE_DB.is_file():
        print(f"NOT JUDGEABLE — {CONSOLE_DB} is absent; no banked bars to measure over.")
        return 2

    import server as srv

    from tools.phase2a_live_sample_v1 import _levels_side, _liquidity_side

    srv.get_db = lambda *a, **k: _ReadOnlyDBHandle(CONSOLE_DB)  # type: ignore[assignment]

    judged = 0
    failed = 0
    for i in range(1, args.rounds + 1):
        lv = _body(srv.get_levels(ticker=args.ticker))
        lq = _body(srv.get_liquidity_snapshot(
            ticker=args.ticker, date=None, snapshot="live", expiry=None, fusion=True))
        a, gen_a = _levels_side(lv)
        b, gen_b = _liquidity_side(lq)
        shared = sorted(set(a) & set(b))
        comparable = gen_a is not None and gen_a == gen_b
        print(f"round {i}: gen levels={gen_a} liquidity={gen_b} comparable={comparable} "
              f"bar_source={lv.get('bar_source')} ids_on_levels={len(a)} "
              f"ids_on_liquidity={len(b)} shared={len(shared)} "
              f"vwap_series_points={len(lv.get('vwap_series') or [])}")
        if not comparable:
            for d in lv.get("degraded") or []:
                print(f"    degraded: {d}")
            time.sleep(args.sleep)
            continue
        judged += 1
        dis = [(k, a[k], b[k]) for k in shared if a[k] != b[k]]
        for k, x, y in dis:
            failed += 1
            print(f"    DISAGREE {k}: /api/levels {x!r} vs /api/liquidity-snapshot {y!r}")
        if not dis:
            print(f"    all {len(shared)} shared ids agree EXACTLY: {shared}")
        only_a, only_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))
        if only_a or only_b:
            print(f"    only_levels={only_a} only_liquidity={only_b}")
        time.sleep(args.sleep)

    if judged == 0:
        print("RESULT: NOT JUDGEABLE — no round shared a generation.")
        return 2
    if failed:
        print(f"RESULT: FAIL — {failed} disagreement(s) across {judged} judged round(s).")
        return 1
    print(f"RESULT: PASS — {judged} judged round(s), every shared id agreed exactly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
