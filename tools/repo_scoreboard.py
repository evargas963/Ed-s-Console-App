"""THE SCOREBOARD — every open number on one board (RC-272).

The operator asked for "an exact account of everything we have on the board",
re-produced after every fix, so a change can be seen to move a number rather
than described as progress.

Every line is MEASURED here, never stored. A cached scoreboard is a scoreboard
that lies the moment the repository changes, which is the defect this session
found in a plan that hardcoded its own status (RC-268).

Numbers that are slow to produce -- coverage, the full suite, mutation score --
are read from their ARTEFACT and reported with the artefact's age, so a stale
number is visibly stale rather than silently wrong. An artefact that has never
been produced reads UNMEASURED, which is not the same as good.

Run:  python tools/repo_scoreboard.py [--json]
Exit: 0 always. This reports; the individual checks are what block.
"""

from __future__ import annotations

import argparse
import ast
import glob
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = {".venv", "node_modules", "__pycache__", "site-packages", ".git",
        ".mypy_cache", ".pytest_cache", "backups", "scratchpad"}


@dataclass
class Row:
    key: str
    area: str
    metric: str
    value: str
    target: str
    state: str                      # OK · OPEN · UNMEASURED · STALE
    source: str = ""
    note: str = ""


def _read(rel: str) -> str:
    try:
        return open(os.path.join(REPO, rel), encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def _age(rel: str) -> str:
    p = os.path.join(REPO, rel)
    if not os.path.exists(p):
        return ""
    hrs = (time.time() - os.path.getmtime(p)) / 3600.0
    return f"{hrs:.0f}h old" if hrs >= 1 else f"{hrs*60:.0f}m old"


def _walk_py():
    """Every .py with its scope bucket.

    RC-272: glob plus a regex split on the full path silently matched nothing
    on Windows, so four different CC>15 figures were reported for the same
    repository -- 516, 930, 569, 627. os.walk with in-place dirs pruning is
    the only form that provably excludes a directory, and the scope bucket
    keeps product code separate from tools, tests and research so the number
    means one thing.
    """
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP]
        parts = os.path.relpath(root, REPO).split(os.sep)
        top = parts[0] if parts and parts[0] != "." else ""
        if top == "tests":
            bucket = "tests"
        elif top == "tools":
            bucket = "tools"
        elif top in ("research", "arch_competition", "calibration"):
            bucket = "research"
        else:
            bucket = "product"
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name), bucket


# --------------------------------------------------------------- rows -----

def row_coverage() -> list[Row]:
    art = "reports/coverage.xml"
    p = os.path.join(REPO, art)
    if not os.path.exists(p):
        return [Row("COV", "tests", "line coverage", "—", ">= 80%", "UNMEASURED",
                    note="run: pytest tests --cov=. --cov-report=xml:reports/coverage.xml")]
    root = ET.parse(p).getroot()
    line = float(root.get("line-rate", 0)) * 100
    branch = float(root.get("branch-rate", 0)) * 100
    return [
        Row("COV", "tests", "line coverage", f"{line:.1f}%", ">= 80%",
            "OK" if line >= 80 else "OPEN", art, _age(art)),
        Row("COVB", "tests", "branch coverage", f"{branch:.1f}%", ">= 80%",
            "OK" if branch >= 80 else "OPEN", art, _age(art)),
    ]


def row_suite() -> list[Row]:
    """Failing tests, from the last full run's artefact if one exists."""
    art = "reports/pytest_full_latest.txt"
    text = _read(art)
    if not text:
        return [Row("FAIL", "tests", "failing tests", "—", "0", "UNMEASURED",
                    note="run: pytest tests -q > reports/pytest_full_latest.txt")]
    m = re.search(r"(\d+) failed, (\d+) passed", text)
    if not m:
        return [Row("FAIL", "tests", "failing tests", "—", "0", "UNMEASURED", art)]
    failed = int(m.group(1))
    return [Row("FAIL", "tests", "failing tests", f"{failed} of {int(m.group(2))+failed}",
                "0", "OK" if failed == 0 else "OPEN", art, _age(art))]


