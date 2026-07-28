"""REPO EXPOSURE AUDIT — the whole state, including what is broken (RC-91).

OPERATOR MANDATE 2026-07-27: "a huge repo wide audit, that exposes everything."

WHY THIS EXISTS, AND WHY IT IS NOT ANOTHER GATE. This repo already has 39 institutional checks, a
faucet audit, a UI-render gate and a code-health panel. On 2026-07-27 every one of them reported
clean while the operator was looking at a frozen volume panel, walls swinging 11 points, two spot
prices on one screen, and a gate that could not accept a commit. The checks were not lying: each
answered its own narrow question correctly. Nothing answered "what is the state of this repo".

So this tool does not judge. It EXPOSES:

  * it prints counts, not verdicts, and never hides a number behind a PASS;
  * it separates MEASURED from UNMEASURABLE, because a check that could not run is a finding, not
    a pass (RC-57) — three instruments shipped silently inert on 2026-07-27 alone;
  * it reports the LIVE app when one is reachable, because every defect found that day was found
    by watching behaviour over time and none by reading code;
  * it lists what is OPEN and what CONTRADICTS ITSELF, including governance rows whose status
    field disagrees with their own text.

  python tools/repo_exposure_audit.py            # the full exposure
  python tools/repo_exposure_audit.py --json     # machine-readable
  python tools/repo_exposure_audit.py --brief    # section headlines only

Deliberately has NO --check mode and NO exit-code contract beyond 0/1-on-crash. The moment this
becomes something to pass, it becomes something to satisfy, and the reason it exists is that
everything else was already being satisfied.
"""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

BASE = "http://127.0.0.1:8000"


