"""THE RUNNING REHAB PLAN — and it measures itself (RC-264).

WHY THIS IS CODE AND NOT A DOCUMENT
    `governance/REHAB_PROGRAM.md` already exists. It is a good document, RC-220,
    charter dated 2026-08-03, with a correct spine: census, one authority, kill
    the second path, test, lock, prove live. Two days later /terrain still
    404s, /api/spot fires 53 times in 82 seconds, /api/terrain/radar stalls
    8,426 ms cold, and 485 MB of Chrome browser profiles sat staged for commit.
    The charter describes all of that work and detected none of it.

    A document cannot run, so it cannot notice. Every item below carries a
    MEASUREMENT and a TARGET, so `python tools/rehab_plan.py` reports where the
    repository actually stands. Nobody types a status, so no status can be
    stale, and an item whose measurement cannot be written is by that fact not
    yet a plan item.

HOW TO READ IT
    DONE     measured value meets the target
    OPEN     measured value does not
    BLOCKED  work finished, cannot land without an operator decision
    MANUAL   needs a judgement only the operator can make
    SKIP     needs the live server and it is down

Run:  python tools/rehab_plan.py [--json] [--phase N]
Exit: 0 always. This reports; the individual checks are what block.
"""

from __future__ import annotations

import argparse
import ast
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "http://127.0.0.1:8000"
SKIP_DIRS = {".venv", "node_modules", "__pycache__", "site-packages", ".git",
             ".mypy_cache", ".pytest_cache", "backups", "scratchpad"}
PROD_SKIP = SKIP_DIRS | {"tests", "reports", "docs", "governance",
                         "arch_competition", "research", "calibration"}


# ----------------------------------------------------------- helpers ------

def _files(patterns: tuple[str, ...], skip: set[str] | None = None) -> list[str]:
    bad = skip or SKIP_DIRS
    out = []
    for pat in patterns:
        for p in glob.glob(os.path.join(REPO, pat), recursive=True):
            if any(d in re.split(r"[\\/]", p) for d in bad):
                continue
            if os.path.isfile(p):
                out.append(p)
    return out


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", REPO, *args],
                          capture_output=True, text=True).stdout


def _get(path: str, timeout: int = 25) -> tuple[int | None, bytes]:
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as r:
            return r.getcode(), r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return None, b""


def server_up() -> bool:
    return _get("/api/health", timeout=6)[0] == 200


def _read(path: str) -> str:
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


# ------------------------------------------------------ measurements ------

def _faucet_census():
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import check_one_faucet_live as OF
    produced, _ = OF.census(BASE, "SPY")
    return {f: m for f, m in produced.items() if len(m) > 1}


def m_faucets_disagreeing() -> tuple[float, str]:
    if not server_up():
        return (-1, "server down")
    multi = _faucet_census()
    bad = {f: m for f, m in multi.items() if len(set(m.values())) > 1}
    worst = ", ".join(sorted(bad)[:5])
    return (len(bad), f"{len(bad)} disagree of {len(multi)} multi-faucet: {worst}")


def m_faucets_total() -> tuple[float, str]:
    if not server_up():
        return (-1, "server down")
    multi = _faucet_census()
    return (len(multi), f"{len(multi)} fields have more than one producer")


DERIVED = {
    "gex": ("gex", "gamma_exposure", "gamma_dollar"), "dex": ("dex", "delta_exposure"),
    "charm": ("charm",), "vanna": ("vanna",), "flip": ("flip",), "wall": ("wall",),
    "regime": ("regime",), "net_delta": ("net_delta",), "exposures": ("exposures",),
    "book_imbalance": ("book_imbalance", "top_book_pressure"), "spot": ("spot",),
    "atm_iv": ("sigma_atm", "atm_iv"), "greeks": ("black_scholes", "norm_cdf"),
    "max_pain": ("max_pain",),
}