def row_mutation() -> list[Row]:
    """Whether a test can DETECT a defect -- the question coverage cannot answer."""
    art = "reports/mutation_latest.txt"
    text = _read(art)
    if not text:
        return [Row("MUT", "tests", "mutation score", "—", ">= 80%", "UNMEASURED",
                    note="the only measure of whether a test would FAIL if the "
                         "code broke; coverage cannot see an assertion-free test")]
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    score = float(m.group(1)) if m else 0.0
    return [Row("MUT", "tests", "mutation score", f"{score:.0f}%", ">= 80%",
                "OK" if score >= 80 else "OPEN", art, _age(art))]


DECISION = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
            ast.With, ast.AsyncWith, ast.Assert, ast.BoolOp, ast.IfExp,
            ast.comprehension)


def row_complexity() -> list[Row]:
    """PRODUCT code only. Scope is stated because it moved the number fourfold."""
    over = total = 0
    worst = (0, "")
    for path, bucket in _walk_py():
        if bucket != "product":
            continue
        try:
            tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            total += 1
            cc = 1 + sum(1 for n in ast.walk(node) if isinstance(n, DECISION))
            if cc > 15:
                over += 1
            if cc > worst[0]:
                worst = (cc, f"{os.path.relpath(path, REPO)}:{node.lineno} {node.name}()")
    return [
        Row("CC", "codebase", "product functions over CC>15",
            f"{over} of {total:,}", "0", "OK" if over == 0 else "OPEN",
            "codeant seven axes", "product scope only; tools/tests/research excluded"),
        Row("CCW", "codebase", "worst function", f"CC {worst[0]}", "<= 15",
            "OK" if worst[0] <= 15 else "OPEN", note=worst[1]),
    ]


def row_server_size() -> list[Row]:
    n = _read("server.py").count("\n")
    return [Row("MONO", "codebase", "server.py lines", f"{n:,}", "split by layer",
                "OPEN" if n > 4000 else "OK",
                note="spans capture/store/compute/serve/present")]


def row_unwired() -> list[Row]:
    tools = sorted(os.path.basename(p)[:-3]
                   for p in glob.glob(os.path.join(REPO, "tools", "*.py")))
    surfaces = (_read(".pre-commit-config.yaml")
                + _read("tools/check_institutional_correctness.py")
                + _read("governance/host_scheduled_jobs.md")
                + "".join(_read(os.path.relpath(p, REPO))
                          for p in glob.glob(os.path.join(REPO, "**/*.ps1"),
                                             recursive=True))
                + "".join(_read(os.path.relpath(p, REPO))
                          for p in glob.glob(os.path.join(REPO, ".github/workflows/*.y*ml"))))
    unwired = [t for t in tools if t not in surfaces]
    return [Row("WIRE", "codebase", "tools no runner invokes",
                f"{len(unwired)} of {len(tools)}", "0", "OPEN" if unwired else "OK",
                note="no pre-commit/gate/schedule/CI runs these; audit each — "
                     "wire if it serves the repo, delete if archaeology")]


def row_faucets() -> list[Row]:
    """Needs the running server; UNMEASURED when it is down, never OK."""
    art = "reports/rehab_latest.md"
    text = _read(art)
    m = re.search(r"(\d+) field\(s\) disagree", text)
    if not m:
        return [Row("FAUC", "data", "fields disagreeing across endpoints", "—", "0",
                    "UNMEASURED", art, "needs the server up")]
    n = int(m.group(1))
    return [Row("FAUC", "data", "fields disagreeing across endpoints", str(n), "0",
                "OK" if n == 0 else "OPEN", art, _age(art))]


def row_db() -> list[Row]:
    db = os.path.join(REPO, "data", "ed_console.db")
    if not os.path.exists(db):
        return [Row("DB", "data", "database health", "—", "0 failing", "UNMEASURED")]
    code = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "check_db_health.py")],
        capture_output=True, text=True, cwd=REPO).returncode
    size = os.path.getsize(db) / 1073741824
    return [
        Row("DB", "data", "database health rules failing", "0" if code == 0 else ">=1",
            "0", "OK" if code == 0 else "OPEN", "tools/check_db_health.py"),
        Row("DBSZ", "data", "ed_console.db size", f"{size:.1f} GB", "—", "OK",
            note="per-table bytes unavailable: this SQLite build omits dbstat"),
    ]


