"""RC-256 — time the THREE cold-start stages separately, because the operator waits twice.

WHAT THE OPERATOR REPORTED: "15-20s hesitation before logs, then long wait before app".
Two distinct waits is itself the clue — a single slow import produces ONE. The evidence to
date could not rank them: RC-247 timed `import server` only, and the PM's audit timed
launch-to-ready as one number, so neither could say which wait the operator is sitting
through or whether they are even the same phenomenon.

WHAT THIS MEASURES, per round, in a FRESH process each time:

    (a) import_s      bare `import server` in a new interpreter
    (b) accept_s      spawn -> TCP accept on the bound port
    (c) http200_s     spawn -> first HTTP 200 from /api/health

Each round is preceded by a bare-interpreter baseline (`python -c pass`) so interpreter
start-up is subtracted from (a) rather than silently counted as import cost.

(b) and (c) are measured in the SAME spawn, so `http200_s - accept_s` is the app-readiness
tail — the second wait — and is not an artefact of comparing two different launches.

DOES NOT TOUCH THE SPLASH OR start_ed_console.bat. The operator froze that output; this
harness spawns uvicorn directly on its own port and never writes to the console launcher.

    .venv/Scripts/python.exe tools/measure_cold_start_stages_v1.py --rounds 7 --port 8791
"""

from __future__ import annotations

import argparse
import json
import socket
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = str(REPO / ".venv" / "Scripts" / "python.exe")


def _baseline_interpreter_s() -> float:
    """Bare interpreter start, so it is subtracted from import rather than blamed on it."""
    t0 = time.perf_counter()
    subprocess.run([PY, "-c", "pass"], cwd=REPO, capture_output=True, check=False)
    return time.perf_counter() - t0


def _import_server_s() -> float:
    t0 = time.perf_counter()
    p = subprocess.run([PY, "-c", "import server"], cwd=REPO,
                       capture_output=True, text=True, errors="replace", check=False)
    dt = time.perf_counter() - t0
    if p.returncode != 0:
        raise RuntimeError(f"`import server` failed: {(p.stderr or '')[-400:]}")
    return dt


def _port_is_free(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0


def _spawn_and_time(port: int, timeout_s: float) -> tuple[float | None, float | None, str]:
    """Return (seconds_to_tcp_accept, seconds_to_first_http_200, note) for ONE spawn.

    127.0.0.1 deliberately, never `localhost`: the operator measured ~2.05s burned on the
    ::1 attempt before the IPv4 fallback, which would land entirely inside this measurement.
    """
    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning"],
        cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    t0 = time.perf_counter()
    accept_s: float | None = None
    http_s: float | None = None
    note = "ok"
    try:
        while time.perf_counter() - t0 < timeout_s:
            if proc.poll() is not None:
                return None, None, f"process exited rc={proc.returncode}"
            if accept_s is None:
                with socket.socket() as s:
                    s.settimeout(0.25)
                    if s.connect_ex(("127.0.0.1", port)) == 0:
                        accept_s = time.perf_counter() - t0
            else:
                try:
                    with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/api/health", timeout=2.0) as r:
                        if r.status == 200:
                            http_s = time.perf_counter() - t0
                            break
                except (urllib.error.URLError, OSError, TimeoutError):
                    pass
            time.sleep(0.05)
        else:
            note = f"timeout after {timeout_s}s"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=20)
    return accept_s, http_s, note


def _stats(vals: list[float]) -> dict[str, float] | None:
    clean = [v for v in vals if v is not None]
    if not clean:
        return None
    return {"n": len(clean), "min": round(min(clean), 3),
            "median": round(statistics.median(clean), 3), "max": round(max(clean), 3)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rounds", type=int, default=7)
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if not _port_is_free(a.port):
        print(f"port {a.port} is already in use — pick another with --port", file=sys.stderr)
        return 2

    rounds = []
    for i in range(a.rounds):
        base = _baseline_interpreter_s()
        imp = _import_server_s()
        accept_s, http_s, note = _spawn_and_time(a.port, a.timeout)
        rounds.append({
            "round": i + 1,
            "baseline_interpreter_s": round(base, 3),
            "import_s": round(imp, 3),
            "import_minus_baseline_s": round(imp - base, 3),
            "accept_s": None if accept_s is None else round(accept_s, 3),
            "http200_s": None if http_s is None else round(http_s, 3),
            "readiness_tail_s": (None if (accept_s is None or http_s is None)
                                 else round(http_s - accept_s, 3)),
            "note": note,
        })
        if not a.json:
            r = rounds[-1]
            print(f"  round {r['round']}: import={r['import_minus_baseline_s']}s "
                  f"accept={r['accept_s']}s http200={r['http200_s']}s "
                  f"tail={r['readiness_tail_s']}s  [{r['note']}]", flush=True)
        time.sleep(1.0)   # let the port fully release between rounds

    summary = {
        "rounds": a.rounds,
        "import_minus_baseline_s": _stats([r["import_minus_baseline_s"] for r in rounds]),
        "accept_s": _stats([r["accept_s"] for r in rounds]),
        "http200_s": _stats([r["http200_s"] for r in rounds]),
        "readiness_tail_s": _stats([r["readiness_tail_s"] for r in rounds]),
    }
    out = {"summary": summary, "rounds": rounds}
    dest = REPO / "reports" / "cold_start_stage_timing_v1.json"
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")

    if a.json:
        print(json.dumps(out, indent=2))
        return 0

    print(f"\nRC-256 COLD START, {a.rounds} rounds (seconds)")
    print(f"{'stage':<34}{'min':>9}{'median':>9}{'max':>9}")
    for key, label in (("import_minus_baseline_s", "(a) import server (net of interp)"),
                       ("accept_s", "(b) spawn -> TCP accept"),
                       ("http200_s", "(c) spawn -> first HTTP 200"),
                       ("readiness_tail_s", "    (c)-(b) app readiness tail")):
        s = summary[key]
        print(f"{label:<34}" + ("       —        —        —" if not s
              else f"{s['min']:>9}{s['median']:>9}{s['max']:>9}"))
    print(f"\nwritten: {dest.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