def _sh(*args: str) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, errors="ignore",
                           cwd=str(REPO), timeout=120)
        return (r.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def section_gate() -> dict:
    """Every institutional check, enforced and advisory, with its count. Import failure is a
    FINDING — a gate that cannot load protects nothing."""
    try:
        import tools.check_institutional_correctness as C
    except Exception as e:
        return {"unmeasurable": f"{type(e).__name__}: {e}"}
    enforced, advisory, broken = {}, {}, {}
    for name, fn, is_enforced in C.CHECKS:
        try:
            n = len(fn())
        except Exception as e:
            broken[name] = f"{type(e).__name__}: {e}"
            continue
        (enforced if is_enforced else advisory)[name] = n
    return {"enforced": enforced, "advisory": advisory, "checks_that_crashed": broken}


def section_governance() -> dict:
    """Open rows, overdue rows, and rows whose STATUS contradicts their own TEXT.

    That last class is the log doing to itself what RC-87 caught in prose: a row stamped OPEN
    whose fix cell begins 'CLOSED, no code change warranted' is a label disagreeing with its
    content, and the label is what every reader trusts."""
    log = REPO / "governance" / "root_cause_log.md"
    if not log.exists():
        return {"unmeasurable": "governance/root_cause_log.md missing"}
    import datetime
    today = datetime.date.today().isoformat()
    rows, open_rows, overdue, contradictory, unfinished = 0, [], [], [], []
    for line in log.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.startswith("| RC-"):
            continue
        c = [x.strip() for x in line.strip("|").split("|")]
        if len(c) < 7:
            continue
        rows += 1
        rc, status, due, fix = c[0], c[1], c[3], c[6]
        if status != "CLOSED":
            open_rows.append(f"{rc} [{status}] due {due}")
            if due and due < today:
                overdue.append(f"{rc} due {due}")
            for marker in ("IN PROGRESS", "VERIFICATION PENDING", "NOT FIXED", "PARTIALLY"):
                if marker in fix.upper():
                    unfinished.append(f"{rc}: {marker}")
                    break
        if status != "CLOSED" and re.match(r"\s*(CLOSED|REFUTED|RESOLVED)\b", fix, re.I):
            contradictory.append(f"{rc}: status={status} but fix cell opens {fix[:44]!r}")
    return {"rows_total": rows, "not_closed": len(open_rows), "open": open_rows,
            "overdue": overdue, "self_declared_unfinished": unfinished,
            "status_contradicts_text": contradictory}


def section_live() -> dict:
    """The running console. Every 2026-07-27 defect was found here and none by reading code."""
    import urllib.request

    def get(path: str, timeout: float = 25.0):
        try:
            with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            return {"__err__": f"{type(e).__name__}: {e}"}

    probe = get("/api/spot?ticker=SPY", 8.0)
    if "__err__" in probe:
        return {"reachable": False, "note": "no console on 127.0.0.1:8000 — "
                                            "every liveness claim below is UNVERIFIED"}
    out: dict = {"reachable": True, "endpoints": {}}
    for ep in ("/api/spot?ticker=SPY", "/api/bars1m?ticker=SPY", "/api/terrain?ticker=SPY",
               "/api/terrain/strikes?ticker=SPY", "/api/terrain/radar?limit=30",
               "/api/terrain/scorecard", "/api/level_crosses?ticker=SPY&n=8"):
        d = get(ep, 45.0)
        if "__err__" in d:
            out["endpoints"][ep] = f"ERROR {d['__err__'][:60]}"
            continue
        cols = {k: (len(v) if isinstance(v, list)
                    else sum(len(x) for x in v.values() if isinstance(x, list)))
                for k, v in d.items() if isinstance(v, (list, dict)) and not k.startswith("_")}
        filled = {k: v for k, v in cols.items() if v}
        scal = [k for k, v in d.items() if isinstance(v, (int, float))]
        out["endpoints"][ep] = (f"{filled}" if filled else
                                (f"scalars={len(scal)}" if scal else "EMPTY PAYLOAD"))
    t = get("/api/terrain?ticker=SPY", 45.0)
    s = get("/api/terrain/strikes?ticker=SPY", 45.0)
    out["levels"] = {k: t.get(k) for k in ("spot", "call_wall", "put_wall", "gamma_flip")}
    out["panel_age_sec"] = s.get("today_age_sec")
    out["panel_source"] = s.get("today_source")
    rows = (s.get("today") or {}).get("all") or []
    out["per_strike_rows"] = len(rows)
    out["session_volume"] = sum(r[2] for r in rows if len(r) > 2)
    return out


def section_faucets() -> dict:
    try:
        from tools.data_faucet_audit import run as faucet_run
        rep = faucet_run(str(REPO / "data" / "ed_console.db"))
    except Exception as e:
        return {"unmeasurable": f"{type(e).__name__}: {e}"}
    return {"violations": len(rep.get("faucet_violations", [])),
            "detail": [v.get("concept") for v in rep.get("faucet_violations", [])],
            "stale_sources": [f"{s['faucet']} age={round(s['age_sec']/3600,1)}h "
                              f"> limit {round(s['limit_sec']/3600,1)}h"
                              for s in rep.get("stale_sources", [])]}


def section_db() -> dict:
    db = REPO / "data" / "ed_console.db"
    if not db.exists():
        return {"unmeasurable": "data/ed_console.db missing"}
    out: dict = {"size_gb": round(db.stat().st_size / 1024 ** 3, 2)}
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=20)
    except sqlite3.Error as e:
        return {"unmeasurable": str(e)}
    try:
        out["integrity"] = con.execute("PRAGMA quick_check(1)").fetchone()[0]
        tabs = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        out["tables"] = len(tabs)
        big = []
        for t in tabs:
            try:
                big.append((con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], t))
            except sqlite3.Error:
                pass
        out["largest_tables"] = [f"{t}: {n:,}" for n, t in sorted(big, reverse=True)[:6]]
        # Duplication in the event log — one price event written once per NAMED level (RC-88).
        try:
            tot = con.execute("SELECT COUNT(*) FROM level_crosses").fetchone()[0]
            extra = con.execute(
                "SELECT COALESCE(SUM(c-1),0) FROM (SELECT COUNT(*) c FROM level_crosses "
                "GROUP BY ticker, ts_utc, level_value HAVING COUNT(*)>1)").fetchone()[0]
            out["level_crosses_duplication"] = (
                f"{extra:,} of {tot:,} rows are repeats of another row's "
                f"(ticker, ts, level_value) — {extra / max(tot, 1) * 100:.1f}%")
        except sqlite3.Error:
            pass
    finally:
        con.close()
    return out


