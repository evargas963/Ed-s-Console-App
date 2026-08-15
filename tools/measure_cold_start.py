#!/usr/bin/env python3
"""RC-256: quiet-host cold-start harness — import vs bind vs health, timed SEPARATELY.

The operator reports two distinct waits on launch: "15-20s hesitation before logs, then a
long wait before app". Two waits means two stages, and every figure collected so far measured
one lump: RC-247 timed `import server` alone, the PM's audit timed launch-before-listen. Neither
separated BIND from LIFESPAN, and both were taken while the live console competed for CPU and
disk — where ten runs of one identical command spanned 6.01-18.64s.

So this measures three stages independently, repeats them, and reports min/median/max:

  import   fresh process, `import server` only — no uvicorn, no app construction
  bind     spawn -> first successful TCP connect on the port (the socket accepting)
  health   spawn -> first HTTP 200 from /api/health (the app actually answering)

`bind` and `health` are measured from the SAME spawned process, so health-minus-bind is the
cost paid after the socket opens. That difference is the whole question: work sitting before
the bind is work the operator waits through with no log output at all.

Each round runs a bare-interpreter control first, because on this host the baseline itself
drifted 2.538 -> 0.731 -> 0.312s. A stage time is only meaningful next to it.

REFUSES TO RUN if anything is already listening on the target port. Measuring while the
console serves is precisely what produced every unusable number so far, and a harness that
silently measures the wrong thing is worse than no harness.

Read-only: it starts and stops its own server on a NON-default port and never edits code.

Usage:
  .venv/Scripts/python.exe tools/measure_cold_start.py                 # 7 rounds, port 8899
  .venv/Scripts/python.exe tools/measure_cold_start.py -n 3 --port 8901
  .venv/Scripts/python.exe tools/measure_cold_start.py --json-only
"""
from __future__ import annotations

import argparse
import json
import socket
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_PORT = 8899
DEFAULT_ROUNDS = 7
#: Past this, a stage is assumed hung rather than slow — a harness that waits forever on a
#: broken boot reads exactly like a harness that is still measuring.
STAGE_TIMEOUT_S = 180.0
HOST = "127.0.0.1"  # never "localhost": ::1 resolution burns ~2s per probe on this host


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((HOST, port)) != 0


def _tcp_accepts(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((HOST, port)) == 0


def _health_ok(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _time_baseline() -> float:
    """Bare interpreter start. The control every other number is read against."""
    t = time.perf_counter()
    subprocess.run([sys.executable, "-c", "pass"], capture_output=True)
    return time.perf_counter() - t


def _time_import() -> float:
    """`import server` in a FRESH process — module import only, no server."""
    t = time.perf_counter()
    subprocess.run([sys.executable, "-c", "import server"], cwd=str(REPO), capture_output=True)
    return time.perf_counter() - t


def _time_bind_and_health(port: int) -> tuple[float | None, float | None, str]:
    """Spawn the real server; return (seconds to TCP accept, seconds to health 200, note).

    Both are measured from the same spawn, so health - bind is the post-bind cost.
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", HOST, "--port", str(port),
         "--log-level", "warning"],
        cwd=str(REPO), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    t0 = time.perf_counter()
    bind_s: float | None = None
    health_s: float | None = None
    note = "ok"
    try:
        while time.perf_counter() - t0 < STAGE_TIMEOUT_S:
            if proc.poll() is not None:
                return None, None, f"server exited early rc={proc.returncode}"
            if bind_s is None and _tcp_accepts(port):
                bind_s = time.perf_counter() - t0
            if bind_s is not None and _health_ok(port):
                health_s = time.perf_counter() - t0
                break
            time.sleep(0.05)
        if health_s is None:
            note = f"health never answered within {STAGE_TIMEOUT_S:.0f}s"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=20)
    return bind_s, health_s, note


def _spread(values: list[float]) -> dict:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    return {
        "n": len(s),
        "min": round(s[0], 2),
        "median": round(statistics.median(s), 2),
        "max": round(s[-1], 2),
        "spread": round(s[-1] - s[0], 2),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RC-256 quiet-host cold-start harness")
    ap.add_argument("-n", "--rounds", type=int, default=DEFAULT_ROUNDS)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--allow-busy-host", action="store_true",
                    help="measure anyway with something already listening (results are noise)")
    args = ap.parse_args(argv)

    if not _port_is_free(args.port) and not args.allow_busy_host:
        print(f"REFUSING: something is already listening on {HOST}:{args.port}. "
              f"Cold-start numbers taken while a server runs are unusable — that is how the "
              f"6.61s / 10.5s disagreement happened. Stop it, or pass --port <free port>.",
              file=sys.stderr)
        return 2

    rounds: list[dict] = []
    for i in range(args.rounds):
        base = _time_baseline()
        imp = _time_import()
        bind_s, health_s, note = _time_bind_and_health(args.port)
        rounds.append({"round": i + 1, "baseline": base, "import": imp,
                       "bind": bind_s, "health": health_s, "note": note})
        if not args.json_only:
            b = f"{bind_s:.2f}" if bind_s is not None else "----"
            h = f"{health_s:.2f}" if health_s is not None else "----"
            print(f"  round {i+1}/{args.rounds}: baseline {base:5.2f}  import {imp:6.2f}  "
                  f"bind {b:>6}  health {h:>6}  {note if note != 'ok' else ''}")

    report = {
        "rounds": args.rounds,
        "port": args.port,
        "baseline": _spread([r["baseline"] for r in rounds]),
        "import": _spread([r["import"] for r in rounds]),
        "bind": _spread([r["bind"] for r in rounds]),
        "health": _spread([r["health"] for r in rounds]),
        "post_bind": _spread([r["health"] - r["bind"] for r in rounds
                              if r["health"] is not None and r["bind"] is not None]),
        "detail": rounds,
    }
    if args.json_only:
        print(json.dumps(report, indent=2))
        return 0

    print("\nSTAGE            n    min  median     max  spread")
    for stage in ("baseline", "import", "bind", "health", "post_bind"):
        s = report[stage]
        if not s.get("n"):
            print(f"  {stage:<13} 0    (no successful runs)")
            continue
        print(f"  {stage:<13} {s['n']:<3} {s['min']:6.2f}  {s['median']:6.2f}  "
              f"{s['max']:6.2f}  {s['spread']:6.2f}")
    print("\n  post_bind = health - bind: cost paid AFTER the socket accepts.")
    print("  A large bind with a small post_bind means work is blocking the listen —")
    print("  that is the silent wait, and deferring it past bind is the smallest fix.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