def m_derived_multi_module() -> tuple[float, str]:
    found: dict[str, set[str]] = defaultdict(set)
    for path in _files(("**/*.py",), PROD_SKIP):
        try:
            tree = ast.parse(_read(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            toks = set(re.split(r"[_\W]+", node.name.lower()))
            for concept, needles in DERIVED.items():
                if any((n in node.name.lower()) if "_" in n else (n in toks)
                       for n in needles):
                    found[concept].add(path)
    multi = sorted(c for c, mods in found.items() if len(mods) > 1)
    return (len(multi), f"{len(multi)} of {len(found)} concepts multi-module: "
                        f"{', '.join(multi[:6])}")


def m_duplicate_functions() -> tuple[float, str]:
    bodies: dict[str, set[str]] = defaultdict(set)
    for path in _files(("**/*.py",)):
        try:
            tree = ast.parse(_read(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            stmts = [s for s in node.body
                     if not (isinstance(s, ast.Expr)
                             and isinstance(getattr(s, "value", None), ast.Constant))]
            if len(stmts) < 6:
                continue
            try:
                sig = ast.dump(ast.Module(body=stmts, type_ignores=[]),
                               annotate_fields=False)
            except (TypeError, ValueError):
                continue
            bodies[hashlib.sha256(sig.encode()).hexdigest()].add(path)
    dupes = [h for h, mods in bodies.items() if len(mods) > 1]
    return (len(dupes), f"{len(dupes)} bodies implemented in more than one module")


def m_identical_files() -> tuple[float, str]:
    by_hash: dict[str, list[str]] = defaultdict(list)
    for p in _files(("**/*.py", "**/*.html", "**/*.js", "**/*.css", "**/*.sql")):
        try:
            raw = open(p, "rb").read()
        except OSError:
            continue
        # Empty package markers are correct Python, not duplication. Counting
        # every __init__.py against every other one was a false positive, and a
        # check that cries wolf is a check nobody reads.
        if not raw.strip():
            continue
        by_hash[hashlib.sha256(raw).hexdigest()].append(p)
    groups = [ps for ps in by_hash.values() if len(ps) > 1]
    wasted = sum(os.path.getsize(ps[0]) * (len(ps) - 1) for ps in groups)
    return (len(groups), f"{len(groups)} groups, {wasted:,} bytes duplicated")


def m_scratch_tracked() -> tuple[float, str]:
    n = sum(1 for p in _git("ls-files").split("\n") if p.startswith("scratchpad"))
    return (n, f"{n} scratchpad paths in the index")


#: Every surface the operator names, including the one that fails.
#: /terrain is here DELIBERATELY. The first draft of this file omitted it and
#: the item reported DONE -- defining the defect away inside the artifact built
#: to prevent exactly that. Terrain is currently a body-class mode of /, not a
#: route, and until that is resolved this item must read OPEN.
SURFACES = ("/", "/terrain", "/desk", "/chart", "/exposure")


def m_surfaces_not_200() -> tuple[float, str]:
    if not server_up():
        return (-1, "server down")
    bad = [s for s in SURFACES if _get(s, timeout=10)[0] != 200]
    return (len(bad), f"{len(bad)} of {len(SURFACES)} not 200: {bad or 'none'}")


def m_dead_endpoints() -> tuple[float, str]:
    srv = _read(os.path.join(REPO, "server.py"))
    defined = {p for _, p in re.findall(
        r"@app\.(get|post|delete|put)\(\s*[\"']([^\"']+)", srv)
        if p.startswith("/api/")}
    front = "".join(_read(p) for p in _files(("static/*.html",)))
    dead = [e for e in defined if (e.split("{")[0].rstrip("/") or "@") not in front]
    return (len(dead), f"{len(dead)} of {len(defined)} API endpoints unreferenced")


def m_palette() -> tuple[float, str]:
    worst, where = 0, "none"
    for p in _files(("static/*.html",)):
        t = _read(p)
        n = len(set(re.findall(r"#[0-9a-fA-F]{3,8}\b", t))
                | set(re.findall(r"rgba?\([^)]*\)", t)))
        if n > worst:
            worst, where = n, os.path.basename(p)
    return (worst, f"worst surface {where} carries {worst} distinct colours")


def m_offgrid() -> tuple[float, str]:
    grid = {0, 2, 4, 8, 12, 16, 24, 32, 40, 48, 64, 96, 160}
    tot = bad = 0
    for p in _files(("static/*.html",)):
        vals = [abs(float(v)) for v in re.findall(
            r"(?:margin|padding|gap)[a-z-]*:\s*(-?[0-9.]+)px", _read(p))]
        tot += len(vals)
        bad += sum(1 for v in vals if v not in grid)
    pct = 100.0 * bad / tot if tot else 0.0
    return (pct, f"{bad}/{tot} spacing values off the 8pt grid ({pct:.0f}%)")


def m_open_rc() -> tuple[float, str]:
    """Measurement only. RC OPEN/PARTIAL has zero work authority."""
    rows = re.findall(r"^\| (RC-\d+) \| (\w+) \|",
                      _read(os.path.join(REPO, "governance", "root_cause_log.md")), re.M)
    op = [i for i, s in rows if s != "CLOSED"]
    return (0.0, f"measurement only: {len(op)} non-closed of {len(rows)} (zero work authority)")


def m_status_vocabulary_enforced() -> tuple[float, str]:
    """Registered, ENFORCED, and green -- read, never asserted.

    RC-268: this item previously returned the constant string "check written,
    19 controls pass, not committed". It kept saying that after the check
    landed in 6c9f64cb, because nothing re-evaluates a constant. That is the
    property RC-264 built this file to eliminate, reproduced inside the file.
    """
    try:
        sys.path.insert(0, os.path.join(REPO, "tools"))
        import check_institutional_correctness as K
    except Exception as exc:                                    # noqa: BLE001
        return (1.0, f"checker unimportable: {type(exc).__name__}")
    entry = [(n, e) for n, _fn, e in getattr(K, "CHECKS", [])
             if n == "rc_status_vocabulary"]
    if not entry:
        return (1.0, "rc_status_vocabulary is not registered")
    if not entry[0][1]:
        return (1.0, "rc_status_vocabulary is registered but NOT enforced")
    violations = len(K.check_rc_status_vocabulary())
    if violations:
        return (float(violations), f"{violations} undeclared status token(s) in the ledger")
    return (0.0, "registered, ENFORCED, 0 violations on the live ledger")


#: Commit-path REQUIRED controls only. duplication_audit and check_one_faucet_live
#: are DIAGNOSTIC_TOOL (non-authoritative); listing them here was phantom enforcement.
BLOCKING_TOOLS = ("check_db_health",)
DIAGNOSTIC_TOOLS = ("duplication_audit", "check_one_faucet_live")


def m_tools_unwired() -> tuple[float, str]:
    """How many measuring tools nothing actually runs."""
    config = _read(os.path.join(REPO, ".pre-commit-config.yaml"))
    try:
        sys.path.insert(0, os.path.join(REPO, "tools"))
        import check_institutional_correctness as K
        registry = " ".join(n for n, _f, _e in getattr(K, "CHECKS", []))
    except Exception:                                           # noqa: BLE001
        registry = ""
    unwired = [t for t in BLOCKING_TOOLS
               if t not in config and t not in registry]
    return (len(unwired),
            f"{len(unwired)} of {len(BLOCKING_TOOLS)} unwired: "
            f"{', '.join(unwired) or 'none'}")


def m_server_lines() -> tuple[float, str]:
    n = _read(os.path.join(REPO, "server.py")).count("\n")
    return (n, f"server.py is {n:,} lines in one module")


# ------------------------------------------------------------- items ------

@dataclass
class Item:
    ident: str
    phase: int
    title: str
    why: str
    target: float
    measure: Callable[[], tuple[float, str]]
    note: str = ""
    manual: bool = False
    blocked_on: str = ""
    evidence: str = ""

    def state(self) -> tuple[str, float, str]:
        if self.manual:
            return ("MANUAL", -1.0, self.note)
        try:
            value, detail = self.measure()
        except Exception as exc:                                # noqa: BLE001
            return ("ERROR", -1.0, f"{type(exc).__name__}: {exc}")
        if value < 0:
            return ("SKIP", value, detail)
        if value <= self.target:
            return ("DONE", value, detail)
        if self.blocked_on:
            return ("BLOCKED", value, detail)
        return ("OPEN", value, detail)


PLAN: list[Item] = [
    Item("F1", 1, "One faucet per field — no two endpoints disagree",
         "spot returned 769.79 to 775.43 across 14 endpoints, and book_imbalance_5 "
         "came back -0.314 and +0.212 at one instant: opposite signs on a "
         "directional signal. Two screens can advise opposite trades.",
         0, m_faucets_disagreeing,
         evidence="tools/check_one_faucet_live.py"),
    Item("F2", 1, "One faucet per field — no field has two producers at all",
         "286 fields agree today with nothing stopping them drifting tomorrow. "
         "Agreement by luck is not a contract.",
         0, m_faucets_total),
    Item("F3", 1, "Each derived quantity computed in exactly one module",
         "gex has 13 functions across 7 modules; regime spans 12. The leaf census "
         "cannot see these because they live inside per-strike lists.",
         0, m_derived_multi_module),

    Item("D1", 2, "No function body implemented in two modules",
         "181 identical bodies across modules. Every one is a place a fix lands "
         "in one copy and not the other.",
         0, m_duplicate_functions),
    Item("D2", 2, "No byte-identical file at two paths",
         "531 groups wasting 33 MB, including a second copy of the whole server.",
         0, m_identical_files),
    Item("D3", 2, "Scratch is never tracked",
         "485 MB of Chrome browser profiles sat staged, one broad commit from "
         "entering history permanently.",
         0, m_scratch_tracked),
    Item("D4", 2, "server.py is not a monolith",
         "15,092 lines and 74 routes in one module is WHY duplication stays "
         "invisible: nobody can hold it in mind well enough to spot the copy.",
         4000, m_server_lines,
         note="the 4000 target is a judgement, not a measurement — argue with it"),

    Item("S1", 3, "Every named surface returns 200",
         "/terrain 404s and always has. Terrain is a body-class mode of /, while "
         "desk, chart and exposure are routes: three architectures, five surfaces.",
         0, m_surfaces_not_200),
    Item("S2", 3, "No endpoint is built and never called",
         "23 of 63 API endpoints are unreferenced by any page. Desk has five "
         "endpoints returning real data and calls one.",
         0, m_dead_endpoints),

    Item("U1", 4, "Colour palette is a token set, not an accident",
         "index.html carries 372 distinct colours. IBM Carbon ships about 30. "
         "This is most of what reads as sophomoric.",
         30, m_palette),
    Item("U2", 4, "Spacing sits on an 8pt grid",
         "57-81% of spacing values are off any grid — 6px, 3px, 5px, 7px, 9px, "
         "the fingerprint of tuning by eye. Carbon uses 16 values in total.",
         5, m_offgrid),
    Item("U3", 4, "Reference set chosen by the operator",
         "The spec must be EXTRACTED from products the operator judges world "
         "class, never authored by the agent — otherwise the target is the "
         "agent's prior wearing a costume.",
         0, lambda: (1.0, "awaiting operator picks"), manual=True,
         note="operator to name 2-3 of: SpotGamma, MenthorQ, GEXRadar, "
              "GEXStream, FlashAlpha, Perspicium"),

    Item("G1", 5, "RC log remains evidence, not a work queue",
         "The ledger is historical evidence of defect investigation. RC OPEN / "
         "due date / classification must not independently select or block work; "
         "unresolved residuals live only on the sole master checklist.",
         0, m_open_rc),
    Item("G2", 5, "Unrecognised RC status fails instead of skipping",
         "DONE, FINISHED and the typo CLOSE each took a deficient row from 2 "
         "violations to 0. The gate must be registered, ENFORCED, and green.",
         0, m_status_vocabulary_enforced,
         evidence="check_institutional_correctness.py::check_rc_status_vocabulary"),
    Item("G3", 5, "The measuring tools are wired to something that blocks",
         "rehab_plan, duplication_audit, check_db_health and "
         "check_one_faucet_live were all executable and none was enforced: "
         "absent from the CHECKS registry and from .pre-commit-config.yaml. A "
         "tool nobody runs is a comment with an exit code, and nothing stopped "
         "a commit from regressing every measurement they take.",
         0, m_tools_unwired),
]

PHASE_NAMES = {
    1: "CORRECTNESS — wrong is worse than slow",
    2: "DUPLICATION — one implementation of everything",
    3: "PRODUCT SURFACE — every surface real and reachable",
    4: "CRAFT — measurable, extracted from references",
    5: "THE LEDGER — the control that polices the rest",
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--phase", type=int, default=0)
    args = ap.parse_args(argv)

    items = [i for i in PLAN if not args.phase or i.phase == args.phase]
    results = []
    for item in items:
        state, value, detail = item.state()
        results.append({"id": item.ident, "phase": item.phase, "title": item.title,
                        "state": state, "value": value, "target": item.target,
                        "detail": detail, "why": item.why, "note": item.note,
                        "blocked_on": item.blocked_on, "evidence": item.evidence})

    if args.as_json:
        print(json.dumps(results, indent=2))
        return 0

    print("REHAB PLAN — measured now, never maintained by hand (RC-264)")
    print(f"server: {'UP' if server_up() else 'DOWN — live items skipped'}")
    mark = {"DONE": "[DONE]", "OPEN": "[OPEN]", "BLOCKED": "[BLKD]",
            "MANUAL": "[MANL]", "SKIP": "[skip]", "ERROR": "[ERR ]"}
    last, tally = None, defaultdict(int)
    for r in results:
        if r["phase"] != last:
            last = r["phase"]
            print(f"\n{'='*74}\nPHASE {last} — {PHASE_NAMES.get(last, '')}\n{'='*74}")
        tally[r["state"]] += 1
        print(f"\n  {mark[r['state']]} {r['id']}  {r['title']}")
        print(f"         now:    {r['detail']}")
        if r["state"] not in ("MANUAL", "SKIP"):
            print(f"         target: {r['target']:g}")
        print(f"         why:    {r['why']}")
        if r["blocked_on"]:
            print(f"         BLOCKED ON: {r['blocked_on']}")
        if r["note"]:
            print(f"         note:   {r['note']}")
        if r["evidence"]:
            print(f"         proof:  {r['evidence']}")
    print(f"\n{'='*74}")
    print("  " + " · ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