def section_git() -> dict:
    status = _sh("git", "status", "--short")
    tracked = [ln for ln in status.splitlines() if not ln.startswith("??")]
    untracked = [ln for ln in status.splitlines() if ln.startswith("??")]
    return {"head": _sh("git", "log", "--oneline", "-1"),
            "branch": _sh("git", "rev-parse", "--abbrev-ref", "HEAD"),
            "uncommitted_tracked": len(tracked),
            "uncommitted_detail": [ln.strip()[:70] for ln in tracked[:8]],
            "untracked": len(untracked)}


def section_tests() -> dict:
    out = _sh(str(REPO / ".venv" / "Scripts" / "python.exe"), "-m", "pytest",
              "--collect-only", "-q", "tests")
    tail = [ln for ln in out.splitlines() if "test" in ln.lower() and "collected" in ln.lower()]
    files = len(list((REPO / "tests").glob("test_*.py")))
    return {"test_files": files, "collection": tail[-1] if tail else "(collection unavailable)"}


SECTIONS = (("INSTITUTIONAL GATE", section_gate), ("GOVERNANCE LEDGER", section_governance),
            ("LIVE CONSOLE", section_live), ("DATA FAUCETS", section_faucets),
            ("DATABASE", section_db), ("GIT", section_git), ("TESTS", section_tests))


def render(rep: dict, brief: bool = False) -> str:
    L = ["", "=" * 78, "REPO EXPOSURE AUDIT", "=" * 78,
         "This tool reports numbers, not verdicts. UNMEASURABLE is a finding, never a pass.", ""]
    for title, _ in SECTIONS:
        data = rep.get(title, {})
        L.append(f"── {title} " + "─" * max(0, 74 - len(title)))
        if not isinstance(data, dict):
            L.append(f"   {data}")
            L.append("")
            continue
        if "unmeasurable" in data:
            L.append(f"   UNMEASURABLE: {data['unmeasurable']}  <-- this is a FINDING")
            L.append("")
            continue
        for k, v in data.items():
            if brief and isinstance(v, list) and len(v) > 3:
                L.append(f"   {k}: {len(v)} item(s)")
                continue
            if isinstance(v, dict):
                nz = {kk: vv for kk, vv in v.items() if vv}
                L.append(f"   {k}: {len(v)} entries, {len(nz)} non-zero")
                for kk, vv in list(nz.items())[:14]:
                    L.append(f"      {kk}: {vv}")
            elif isinstance(v, list):
                L.append(f"   {k}: {len(v)}")
                for x in v[:10]:
                    L.append(f"      {x}")
            else:
                L.append(f"   {k}: {v}")
        L.append("")
    L += ["=" * 78,
          "No --check mode by design: the moment this is something to pass, it becomes",
          "something to satisfy — and everything else was already being satisfied.",
          "=" * 78]
    return "\n".join(L)


def main(argv: list[str]) -> int:
    rep: dict = {}
    for title, fn in SECTIONS:
        t0 = time.time()
        try:
            rep[title] = fn()
        except Exception as e:                       # a crashed section is a finding
            rep[title] = {"unmeasurable": f"{type(e).__name__}: {e}"}
        rep[title].setdefault("_sec", round(time.time() - t0, 1))
    if "--json" in argv:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print(render(rep, brief="--brief" in argv))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
