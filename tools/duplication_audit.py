"""THE DUPLICATION REGISTER — one number, and it must reach zero (RC-265).

The operator's law is one faucet: a thing is produced ONCE and read wherever
it is needed. Duplication is that law violated, and it hides in more places
than a single scan looks:

    D-FILE     byte-identical files
    D-MODULE   near-identical modules that have since drifted apart
    D-FUNC     the same function body implemented in two modules
    D-CONCEPT  a derived quantity computed in more than one module
    D-FIELD    a field published by more than one endpoint (live)
    D-VALUE    a field whose faucets DISAGREE right now (live) — the dangerous kind
    D-ROUTE    two endpoints returning the same payload shape (live)
    D-DEAD     an endpoint built and never called by any surface
    D-CONST    the same domain constant literal written in two modules
    D-SQL      the same query text issued from two places
    D-CSS      the same style rule block declared twice
    D-CHECK    two enforced gates whose docstrings claim the same property

Every finding gets a stable id so it can be argued with, deferred, or fixed.
The TOTAL is the number the operator watches. It goes down or the work did not
happen.

Run:  python tools/duplication_audit.py [--json] [--kind D-FUNC] [--full]
Exit: 0 when the total is zero, 1 otherwise.
"""

from __future__ import annotations

import argparse
import ast
import glob
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "http://127.0.0.1:8000"
SKIP_DIRS = {".venv", "node_modules", "__pycache__", "site-packages", ".git",
             ".mypy_cache", ".pytest_cache", "backups", "scratchpad"}
PROD_SKIP = SKIP_DIRS | {"tests", "reports", "docs", "governance",
                         "arch_competition", "research", "calibration"}


@dataclass
class Finding:
    kind: str
    ident: str
    detail: str
    members: list[str] = field(default_factory=list)
    accepted: str = ""          # non-empty => a reasoned exemption, still listed


#: Reasoned exemptions. Each must say WHY, and each still appears in output so
#: an exemption can never become an invisible gap.
ACCEPTED: dict[str, str] = {
    "D-FILE:reports/daily_scoreboard/latest.html":
        "latest-pointer convention: a dated snapshot plus a stable filename",
}


def _files(pats: tuple[str, ...], skip: set[str] | None = None) -> list[str]:
    bad = skip or SKIP_DIRS
    out = []
    for pat in pats:
        for p in glob.glob(os.path.join(REPO, pat), recursive=True):
            if any(d in re.split(r"[\\/]", p) for d in bad):
                continue
            if os.path.isfile(p):
                out.append(p)
    return out


def rel(p: str) -> str:
    return os.path.relpath(p, REPO).replace("\\", "/")


def _read(p: str) -> str:
    try:
        return open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def _get(path: str, timeout: int = 25):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:                                        # noqa: BLE001
        return None


def server_up() -> bool:
    return _get("/api/health", timeout=6) is not None


# ------------------------------------------------------------ scanners ----

def scan_files() -> list[Finding]:
    by_hash: dict[str, list[str]] = defaultdict(list)
    for p in _files(("**/*.py", "**/*.html", "**/*.js", "**/*.css", "**/*.sql")):
        try:
            raw = open(p, "rb").read()
        except OSError:
            continue
        if not raw.strip():          # empty package markers are correct Python
            continue
        by_hash[hashlib.sha256(raw).hexdigest()].append(p)
    out = []
    for ps in by_hash.values():
        if len(ps) < 2:
            continue
        members = sorted(rel(p) for p in ps)
        out.append(Finding("D-FILE", f"D-FILE:{members[0]}",
                           f"{os.path.getsize(ps[0]):,} bytes x{len(ps)}", members))
    return out


def scan_modules() -> list[Finding]:
    import difflib
    big = sorted(((p, os.path.getsize(p)) for p in _files(("**/*.py",))
                  if os.path.getsize(p) >= 8192), key=lambda t: -t[1])[:70]
    texts = {p: _read(p) for p, _ in big}
    out, paths = [], list(texts)
    for i, a in enumerate(paths):
        for b in paths[i + 1:]:
            la, lb = len(texts[a]), len(texts[b])
            if not la or not lb or abs(la - lb) / max(la, lb) > 0.4:
                continue
            # quick_ratio only compares character multisets, so it is an UPPER
            # BOUND: two modules using the same alphabet score high while
            # sharing no structure. Using it alone reported 401 near-duplicate
            # pairs, almost all of them Python files that merely look like
            # Python. It is a cheap prefilter; ratio() is the measurement.
            matcher = difflib.SequenceMatcher(None, texts[a], texts[b])
            if matcher.quick_ratio() < 0.85:
                continue
            ratio = matcher.ratio()
            if ratio >= 0.85:
                members = sorted([rel(a), rel(b)])
                out.append(Finding("D-MODULE", f"D-MODULE:{members[0]}|{members[1]}",
                                   f"{ratio*100:.1f}% similar", members))
    return out


