#!/usr/bin/env python3
"""RC-325 PHASE A — mechanically derive the producer-candidate universe, repo-wide.

The mission's denominators cannot come from a remembered concept list. This walks the whole
tracked production tree and classifies EVERY function/method as a producer candidate or not,
by what it DOES, so `PRODUCTION_FILES_UNAUDITED` is a measured number rather than a claim.

A function is a PRODUCER_CANDIDATE when it materially establishes new semantic truth:
arithmetic on two or more inputs, an aggregation, a comparison that yields a state/label, a
threshold, a classification, an encoding, or a ranking. Pure transport (return a dict of
already-computed values), pure formatting (f-strings, .2f), and pure I/O are not.

    .venv/Scripts/python.exe tools/producer_inventory_v1.py
    .venv/Scripts/python.exe tools/producer_inventory_v1.py --json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Layers. Test oracles and research are NOT production authority (SP-06) but are counted.
LAYERS = (
    ("frontend", ("static/",)),
    ("tests", ("tests/",)),
    ("tools", ("tools/",)),
    ("research", ("research/", "arch_competition/", "verification/")),
    ("calibration", ("calibration/",)),
    ("training", ("features/", "ml_", "lstm_", "multi_horizon", "bayesian_fusion")),
    ("governance", ("governance/",)),
)


def layer_of(rel: str) -> str:
    for name, prefixes in LAYERS:
        if any(rel.startswith(p) or Path(rel).name.startswith(p) for p in prefixes):
            return name
    return "backend"


PRODUCTION_LAYERS = {"backend", "training", "calibration", "frontend"}


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p]


#: Names that mean "I established something", used only as a secondary signal.
_VERB = ("calc", "comput", "deriv", "transform", "normal", "classif", "aggregat",
         "estimat", "infer", "score", "encod", "map_", "select", "determin", "synth",
         "reconstruct", "convert", "calibrat", "threshold", "label", "rank", "filter",
         "resolve", "pick", "build", "bucket", "detect", "measure")


def is_producer(fn: ast.AST) -> tuple[bool, str]:
    """Classify by BEHAVIOUR first, name second."""
    arith = agg = cmpst = enc = 0
    returns_literal_dict_only = True
    for n in ast.walk(fn):
        if isinstance(n, ast.BinOp) and isinstance(
                n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.FloorDiv)):
            arith += 1
        elif isinstance(n, ast.AugAssign):
            agg += 1
        elif isinstance(n, ast.Call) and getattr(n.func, "id", "") in (
                "sum", "min", "max", "sorted", "round", "abs", "len"):
            agg += 1
        elif isinstance(n, ast.Compare):
            cmpst += 1
        elif isinstance(n, (ast.IfExp, ast.ListComp, ast.DictComp, ast.GeneratorExp)):
            enc += 1
        if isinstance(n, ast.Return) and n.value is not None:
            if not isinstance(n.value, (ast.Dict, ast.Name, ast.Constant, ast.Attribute)):
                returns_literal_dict_only = False
    named = any(v in fn.name.lower() for v in _VERB)
    if arith >= 2 or agg >= 2:
        return True, "arithmetic/aggregation"
    if arith >= 1 and cmpst >= 1:
        return True, "arithmetic+branching"
    if enc >= 1 and cmpst >= 2:
        return True, "classification/encoding"
    if named and (arith or agg or cmpst or enc):
        return True, "derivation-named with derivation body"
    if not returns_literal_dict_only and (arith or agg):
        return True, "computed return"
    return False, "transport/format/io"


#: RC-327: a derivation in JavaScript or SQL is a producer. Scanning only .py made
#: `EXECUTABLE_PRODUCTION_FILES_UNSCANNED` an omission rather than a measured zero.
_JS_DERIVE = re.compile(
    r"(?:^|[^\w.])(?:[\w$.\[\]]+\s*(?:\+=|-=|\*=|/=)\s*[\w$.\[\]]+"      # accumulation
    r"|[\w$.\[\]]+\s*=\s*[\w$.\[\]()]+\s*[-+*/]\s*[\w$.\[\]()]+"          # arithmetic assign
    r"|\.reduce\s*\(|Math\.(?:max|min|abs|sqrt|pow|round)\s*\("           # aggregation
    r"|\?\s*[^:]{1,40}\s*:\s*)", re.M)                                    # ternary classify
_SQL_DERIVE = re.compile(
    r"\b(?:SUM|AVG|COUNT|MIN|MAX|STDDEV|PERCENTILE|NTILE|RANK|ROW_NUMBER)\s*\("
    r"|\bCASE\s+WHEN\b|\bOVER\s*\(", re.I)
_SCRIPT_BLOCK = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S | re.I)


def _scan_text_layer(rel: str, text: str, kind: str) -> list[dict]:
    """Line-level producer candidates for non-Python executables."""
    pat = _SQL_DERIVE if kind == "sql" else _JS_DERIVE
    body = text
    if kind == "html":
        body = "\n".join(m.group(1) for m in _SCRIPT_BLOCK.finditer(text))
        if not body.strip():
            return []
    out = []
    for i, line in enumerate(body.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith(("//", "*", "/*", "--")):
            continue
        if pat.search(s):
            out.append({"file": rel, "symbol": f"line {i}", "line": i,
                        "layer": layer_of(rel), "reason": f"{kind}-derivation",
                        "production": layer_of(rel) in PRODUCTION_LAYERS})
    return out


#: RC-327: every tracked file lands in exactly one bucket, so the denominator reconciles.
#: Extensions that can carry executable derivation logic.
_EXEC_EXT = {".py": "python", ".js": "js", ".html": "html", ".sql": "sql",
             ".mjs": "js", ".jsx": "js", ".ts": "js", ".ipynb": "notebook",
             ".bat": "script", ".ps1": "script", ".sh": "script"}
#: Non-executable data/doc surfaces. Excluded WITH a reason, never silently.
_NONEXEC_REASON = {
    ".md": "documentation, not executed",
    ".json": "data/config, no expression evaluation in this repo",
    ".jsonl": "append-only data records",
    ".csv": "tabular data", ".txt": "text data", ".log": "log output",
    ".yaml": "declarative config consumed by pre-commit, no formulas",
    ".yml": "declarative config", ".cfg": "declarative config",
    ".toml": "declarative config", ".ini": "declarative config",
    ".png": "binary image", ".jpg": "binary image", ".ico": "binary icon",
    ".css": "presentation styling, no derivation", ".gitignore": "vcs metadata",
    ".pkl": "binary artefact", ".joblib": "binary artefact", ".db": "binary database",
    ".zip": "binary archive", ".mdc": "editor rule text", ".pt": "binary model",
}


def reconcile(all_tracked: list[str]) -> dict:
    """Bucket EVERY tracked file: executable-scanned, executable-unscanned, or excluded."""
    buckets: dict[str, list[str]] = {k: [] for k in
                                     ("python", "js", "html", "sql", "notebook", "script")}
    excluded: list[tuple[str, str, str]] = []
    unknown: list[str] = []
    for rel in all_tracked:
        ext = Path(rel).suffix.lower()
        if ext in _EXEC_EXT:
            buckets[_EXEC_EXT[ext]].append(rel)
        elif ext in _NONEXEC_REASON:
            excluded.append((rel, ext or "(none)", _NONEXEC_REASON[ext]))
        else:
            unknown.append(rel)          # NOT_PROVEN: neither proven executable nor excluded
    return {"buckets": buckets, "excluded": excluded, "unknown": unknown,
            "repository_files_total": len(all_tracked)}


def scan() -> dict:
    all_tracked = tracked()
    rec = reconcile(all_tracked)
    files = rec["buckets"]["python"]
    js = rec["buckets"]["js"]
    html = rec["buckets"]["html"]
    sql = rec["buckets"]["sql"]
    text_rows: list[dict] = []
    for rel, kind in ([(f, "js") for f in js] + [(f, "html") for f in html]
                      + [(f, "sql") for f in sql]):
        p = REPO / rel
        if not p.exists():
            continue
        text_rows += _scan_text_layer(rel, p.read_text(encoding="utf-8", errors="replace"),
                                      kind)
    rows, per_layer, unparsed = list(text_rows), Counter(), []
    for rel in files:
        p = REPO / rel
        if not p.exists():
            continue
        lay = layer_of(rel)
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            unparsed.append(rel)
            continue
        per_layer[lay] += 1
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            ok, why = is_producer(fn)
            if ok:
                rows.append({"file": rel, "symbol": fn.name, "line": fn.lineno,
                             "layer": lay, "reason": why,
                             "production": lay in PRODUCTION_LAYERS})
    return {"files_total": len(files), "files_parsed": sum(per_layer.values()),
            "files_unparsed": unparsed, "per_layer_files": dict(per_layer),
            "js_files": len(js), "html_files": len(html), "sql_files": len(sql),
            "reconcile": rec, "candidates": rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = scan()
    if args.json:
        print(json.dumps(r, indent=1)[:200000])
        return 0
    cands = r["candidates"]
    prod = [c for c in cands if c["production"]]
    by_layer = Counter(c["layer"] for c in cands)
    print("PHASE A — mechanically derived producer-candidate universe")
    tot = r["files_total"] + r["js_files"] + r["html_files"] + r["sql_files"]
    print(f"  EXECUTABLE_PRODUCTION_FILES_TOTAL     = {tot}")
    print(f"  EXECUTABLE_PRODUCTION_FILES_SCANNED   = {tot - len(r['files_unparsed'])}")
    print(f"  EXECUTABLE_PRODUCTION_FILES_UNSCANNED = {len(r['files_unparsed'])}"
          f"  {r['files_unparsed'][:3]}")
    print(f"    PYTHON_FILES={r['files_total']}  JS_FILES={r['js_files']}  "
          f"HTML_SCRIPT_FILES={r['html_files']}  SQL_FILES={r['sql_files']}")
    print(f"  PRODUCER_CANDIDATES_TOTAL   = {len(cands)}")
    print(f"    of which production-layer = {len(prod)}")
    print("  PRODUCER_CANDIDATES_CLASSIFIED  = 0   (Phase B not run)")
    print(f"  PRODUCER_CANDIDATES_NOT_PROVEN  = {len(cands)}")
    print("  by layer:")
    for lay, n in by_layer.most_common():
        print(f"      {lay:12s} {n}")
    print("  by detection reason:")
    for why, n in Counter(c["reason"] for c in cands).most_common():
        print(f"      {why:34s} {n}")

    # ---- RC-327 RECONCILIATION: the numbers must add up or Phase A is NOT_COMPLETE ----
    rec = r["reconcile"]
    b = rec["buckets"]
    print("\n  RECONCILIATION")
    print(f"    REPOSITORY_FILES_TOTAL          = {rec['repository_files_total']}")
    exec_total = sum(len(v) for v in b.values())
    scanned = len(b['python']) + len(b['js']) + len(b['html']) + len(b['sql'])
    unscanned = len(b['notebook']) + len(b['script'])
    print(f"    EXECUTABLE_PRODUCTION_FILES_TOTAL     = {exec_total}")
    print(f"    EXECUTABLE_PRODUCTION_FILES_SCANNED   = {scanned}")
    print(f"    EXECUTABLE_PRODUCTION_FILES_UNSCANNED = {unscanned}"
          f"  (notebook={len(b['notebook'])} script={len(b['script'])})")
    print(f"    EXECUTABLE_PRODUCTION_FILES_EXCLUDED  = {len(rec['excluded'])}")
    print(f"    UNKNOWN_EXTENSION_NOT_PROVEN          = {len(rec['unknown'])}"
          f"  {[u for u in rec['unknown'][:5]]}")
    bucket_sum = exec_total + len(rec["excluded"]) + len(rec["unknown"])
    print(f"    BUCKET_SUM                      = {bucket_sum}")
    print(f"    DIFFERENCE_FROM_REPO_TOTAL      = "
          f"{bucket_sum - rec['repository_files_total']}")

    per_lang = Counter()
    for c in cands:
        f = c["file"]
        per_lang["html_inline" if f.endswith(".html")
                 else "js" if f.endswith(".js")
                 else "sql" if f.endswith(".sql") else "python"] += 1
    print("\n    PRODUCER_CANDIDATES_TOTAL       = %d" % len(cands))
    for k in ("python", "js", "html_inline", "sql"):
        print(f"      {k:14s} = {per_lang.get(k, 0)}")
    print(f"    SUM_OF_LAYER_COUNTS             = {sum(per_lang.values())}")
    print(f"    DIFFERENCE_FROM_TOTAL           = {sum(per_lang.values()) - len(cands)}")
    with_loc = sum(1 for c in cands if c.get("file") and c.get("line"))
    print(f"    CANDIDATES_WITH_FILE_AND_LOCATION    = {with_loc}")
    print(f"    CANDIDATES_WITHOUT_FILE_AND_LOCATION = {len(cands) - with_loc}")

    ok = (unscanned == 0 and len(rec["unknown"]) == 0
          and bucket_sum == rec["repository_files_total"]
          and sum(per_lang.values()) == len(cands) and with_loc == len(cands))
    print(f"\n  PHASE_A_STATUS = {'COMPLETE' if ok else 'NOT_COMPLETE'}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
