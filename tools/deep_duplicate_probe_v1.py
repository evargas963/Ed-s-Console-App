"""RC-326 probe: EXHAUSTIVE duplicate/inconsistency sweep over the tracked repo.

Three orthogonal detectors, because name matching finds only what was named the same:

  A. STRUCTURAL CLONES  — normalise every function body (identifiers and literals erased,
     control-flow shape kept), hash it, and group. Two functions with the same shape are
     the same computation written twice, whatever they are called.

  B. SEMANTIC FIELD COLLISIONS — normalise every payload/attribute field name (drop known
     namespace prefixes, singular/plural, abbreviations) and group. `overnight_low`,
     `on_low`, `OVERNIGHT_LOW` and `kl_on_low` are one concept under four spellings.

  C. RETURNED-EXPRESSION CLONES — the actual arithmetic returned by a function, normalised
     to its operator tree. Catches the same formula under different variable names.
"""
from __future__ import annotations

import ast
import hashlib
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

#: Derived from THIS file's location, never from a developer machine's absolute path.
#: A baked-in drive-letter literal used to live here, which made the module unimportable
#: on any other checkout: on the required Linux runner `tracked()` passed that path to
#: subprocess as cwd and raised FileNotFoundError at IMPORT,
#: which aborted pytest COLLECTION — so the entire required suite died on one developer's
#: directory layout rather than on any test. Every other tool here resolves its root this
#: way; this one had drifted, and nothing measured the drift until CI ran on Linux.
REPO = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SKIP = ("tests/", "research/", "arch_competition/", "scratchpad/", "governance/archive/")


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z", "--", "*.py"],
                         cwd=REPO, capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p and not p.startswith(SKIP)]


class _Norm(ast.NodeTransformer):
    """Erase identity, keep shape."""
    def visit_Name(self, n):  # noqa: N802
        return ast.copy_location(ast.Name(id="_", ctx=n.ctx), n)

    def visit_Attribute(self, n):  # noqa: N802
        self.generic_visit(n)
        return ast.copy_location(ast.Attribute(value=n.value, attr="_", ctx=n.ctx), n)

    def visit_Constant(self, n):  # noqa: N802
        return ast.copy_location(ast.Constant(value=0), n)

    def visit_arg(self, n):  # noqa: N802
        return ast.copy_location(ast.arg(arg="_", annotation=None), n)


def shape(node) -> str:
    try:
        cloned = ast.parse(ast.unparse(node))
    except Exception:  # noqa: BLE001
        return ""
    normed = _Norm().visit(cloned)
    ast.fix_missing_locations(normed)
    try:
        return hashlib.blake2b(ast.dump(normed).encode(), digest_size=12).hexdigest()
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------- A: structural clones
groups: dict[str, list[str]] = defaultdict(list)
sizes: dict[str, int] = {}
fields_seen: dict[str, set[str]] = defaultdict(set)
ret_groups: dict[str, list[str]] = defaultdict(list)

FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{2,}$")

for rel in tracked():
    p = REPO / rel
    if not p.exists():
        continue
    src = p.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = [s for s in fn.body if not (isinstance(s, ast.Expr)
                                               and isinstance(s.value, ast.Constant))]
            if len(body) < 3:
                continue
            mod = ast.Module(body=body, type_ignores=[])
            h = shape(mod)
            if h:
                groups[h].append(f"{rel}:{fn.lineno} {fn.name}")
                sizes[h] = len(body)
            for st in ast.walk(fn):
                if isinstance(st, ast.Return) and isinstance(st.value, ast.BinOp):
                    rh = shape(st.value)
                    if rh:
                        ret_groups[rh].append(f"{rel}:{st.lineno} {fn.name}")
    # B: field names
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if FIELD_RE.match(n.value):
                fields_seen[n.value].add(rel)

print("=" * 78)
print("A. STRUCTURAL CLONES — same computation shape, different names")
clones = {h: v for h, v in groups.items() if len(set(v)) > 1 and sizes.get(h, 0) >= 5}
print(f"   clone groups (>=5 statements, 2+ sites): {len(clones)}")
for h, v in sorted(clones.items(), key=lambda kv: -sizes.get(kv[0], 0))[:12]:
    print(f"   [{sizes[h]} stmts] {len(set(v))} sites")
    for s in sorted(set(v))[:4]:
        print(f"        {s}")

print()
print("=" * 78)
print("C. IDENTICAL RETURNED FORMULAS — same arithmetic, different variables")
rc = {h: v for h, v in ret_groups.items() if len(set(v)) > 2}
print(f"   formula groups (3+ sites): {len(rc)}")
for h, v in sorted(rc.items(), key=lambda kv: -len(set(kv[1])))[:8]:
    print(f"   {len(set(v))} sites:")
    for s in sorted(set(v))[:4]:
        print(f"        {s}")

print()
print("=" * 78)
print("B. SEMANTIC FIELD COLLISIONS — one concept, several spellings")
PREFIX = re.compile(r"^(kl_|em_|mc_|tv_|cv2_|ov_|f_|d_|_)+")
ABBR = {"on": "overnight", "pd": "priorday", "hi": "high", "lo": "low",
        "vol": "volume", "px": "price", "val": "valuearea_low", "vah": "valuearea_high",
        "poc": "pointofcontrol", "gex": "gammaexposure", "dex": "deltaexposure",
        "oi": "openinterest", "em": "expectedmove", "vwap": "vwap"}


def canon(name: str) -> str:
    s = PREFIX.sub("", name.lower())
    parts = [ABBR.get(t, t) for t in s.split("_") if t]
    return "".join(sorted(parts))


buckets: dict[str, set[str]] = defaultdict(set)
for f in fields_seen:
    buckets[canon(f)].add(f)
coll = {k: v for k, v in buckets.items() if len(v) > 1}
print(f"   concepts with 2+ spellings: {len(coll)}")
for k, v in sorted(coll.items(), key=lambda kv: -len(kv[1]))[:18]:
    print(f"   {k:26s} {sorted(v)}")