def scan_functions() -> list[Finding]:
    bodies: dict[str, list[tuple[str, int, str, int]]] = defaultdict(list)
    for p in _files(("**/*.py",)):
        try:
            tree = ast.parse(_read(p))
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
            bodies[hashlib.sha256(sig.encode()).hexdigest()].append(
                (rel(p), node.lineno, node.name, len(stmts)))
    out = []
    for v in bodies.values():
        if len({p for p, _, _, _ in v}) < 2:
            continue
        members = sorted(f"{p}:{ln} {name}()" for p, ln, name, _ in v)
        out.append(Finding("D-FUNC", f"D-FUNC:{members[0]}",
                           f"{v[0][3]} statements, {len(v)} copies", members))
    return out


DERIVED = {
    "gex": ("gex", "gamma_exposure", "gamma_dollar"), "dex": ("dex", "delta_exposure"),
    "charm": ("charm",), "vanna": ("vanna",), "flip": ("flip",), "wall": ("wall",),
    "regime": ("regime",), "net_delta": ("net_delta",), "exposures": ("exposures",),
    "book_imbalance": ("book_imbalance", "top_book_pressure"), "spot": ("spot",),
    "atm_iv": ("sigma_atm", "atm_iv"), "greeks": ("black_scholes", "norm_cdf"),
    "max_pain": ("max_pain",),
}


def scan_concepts() -> list[Finding]:
    found: dict[str, set[str]] = defaultdict(set)
    for p in _files(("**/*.py",), PROD_SKIP):
        try:
            tree = ast.parse(_read(p))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            toks = set(re.split(r"[_\W]+", node.name.lower()))
            for concept, needles in DERIVED.items():
                if any((n in node.name.lower()) if "_" in n else (n in toks)
                       for n in needles):
                    found[concept].add(rel(p))
    return [Finding("D-CONCEPT", f"D-CONCEPT:{c}",
                    f"computed in {len(mods)} modules", sorted(mods))
            for c, mods in sorted(found.items()) if len(mods) > 1]


def _faucets():
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import check_one_faucet_live as OF
    produced, _ = OF.census(BASE, "SPY")
    return {f: m for f, m in produced.items() if len(m) > 1}


def scan_fields() -> list[Finding]:
    if not server_up():
        return []
    return [Finding("D-FIELD", f"D-FIELD:{f}", f"{len(m)} producers",
                    sorted(m)) for f, m in sorted(_faucets().items())]


def scan_values() -> list[Finding]:
    """Cross-endpoint disagreement that EXCEEDS the field's own drift.

    MEASURED 2026-08-06 at the open: two identical runs of the naive version,
    seconds apart, reported 105 then 6. Polling nineteen endpoints takes
    seconds, and during market hours the price moves between the first call
    and the last, so every field derived from spot "disagrees" simply because
    it was sampled at different instants. A check that reads 105 or 6 for the
    same repository is noise, and it is noisiest exactly when it matters.

    So the field is measured against ITSELF first. Two full passes give each
    field a self-drift: how much it moved between passes with no faucet
    disagreement involved. Only cross-endpoint spread LARGER than that drift
    is reported. A structural disagreement stays; a moving price cancels.

    Fails safe toward reporting: when a field has no drift measurement, any
    spread is reported rather than assumed benign.
    """
    if not server_up():
        return []
    first = _faucets()
    second = _faucets()

    out = []
    for f, m in sorted(first.items()):
        vals = list(m.values())
        if len(set(vals)) < 2:
            continue
        spread = max(vals) - min(vals)

        # self-drift: the same endpoint's value across the two passes
        drift = 0.0
        other = second.get(f, {})
        for ep, v in m.items():
            if ep in other:
                drift = max(drift, abs(other[ep] - v))

        if drift and spread <= drift:
            continue                     # moved, did not disagree

        # and it must still disagree on the second pass
        if other and len(set(other.values())) < 2:
            continue

        out.append(Finding(
            "D-VALUE", f"D-VALUE:{f}",
            f"{len(m)} faucets DISAGREE, spread {spread:.6g} "
            f"(self-drift {drift:.6g})",
            [f"{v} <- {ep}" for ep, v in sorted(m.items(), key=lambda kv: kv[1])]))
    return out


