"""Measure whether options persistence can stall the SOLE Schwab stream. Evidence, not opinion.

THE QUESTION THIS ANSWERS. order_flow_streaming owns one StreamClient and one asyncio message
loop, and its service handlers run INLINE on that loop. Time spent inside a handler is time the
loop is not reading the socket, so a slow options write becomes an equity/book stall. Before any
meaningful contract volume is enabled, that has to be a measured quantity.

WHAT IS MEASURED, and why each one is here:
  * offer() LATENCY DISTRIBUTION (p50/p95/p99/max), not just a mean. The mean is the number that
    hides the problem: a 5 us mean with a 28 ms tail still stalls the stream, and the tail is the
    stall. The first version of the ingest module measured a 28,152 us worst case, traced to the
    writer holding the stats lock across a whole batch; that is exactly the defect a mean would
    have concealed.
  * SUSTAINED behaviour at a REALISTIC frame rate, derived from the committed probe (91 frames in
    90 s for one symbol) rather than from an unbounded burst. A burst that offers 20x faster than
    any real stream proves the queue absorbs bursts; it does not describe production.
  * DELIBERATE OVERLOAD, to prove the bound is real: a queue small enough to overflow must drop,
    count every drop, and keep the producer fast. An unproven bound is not a bound.
  * WRITER FAILURE ISOLATION: a writer that cannot write must not take the stream down and must
    not silently look healthy.
  * STORAGE COST per frame and WAL growth, so the retention decision is made on numbers.

NOTHING HERE INTERPRETS MARKET DATA. It moves real captured frames through the real path and
reports timings and byte counts.
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from calibration.options_stream_ingest import OptionsFrameIngest  # noqa: E402

#: Measured from the committed capture: 91 LEVELONE_OPTIONS frames in 90 s for ONE contract.
#: This is the per-contract update rate the arithmetic below scales by contract count.
PROBE_FRAMES_PER_CONTRACT_PER_S = 91.0 / 90.0


def load_real_frames() -> list[tuple[str, dict]]:
    """Real decoded vendor frames from the committed probe. Never synthetic."""
    out: list[tuple[str, dict]] = []
    for svc in ("LEVELONE_OPTIONS", "OPTIONS_BOOK"):
        pat = str(REPO / "reports" / "of_capability_probe" / "options_20260820T1354Z" /
                  "frames" / f"{svc}_*_decoded.json")
        for p in sorted(glob.glob(pat)):
            try:
                out.append((svc, json.loads(Path(p).read_text(encoding="utf-8"))))
            except (OSError, ValueError):
                continue
    return out


def _pct(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def _stamp(frame: dict, vendor_lag_ms: int = 40) -> dict:
    """Copy a real frame and give it a vendor clock consistent with 'sent just now'.

    Replaying the capture's own Aug-20 timestamps against today's clock reports ~522,134,814 ms
    of ingest lag, which measures the age of the fixture, not the pipeline. The lag statistic is
    only meaningful when the vendor stamp is contemporaneous, so it is set here.
    """
    g = copy.deepcopy(frame)
    g["timestamp"] = int(time.time() * 1000.0) - int(vendor_lag_ms)
    return g


def run_case(name: str, frames: list[tuple[str, dict]], *, max_queue: int, batch_max: int,
             target_rate_per_s: float | None, db_path: str) -> dict:
    ing = OptionsFrameIngest(db_path, max_queue=max_queue, batch_max=batch_max)
    ing.start()
    lat_us: list[float] = []
    t0 = time.perf_counter()
    interval = (1.0 / target_rate_per_s) if target_rate_per_s else 0.0
    next_at = t0
    for svc, fr in frames:
        if interval:
            now = time.perf_counter()
            if next_at > now:
                time.sleep(next_at - now)
            next_at += interval
        g = _stamp(fr)
        a = time.perf_counter_ns()
        ing.offer(svc, g)
        lat_us.append((time.perf_counter_ns() - a) / 1000.0)
    offer_wall = time.perf_counter() - t0
    final = ing.stop(timeout=180.0)
    total_wall = time.perf_counter() - t0

    size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    wal = db_path + "-wal"
    wal_size = os.path.getsize(wal) if os.path.exists(wal) else 0
    return {
        "case": name,
        "frames": len(frames),
        "max_queue": max_queue,
        "target_rate_per_s": target_rate_per_s,
        "offered": final["offered"], "written": final["written"], "dropped": final["dropped"],
        "write_errors": final["write_errors"], "batches": final["batches"],
        "max_queue_depth": final["max_queue_depth"],
        "max_ingest_lag_ms": final["max_ingest_lag_ms"],
        "clean_shutdown": final.get("clean_shutdown"),
        "accounting_complete": final["offered"] == final["written"] + final["dropped"],
        "offer_us_p50": round(_pct(lat_us, 0.50), 2),
        "offer_us_p95": round(_pct(lat_us, 0.95), 2),
        "offer_us_p99": round(_pct(lat_us, 0.99), 2),
        "offer_us_max": round(max(lat_us) if lat_us else 0.0, 2),
        "offer_us_mean": round(statistics.fmean(lat_us) if lat_us else 0.0, 2),
        "offer_wall_s": round(offer_wall, 3),
        "total_wall_s": round(total_wall, 3),
        "write_rate_per_s": round(final["written"] / total_wall, 1) if total_wall else None,
        "db_bytes": size,
        "bytes_per_frame": round(size / max(1, final["written"]), 1),
        "wal_bytes_at_close": wal_size,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure options ingest capacity and stream safety")
    ap.add_argument("--frames", type=int, default=20000, help="frames per burst case")
    ap.add_argument("--contracts", type=int, default=240,
                    help="streamed contract count to size the realistic rate from")
    ap.add_argument("--sustain-seconds", type=float, default=20.0)
    ap.add_argument("--json-out", type=str, default=None)
    args = ap.parse_args()

    base = load_real_frames()
    if not base:
        print("FAIL: no real captured frames found — refusing to measure on synthetic data")
        return 2
    print(f"real base frames: {len(base)}")

    tmp = tempfile.mkdtemp(prefix="opt_ingest_cap_")
    results = []

    # 1. BURST — queue large enough to absorb everything. Establishes raw write throughput.
    burst = [base[i % len(base)] for i in range(args.frames)]
    results.append(run_case("burst_absorbed", burst, max_queue=args.frames + 1000,
                            batch_max=500, target_rate_per_s=None,
                            db_path=os.path.join(tmp, "burst.db")))

    # 2. REALISTIC SUSTAINED — the rate production would actually see.
    rate = PROBE_FRAMES_PER_CONTRACT_PER_S * args.contracts
    n_sus = max(1, int(rate * args.sustain_seconds))
    sus = [base[i % len(base)] for i in range(n_sus)]
    results.append(run_case(f"sustained_{int(rate)}_per_s", sus, max_queue=20000, batch_max=500,
                            target_rate_per_s=rate, db_path=os.path.join(tmp, "sustained.db")))

    # 3. DELIBERATE OVERFLOW — a bound nobody has seen enforced is not a bound.
    results.append(run_case("overflow_bounded", burst, max_queue=500, batch_max=500,
                            target_rate_per_s=None,
                            db_path=os.path.join(tmp, "overflow.db")))

    # 4. WRITER CANNOT WRITE — failure must be isolated, counted, and non-fatal.
    bad_db = os.path.join(tmp, "no_such_dir", "unwritable.db")
    results.append(run_case("writer_open_fails", burst[:2000], max_queue=1000, batch_max=500,
                            target_rate_per_s=None, db_path=bad_db))

    print(f"\n{'case':<26}{'offered':>8}{'written':>9}{'dropped':>9}{'p50us':>8}"
          f"{'p99us':>9}{'maxus':>10}{'wr/s':>9}  acct")
    for r in results:
        print(f"{r['case']:<26}{r['offered']:>8}{r['written']:>9}{r['dropped']:>9}"
              f"{r['offer_us_p50']:>8}{r['offer_us_p99']:>9}{r['offer_us_max']:>10}"
              f"{str(r['write_rate_per_s']):>9}  {r['accounting_complete']}")

    sus_r = results[1]
    burst_r = results[0]
    over_r = results[2]
    fail_r = results[3]

    print("\n--- VERDICTS (each tied to the case above) ---")
    headroom = (burst_r["write_rate_per_s"] or 0) / max(1e-9, rate)
    print(f"realistic rate for {args.contracts} contracts : {rate:.0f} frames/s "
          f"(probe: {PROBE_FRAMES_PER_CONTRACT_PER_S:.3f}/contract/s)")
    print(f"measured write throughput                  : {burst_r['write_rate_per_s']}/s "
          f"-> {headroom:.1f}x headroom")
    print(f"sustained: dropped={sus_r['dropped']} maxq={sus_r['max_queue_depth']} "
          f"p99_offer={sus_r['offer_us_p99']}us max_offer={sus_r['offer_us_max']}us")
    print(f"bounded overflow: queue=500 -> dropped={over_r['dropped']}, "
          f"accounting_complete={over_r['accounting_complete']}, "
          f"max_offer={over_r['offer_us_max']}us")
    print(f"writer-open failure: written={fail_r['written']} errors={fail_r['write_errors']} "
          f"dropped={fail_r['dropped']} accounting_complete={fail_r['accounting_complete']}")
    print(f"storage: {burst_r['bytes_per_frame']} bytes/frame "
          f"-> {rate * 3600 * burst_r['bytes_per_frame'] / 1e9:.2f} GB per RTH hour at "
          f"{args.contracts} contracts")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=1), encoding="utf-8")
        print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