def row_rc() -> list[Row]:
    rows = re.findall(r"^\| (RC-\d+) \| (\w+) \|",
                      _read("governance/root_cause_log.md"), re.M)
    op = [i for i, s in rows if s != "CLOSED"]
    return [Row("RC", "ledger", "open root causes", f"{len(op)} of {len(rows)}", "0",
                "OK" if not op else "OPEN", note=", ".join(op[:8]))]


def row_plans() -> list[Row]:
    pats = ("*PLAN*", "*ROADMAP*", "*PROGRAM*")
    found = set()
    for d in ("governance", "docs", "reports", "."):
        for pat in pats:
            for f in glob.glob(os.path.join(REPO, d, "**", pat), recursive=True):
                if os.path.isfile(f) and not any(
                        s in re.split(r"[\\/]", f) for s in SKIP):
                    found.add(f)
    return [Row("PLAN", "ledger", "competing plan documents", str(len(found)), "1",
                "OPEN" if len(found) > 1 else "OK",
                note="one canonical plan; the rest consolidated or deleted")]


def row_surfaces() -> list[Row]:
    art = "reports/rehab_latest.md"
    return [Row("SURF", "product", "named surfaces returning 200", "—", "5 of 5",
                "UNMEASURED", art, "needs the server up; /terrain has no route")]


def row_ui() -> list[Row]:
    worst, where = 0, ""
    for p in glob.glob(os.path.join(REPO, "static", "*.html")):
        t = open(p, encoding="utf-8", errors="replace").read()
        n = len(set(re.findall(r"#[0-9a-fA-F]{3,8}\b", t))
                | set(re.findall(r"rgba?\([^)]*\)", t)))
        if n > worst:
            worst, where = n, os.path.basename(p)
    grid = {0, 2, 4, 8, 12, 16, 24, 32, 40, 48, 64, 96, 160}
    tot = bad = 0
    for p in glob.glob(os.path.join(REPO, "static", "*.html")):
        vals = [abs(float(v)) for v in re.findall(
            r"(?:margin|padding|gap)[a-z-]*:\s*(-?[0-9.]+)px",
            open(p, encoding="utf-8", errors="replace").read())]
        tot += len(vals)
        bad += sum(1 for v in vals if v not in grid)
    pct = 100.0 * bad / tot if tot else 0
    return [
        Row("PAL", "ui", "distinct colours (worst surface)", str(worst), "<= 30",
            "OK" if worst <= 30 else "OPEN", "IBM Carbon", where),
        Row("GRID", "ui", "spacing off the 8pt grid", f"{pct:.0f}%", "<= 5%",
            "OK" if pct <= 5 else "OPEN", "IBM Carbon"),
    ]


BUILDERS = (row_coverage, row_suite, row_mutation, row_complexity, row_server_size,
            row_unwired, row_faucets, row_db, row_rc, row_plans, row_surfaces, row_ui)


def collect() -> list[Row]:
    rows: list[Row] = []
    for build in BUILDERS:
        try:
            rows += build()
        except Exception as exc:                                # noqa: BLE001
            rows.append(Row(build.__name__, "?", build.__name__, "—", "—", "ERROR",
                            note=f"{type(exc).__name__}: {exc}"))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)

    rows = collect()
    if args.as_json:
        print(json.dumps([r.__dict__ for r in rows], indent=2))
        return 0

    head = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    print(f"THE SCOREBOARD — measured now, never stored (RC-272)   HEAD {head}")
    print("=" * 96)
    print(f"  {'':<6}{'AREA':<10}{'METRIC':<38}{'NOW':>14}{'TARGET':>16}   STATE")
    print("  " + "-" * 92)
    last, tally = None, {}
    for r in rows:
        if r.area != last:
            last = r.area
            print()
        tally[r.state] = tally.get(r.state, 0) + 1
        mark = {"OK": "[ok ]", "OPEN": "[    ]", "UNMEASURED": "[ ?  ]",
                "STALE": "[stal]", "ERROR": "[err ]"}.get(r.state, "[    ]")
        print(f"  {mark:<6}{r.area:<10}{r.metric:<38}{r.value:>14}{r.target:>16}   {r.state}")
        if r.note:
            print(f"  {'':<6}{'':<10}{r.note[:80]}")
    print()
    print("  " + "-" * 92)
    print("  " + " · ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