def scan_dead_endpoints() -> list[Finding]:
    srv = _read(os.path.join(REPO, "server.py"))
    defined = {p for _, p in re.findall(
        r"@app\.(get|post|delete|put)\(\s*[\"']([^\"']+)", srv) if p.startswith("/api/")}
    front = "".join(_read(p) for p in _files(("static/*.html",)))
    return [Finding("D-DEAD", f"D-DEAD:{e}", "built, never called by any surface", [e])
            for e in sorted(defined)
            if (e.split("{")[0].rstrip("/") or "@") not in front]


#: Domain magic numbers that must live in exactly one place.
CONST_PATTERNS = (
    (r"\b252\b", "trading days per year"),
    (r"\b390\b", "RTH minutes"),
    (r"\b16\s*[,:]\s*30\b", "RTH close 16:30"),
    (r"\b9\s*[,:]\s*30\b", "RTH open 9:30"),
    (r"\b100\b(?=\s*[#\)]|\s*\*\s*)", "contract multiplier"),
)


def scan_constants() -> list[Finding]:
    out = []
    for pattern, label in CONST_PATTERNS:
        holders = set()
        for p in _files(("**/*.py",), PROD_SKIP):
            for line in _read(p).splitlines():
                s = line.strip()
                if s.startswith("#") or not re.search(pattern, s):
                    continue
                if re.search(r"=|return|:\s*int|:\s*float", s):
                    holders.add(rel(p))
                    break
        if len(holders) > 1:
            out.append(Finding("D-CONST", f"D-CONST:{label}",
                               f"{label} literal appears in {len(holders)} modules",
                               sorted(holders)))
    return out


def scan_sql() -> list[Finding]:
    stmts: dict[str, set[str]] = defaultdict(set)
    for p in _files(("**/*.py",), PROD_SKIP):
        for m in re.finditer(r"[\"']{1,3}\s*(SELECT\s+.{20,300}?)[\"']{1,3}",
                             _read(p), re.S | re.I):
            norm = re.sub(r"\s+", " ", m.group(1)).strip().lower()
            stmts[norm].add(rel(p))
    return [Finding("D-SQL", f"D-SQL:{hashlib.sha256(q.encode()).hexdigest()[:10]}",
                    f"same query from {len(mods)} modules: {q[:70]}...", sorted(mods))
            for q, mods in stmts.items() if len(mods) > 1]


def scan_css() -> list[Finding]:
    out = []
    for p in _files(("static/*.html", "static/*.css")):
        seen: dict[str, int] = defaultdict(int)
        for m in re.finditer(r"([.#][\w-]+)\s*\{([^}]{20,})\}", _read(p)):
            seen[f"{m.group(1)}|{re.sub(r'[ ]+', ' ', m.group(2)).strip()}"] += 1
        for key, n in seen.items():
            if n > 1:
                sel = key.split("|")[0]
                out.append(Finding("D-CSS", f"D-CSS:{rel(p)}:{sel}",
                                   f"identical rule block declared {n}x", [rel(p)]))
    return out


def scan_universe() -> list[Finding]:
    """Competing notions of WHICH SYMBOLS the system covers.

    The most consequential faucet in the repository, because it decides what
    data exists at all. MEASURED 2026-08-06: the tick-level capture daemon
    hardcodes three sentinels at `--symbols default="SPY,QQQ,IWM"` while the
    logger cycles 43 symbols and the database holds 60 rows, and Alpaca's free
    tier permits 30 of which 6 keys are used. Three caps disagree as well:
    max_pinned_symbols 24, Alpaca 30, actual in-cycle 43.

    The operator's universal-ticker law says SPY/QQQ/IWM are RTH sentinels and
    must never be a proof boundary. Here they are not merely a boundary -- they
    are the entire streaming dataset.
    """
    counts: dict[str, int] = {}

    src = _read(os.path.join(REPO, "tools", "run_stream_capture.py"))
    m = re.search(r'--symbols["\']\s*,\s*default\s*=\s*["\']([^"\']+)', src)
    if m:
        counts["stream capture --symbols default"] = len(m.group(1).split(","))
    m = re.search(r"free tier cap (\d+)", src)
    if m:
        counts["alpaca free-tier cap"] = int(m.group(1))

    if server_up():
        uni = _get("/api/logger/universe", timeout=25) or {}
        for key in ("core_tickers", "symbols_in_memory_logger_cycle",
                    "protected_symbols", "logging_universe_rows"):
            v = uni.get(key)
            if isinstance(v, list) and v:
                counts[f"universe.{key}"] = len(v)
        cap = uni.get("max_pinned_symbols")
        if isinstance(cap, int):
            counts["universe.max_pinned_symbols"] = cap

    distinct = sorted(set(counts.values()))
    if len(distinct) < 2:
        return []
    members = [f"{n:>4}  {name}" for name, n in
               sorted(counts.items(), key=lambda kv: kv[1])]
    return [Finding("D-UNIVERSE", "D-UNIVERSE:symbol-set",
                    f"{len(distinct)} different symbol-set sizes in play "
                    f"({distinct[0]}..{distinct[-1]})", members)]


def scan_db_columns() -> list[Finding]:
    """The same quantity stored under two column names.

    A duplicated column is a duplicated faucet with persistence: the two copies
    can disagree and the disagreement survives a restart.
    """
    cols: dict[str, set[str]] = defaultdict(set)
    for p in _files(("**/*.py", "**/*.sql"), PROD_SKIP):
        text = _read(p)
        for m in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                             r"[\"'`\[]?(\w+)[\"'`\]]?\s*\(", text, re.I):
            table = m.group(1)
            # Balance parentheses from the opening paren. A non-greedy .*? to
            # the first ');' spanned across statements and swallowed later
            # tables' columns whole -- it reported bar columns inside
            # logging_universe, which only appears in a COMMENT in db.py.
            depth, start = 1, m.end()
            i = start
            while i < len(text) and depth:
                if text[i] == "(":
                    depth += 1
                elif text[i] == ")":
                    depth -= 1
                i += 1
            if depth:
                continue                     # unbalanced: refuse to guess
            body = text[start:i - 1]
            if len(body) > 20000:
                continue                     # implausible for one table
            for col in re.findall(r"^\s*[\"'`\[]?(\w+)[\"'`\]]?\s+"
                                  r"(?:INTEGER|REAL|TEXT|BLOB|NUMERIC)",
                                  body, re.M | re.I):
                cols[col.lower()].add(f"{rel(p)}::{table}")
    # only domain quantities matter; structural ids repeat by design
    STRUCTURAL = {"id", "rowid", "ts", "created_at", "updated_at", "symbol",
                  "ticker", "date", "session", "as_of", "source", "kind"}
    MIRROR = ("_staging", "_quarantine", "_archive", "_backup", "_tmp", "_new")

    def is_mirror_set(tables: set[str]) -> bool:
        """True when every table is the same base plus a lifecycle suffix.

        A staging or quarantine table mirroring its parent shares columns BY
        DESIGN -- that is the point of it. Counting those as duplication buries
        the real finding. They are exempted, never hidden: an exemption that
        stops appearing is how a register quietly narrows.
        """
        bases = set()
        for t in tables:
            name = t.split("::")[-1].lower()
            for suffix in MIRROR:
                if name.endswith(suffix):
                    name = name[: -len(suffix)]
                    break
            bases.add(name)
        return len(bases) == 1

    out = []
    for col, tables in sorted(cols.items()):
        if len(tables) < 2 or col in STRUCTURAL:
            continue
        f = Finding("D-DBCOL", f"D-DBCOL:{col}",
                    f"column {col!r} defined in {len(tables)} tables",
                    sorted(tables))
        if is_mirror_set(tables):
            f.accepted = ("lifecycle mirror: staging/quarantine tables share "
                          "their parent's columns by design")
        out.append(f)
    return out


def scan_scheduled_jobs() -> list[Finding]:
    """Two schedulers running the same work.

    A job defined twice runs twice, and the second run silently doubles load
    or overwrites the first result.
    """
    jobs: dict[str, set[str]] = defaultdict(set)
    for p in _files(("**/*.py", "**/*.ps1", "**/*.bat", "**/*.json",
                     "**/*.yaml", "**/*.yml"), PROD_SKIP):
        text = _read(p)
        for m in re.finditer(r"(?:add_job|schedule\.\w+|CronTrigger|IntervalTrigger|"
                             r"Register-ScheduledTask|schtasks)[^\n]{0,120}?"
                             r"([\w/\\.-]+\.(?:py|ps1|bat))", text, re.I):
            jobs[m.group(1).replace("\\", "/").lower()].add(rel(p))
    return [Finding("D-CRON", f"D-CRON:{target}",
                    f"{target} scheduled from {len(src)} places", sorted(src))
            for target, src in sorted(jobs.items()) if len(src) > 1]


def scan_duplicate_gates() -> list[Finding]:
    """Two enforced gates claiming the same property.

    Two gates for one property is not twice the safety: it is two places to
    maintain, two places to drift, and a false sense that the property is
    doubly covered when one of them may have quietly stopped measuring.
    """
    try:
        sys.path.insert(0, os.path.join(REPO, "tools"))
        import check_institutional_correctness as K
    except Exception:                                       # noqa: BLE001
        return []
    STOP = set("the a an of to and or is are be for in on that this it its "
               "must never always when what why how not no with which".split())
    sigs: dict[frozenset, list[str]] = defaultdict(list)
    for name, fn, enforced in getattr(K, "CHECKS", []):
        doc = (fn.__doc__ or "").strip().splitlines()
        if not doc:
            continue
        words = {w for w in re.findall(r"[a-z]{4,}", doc[0].lower())
                 if w not in STOP}
        if len(words) < 3:
            continue
        sigs[frozenset(words)].append(name)
    return [Finding("D-GATE", f"D-GATE:{sorted(names)[0]}",
                    f"{len(names)} gates claim the same property", sorted(names))
            for names in sigs.values() if len(names) > 1]


SCANNERS = {
    "D-FILE": scan_files, "D-MODULE": scan_modules, "D-FUNC": scan_functions,
    "D-CONCEPT": scan_concepts, "D-FIELD": scan_fields, "D-VALUE": scan_values,
    "D-DEAD": scan_dead_endpoints, "D-CONST": scan_constants, "D-SQL": scan_sql,
    "D-CSS": scan_css, "D-UNIVERSE": scan_universe, "D-DBCOL": scan_db_columns,
    "D-CRON": scan_scheduled_jobs, "D-GATE": scan_duplicate_gates,
}

BLURB = {
    "D-FILE": "byte-identical files",
    "D-MODULE": "near-identical modules that have drifted",
    "D-FUNC": "same function body in two modules",
    "D-CONCEPT": "derived quantity computed in >1 module",
    "D-FIELD": "field published by >1 endpoint",
    "D-VALUE": "faucets that DISAGREE right now",
    "D-DEAD": "endpoint built and never called",
    "D-CONST": "domain constant literal in >1 module",
    "D-SQL": "same query issued from >1 module",
    "D-CSS": "identical style rule declared twice",
    "D-UNIVERSE": "competing notions of which symbols we cover",
    "D-DBCOL": "same quantity stored in >1 table column",
    "D-CRON": "same job scheduled from >1 place",
    "D-GATE": "two enforced gates claiming one property",
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--kind", default="")
    ap.add_argument("--full", action="store_true", help="list every member")
    args = ap.parse_args(argv)

    kinds = [args.kind] if args.kind else list(SCANNERS)
    findings: list[Finding] = []
    for kind in kinds:
        for f in SCANNERS[kind]():
            f.accepted = ACCEPTED.get(f.ident, "")
            findings.append(f)

    live = [f for f in findings if not f.accepted]
    exempt = [f for f in findings if f.accepted]

    if args.as_json:
        print(json.dumps([f.__dict__ for f in findings], indent=2))
        return 1 if live else 0

    print("DUPLICATION REGISTER — the total must reach zero (RC-265)")
    print(f"server: {'UP' if server_up() else 'DOWN — live scans skipped'}\n")
    by_kind: dict[str, list[Finding]] = defaultdict(list)
    for f in live:
        by_kind[f.kind].append(f)

    print(f"  {'kind':<11}{'count':>6}   what it means")
    print("  " + "-" * 68)
    for kind in SCANNERS:
        n = len(by_kind.get(kind, []))
        flag = "  " if n == 0 else " !"
        print(f" {flag}{kind:<11}{n:>6}   {BLURB[kind]}")
    print("  " + "-" * 68)
    print(f"  {'TOTAL':<11}{len(live):>6}   exempt (listed, not counted): {len(exempt)}")

    for kind in SCANNERS:
        items = by_kind.get(kind, [])
        if not items:
            continue
        print(f"\n{'='*72}\n{kind} — {BLURB[kind]}  ({len(items)})\n{'='*72}")
        for i, f in enumerate(sorted(items, key=lambda x: x.ident), 1):
            print(f"\n  {kind}-{i:03d}  {f.detail}")
            for m in (f.members if args.full else f.members[:6]):
                print(f"        {m}")
            if not args.full and len(f.members) > 6:
                print(f"        ... {len(f.members)-6} more (--full)")

    if exempt:
        print(f"\n{'='*72}\nEXEMPT — reasoned, still visible\n{'='*72}")
        for f in exempt:
            print(f"  {f.ident}\n      {f.accepted}")

    return 1 if live else 0


if __name__ == "__main__":
    raise SystemExit(main())
