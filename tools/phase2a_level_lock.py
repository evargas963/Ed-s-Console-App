"""Phase 2A single-computation lock — the guard that reads CALLS, not field writes.

WHY A FIELD-WRITER LOCK WAS NOT ENOUGH (measured, 2026-08-08)
    `tests/test_levels_single_producer_v1.py` already enforces "exactly one writer of
    each SSOT payload key", and it was green while /api/levels served overnight
    773.3975/773.3975 and /api/liquidity-snapshot served 773.40/772.55 for the same
    ticker at the same instant. It was green because nothing wrote a forbidden KEY —
    each endpoint legitimately wrote its own payload, having independently INVOKED the
    same engine helpers over a different bar input. The duplication lived in the call
    graph, one layer below where the lock was looking.

WHAT THIS ENFORCES
    1. COMPUTATION: the Phase 2A helpers are invoked from exactly one production site,
       `liquidity_value_engine.build_price_level_snapshot`, plus the explicitly declared
       checkpoint-scoped builders. Alias-resolved, so `from ... import compute_session_vwap
       as _v`, `f = compute_session_vwap`, `eng.compute_session_vwap` and a WRAPPER
       function that forwards to one all count as the same invocation under another name.
    2. VALUE CARRIAGE: a Phase 2A level id appearing in a payload row — including inside
       list literals such as `levels: [{"id": ..., "price": ...}]`, and including ids
       aliased through a constant — must take its number from the canonical snapshot,
       never from a literal, a helper call or an unrelated expression.
    3. BROWSER: no in-page reconstruction of the Phase 2A families. The browser draws
       carried server results only.

Escape (visible, per-line): ``# phase2a-level-ok: <reason>``
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

ESCAPE = "# phase2a-level-ok:"
JS_ESCAPE = "phase2a-level-ok:"

#: The canonical Phase 2A level ids. Duplicated from liquidity_value_engine's registry
#: deliberately: the lock must still fire if someone edits the registry to get green.
PHASE2A_IDS: frozenset[str] = frozenset({
    "PDH", "PDL", "PDC", "PD_POC", "PD_VAH", "PD_VAL",
    "OVERNIGHT_HIGH", "OVERNIGHT_LOW",
    "ORB_HIGH", "ORB_LOW", "ORB_MID",
    "VWAP", "VWAP_P1", "VWAP_M1", "VWAP_P2", "VWAP_M2",
    "TODAY_POC", "TODAY_VAH", "TODAY_VAL",
})

#: The engine functions that ARE the Phase 2A computation.
CANONICAL_HELPERS: frozenset[str] = frozenset({
    "get_previous_day_levels",
    "get_overnight_levels",
    "compute_opening_range",
    "compute_session_vwap",
    "compute_session_vwap_path",
    "compute_vwap_bands",
    "compute_volume_profile_levels",
})

#: (module rel path, enclosing function) permitted to invoke a canonical helper.
#: Each entry is a DECLARED producer with a declared scope — adding one is a deliberate
#: edit to this table, not something a new endpoint can do by accident.
ALLOWED_COMPUTATION_SITES: frozenset[tuple[str, str]] = frozenset({
    # THE canonical producer for the repo-wide (ticker, level_id, scope, generation).
    ("liquidity_value_engine.py", "build_price_level_snapshot"),
    # The scalar VWAP is the last point of the one accumulation.
    ("liquidity_value_engine.py", "compute_session_vwap"),
    # CHECKPOINT-SCOPED builders. These measure the same concepts through a fixed
    # cutoff (premarket / 09:45 / 10:30 / 14:00) — a legitimately different number, so
    # their output travels under `<ID>@checkpoint:<type>` and is never compared against
    # the canonical id. `build_live_snapshot` self-computes ONLY when no canonical
    # snapshot is handed in, which is historical replay, never a live serving path.
    ("liquidity_value_engine.py", "build_premarket_snapshot"),
    ("liquidity_value_engine.py", "build_opening_snapshot"),
    ("liquidity_value_engine.py", "build_midday_snapshot"),
    ("liquidity_value_engine.py", "build_afternoon_snapshot"),
    ("liquidity_value_engine.py", "build_live_snapshot"),
    # RESEARCH REPLAY, per historical session. Not a serving path and never rendered
    # beside /api/levels: each study session is its own generation over banked bars, and
    # the outputs land in reports/, not in an API, a screen, a model feature or a row.
    ("tools/lp01_touch_study_v1.py", "_levels_for_session"),
    ("tools/liquidity_synthesis_experiments_v1.py", "_levels_for_session"),
})

#: Expression tokens that mark a value as READ from the canonical snapshot rather than
#: produced locally. A carried value is legal in a levels row; a computed one is not.
CARRIAGE_TOKENS: tuple[str, ...] = (
    "snapshot", "snap", "canonical", "carried", "carry_snapshot_levels",
    "to_contract_dict", "price_level", "level_value", "lv.price", "value.price",
)

#: Trees scanned. Tests, scratchpad and governance inventories are excluded: a test
#: MUST be able to call the helpers directly, and the inventories only quote names.
SCAN_DIRS: tuple[str, ...] = ("", "features", "planes", "tools")
SKIP_PARTS: frozenset[str] = frozenset({
    "tests", "scratchpad", "governance", "backups", "data", "models", "reports",
    ".git", "venv", ".venv", "node_modules", "archive",
})
#: This module names every helper in prose and in its own data tables.
SKIP_FILES: frozenset[str] = frozenset({"tools/phase2a_level_lock.py"})


def _norm(rel) -> str:
    return str(rel).replace("\\", "/").strip()


def _escaped(source: str, lineno: int) -> bool:
    lines = source.splitlines()
    if 1 <= lineno <= len(lines):
        return ESCAPE in lines[lineno - 1]
    return False


class _AliasResolver(ast.NodeVisitor):
    """Maps every local name that reaches a canonical helper back to that helper.

    Covers: `from m import h as a`, `import m as e` (→ `e.h`), `a = h`, `a = m.h`,
    `a = getattr(m, "h")`, and WRAPPER functions whose body calls a helper — because
    "the same helper called under another function name" is the exact evasion the
    operator named, and a wrapper is the cheapest form of it.
    """

    def __init__(self) -> None:
        self.alias_to_helper: dict[str, str] = {h: h for h in CANONICAL_HELPERS}
        self.wrapper_bodies: dict[str, set[str]] = {}
        self._fn_stack: list[str] = []

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for a in node.names:
            if a.name in CANONICAL_HELPERS:
                self.alias_to_helper[a.asname or a.name] = a.name
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        target = None
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
        if target:
            resolved = self._resolve_value(node.value)
            if resolved:
                self.alias_to_helper[target] = resolved
        self.generic_visit(node)

    def _resolve_value(self, value: ast.AST) -> str | None:
        if isinstance(value, ast.Name) and value.id in self.alias_to_helper:
            return self.alias_to_helper[value.id]
        if isinstance(value, ast.Attribute) and value.attr in CANONICAL_HELPERS:
            return value.attr
        if isinstance(value, ast.Call):
            fn = value.func
            is_getattr = isinstance(fn, ast.Name) and fn.id == "getattr"
            if is_getattr and len(value.args) >= 2:
                arg = value.args[1]
                if isinstance(arg, ast.Constant) and arg.value in CANONICAL_HELPERS:
                    return str(arg.value)
        return None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._fn_stack.append(node.name)
        called: set[str] = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Call):
                name = _call_name(n)
                if name in CANONICAL_HELPERS or name in self.alias_to_helper:
                    called.add(self.alias_to_helper.get(name, name))
        if called:
            self.wrapper_bodies[node.name] = called
        self.generic_visit(node)
        self._fn_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]


def _call_name(node: ast.Call) -> str:
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id
    return getattr(fn, "attr", "") or ""


def _enclosing_functions(tree: ast.AST) -> dict[int, str]:
    """line number -> nearest enclosing def name (module level → '<module>')."""
    owner: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            for ln in range(node.lineno, (end or node.lineno) + 1):
                owner[ln] = node.name
    return owner


def level_computation_violations(rel_path: str, source: str) -> list[str]:
    """Every invocation of a Phase 2A helper outside the declared producer sites."""
    rel = _norm(rel_path)
    if rel in SKIP_FILES:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"{rel}: unparseable, the Phase 2A computation lock cannot see it ({e})"]

    resolver = _AliasResolver()
    resolver.visit(tree)
    owner = _enclosing_functions(tree)
    # A wrapper that forwards to a helper is itself an invocation of that helper — that
    # is the "same helper under another function name" evasion. A DECLARED producer is
    # not a wrapper: calling it is carriage of the one computation, which is the point.
    alias = dict(resolver.alias_to_helper)
    for wrapper, helpers in resolver.wrapper_bodies.items():
        if (rel, wrapper) in ALLOWED_COMPUTATION_SITES:
            continue
        if wrapper not in alias and helpers:
            alias[wrapper] = sorted(helpers)[0]

    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        helper = alias.get(name)
        if helper is None:
            continue
        fn = owner.get(node.lineno, "<module>")
        if (rel, fn) in ALLOWED_COMPUTATION_SITES:
            continue
        if _escaped(source, node.lineno):
            continue
        under = "" if name == helper else f" (aliased as {name!r})"
        out.append(
            f"{rel}:{node.lineno}: {fn}() invokes the Phase 2A computation "
            f"{helper}{under} — a SECOND materialization of "
            f"(ticker, level_id, semantic_scope, generation). Carry the value from the "
            f"canonical PriceLevelSnapshot instead "
            f"(liquidity_value_engine.carry_snapshot_levels), or declare the site with "
            f"its own distinct scope in ALLOWED_COMPUTATION_SITES."
        )
    return out


def _dict_key_value(d: ast.Dict, key: str) -> ast.AST | None:
    for k, v in zip(d.keys, d.values):
        if isinstance(k, ast.Constant) and k.value == key:
            return v
    return None


def _resolve_id_constant(node: ast.AST | None, const_alias: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return const_alias.get(node.id)
    return None


def _string_constant_aliases(tree: ast.AST) -> dict[str, str]:
    """NAME = "VWAP" bindings, so an id hidden behind an alias is still an id."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    out[tgt.id] = node.value.value
    return out


def level_alias_value_violations(rel_path: str, source: str) -> list[str]:
    """Numeric values attached to a Phase 2A id must be CARRIED, not produced.

    Walks INTO list literals, so `levels: [{"id": "VWAP", "price": <expr>}]` is scanned
    row by row rather than treated as one opaque value, and resolves an id given through
    a constant alias.
    """
    rel = _norm(rel_path)
    if rel in SKIP_FILES:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    const_alias = _string_constant_aliases(tree)
    owner = _enclosing_functions(tree)
    resolver = _AliasResolver()
    resolver.visit(tree)

    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        id_node = _dict_key_value(node, "id") or _dict_key_value(node, "level_id")
        lid = _resolve_id_constant(id_node, const_alias)
        if lid not in PHASE2A_IDS:
            continue
        for value_key in ("price", "value", "v", "level", "px"):
            val = _dict_key_value(node, value_key)
            if val is None:
                continue
            if _escaped(source, getattr(val, "lineno", node.lineno)):
                continue
            expr = ast.unparse(val) if hasattr(ast, "unparse") else ""
            if any(tok in expr for tok in CARRIAGE_TOKENS):
                continue
            reason = None
            if isinstance(val, ast.Constant) and isinstance(val.value, (int, float)):
                reason = f"a hardcoded number ({val.value!r})"
            else:
                for sub in ast.walk(val):
                    if isinstance(sub, ast.Call):
                        nm = _call_name(sub)
                        if resolver.alias_to_helper.get(nm):
                            reason = (f"a live call to "
                                      f"{resolver.alias_to_helper[nm]} (as {nm!r})")
                            break
            if reason is None:
                continue
            fn = owner.get(getattr(val, "lineno", node.lineno), "<module>")
            out.append(
                f"{rel}:{getattr(val, 'lineno', node.lineno)}: {fn}() emits level "
                f"{lid!r} with {reason} — a level row must carry the canonical "
                f"snapshot's value for this (ticker, level_id, semantic_scope, "
                f"generation), not produce its own."
            )
    return out


#: Browser-side reconstruction shapes for the Phase 2A families. Kept as explicit
#: patterns rather than a vague "no math in JS" so the failure names what it found.
_JS_RECONSTRUCTION: tuple[tuple[str, str], ...] = (
    (r"\(\s*b\.h\s*\+\s*b\.l\s*\+\s*b\.c\s*\)\s*/\s*3",
     "typical-price accumulation — an in-page VWAP"),
    (r"\(\s*\w+\.high\s*\+\s*\w+\.low\s*\+\s*\w+\.close\s*\)\s*/\s*3",
     "typical-price accumulation — an in-page VWAP"),
    (r"days\s*\[\s*days\.length\s*-\s*2\s*\]",
     "prior-session grouping — an in-page prior-day family"),
    (r"vwap\.push\s*\(", "an in-page VWAP series being built"),
)


def client_level_reconstruction_violations(rel_path: str, text: str) -> list[str]:
    """The browser draws carried server results only."""
    rel = _norm(rel_path)
    out: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if JS_ESCAPE in line:
            continue
        for pattern, what in _JS_RECONSTRUCTION:
            if re.search(pattern, line):
                out.append(
                    f"{rel}:{lineno}: {what} — Phase 2A levels are CARRIED from "
                    f"/api/levels (levels[] and vwap_path); the browser must not "
                    f"reconstruct them."
                )
                break
    return out


def _tracked_or_staged(repo: Path) -> set[str]:
    """Paths git knows about: the index, plus anything staged in this commit.

    RC-307/RC-323: repo-wide means the GIT INDEX, never a filesystem walk. This gate's
    first run flagged `tools/_tmp_review_probe.py` — untracked audit scratch that the
    repository does not contain — which is the third occurrence of that class after
    tests/test_coh_sa2_et_authority.py and tests/test_calibration_bypass_closure.py. A
    hand-maintained SKIP list is correct only on the day it is written; the index is the
    definition. Staged-but-new files are included so a duplicate cannot be introduced in
    the very commit the gate is guarding.
    """
    out: set[str] = set()
    for args in (["git", "ls-files", "-z"],
                 ["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"]):
        proc = subprocess.run(args, cwd=repo, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"{' '.join(args)} failed, so the scan scope is unknown: "
                               f"{proc.stderr.strip()[:160]}")
        out.update(p for p in proc.stdout.split("\0") if p)
    return out


def _python_files(repo: Path) -> list[Path]:
    """Tracked .py files under SCAN_DIRS. SCOPE IS THE INDEX (RC-274 -> RC-286 -> RC-307).

    This used to walk the filesystem and then drop whatever was not tracked. That produced
    the right answer, but it still enumerated disk to do it — so the gate's cost, and its
    exposure to scratch litter, scaled with the working directory rather than the
    repository. Iterating the tracked set directly is the same answer without the walk.
    Root ("" in SCAN_DIRS) stays NON-recursive, as the glob/rglob split encoded.
    """
    seen: list[Path] = []
    for rel_s in _tracked_or_staged(repo):
        if not rel_s.endswith(".py"):
            continue
        rel = Path(rel_s)
        parents = rel.parts[:-1]
        if set(parents) & SKIP_PARTS:
            continue
        in_scope = (not parents and "" in SCAN_DIRS) or (
            bool(parents) and parents[0] in SCAN_DIRS)
        if not in_scope:
            continue
        seen.append(repo / rel)
    return sorted(set(seen))


def scan_repo(repo: Path | None = None) -> list[str]:
    """Every Phase 2A violation in the tree, as printable strings."""
    root = repo or REPO
    out: list[str] = []
    for path in _python_files(root):
        rel = _norm(path.relative_to(root))
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out.extend(level_computation_violations(rel, src))
        out.extend(level_alias_value_violations(rel, src))
    static_dir = root / "static"
    if static_dir.is_dir():
        for path in sorted(static_dir.glob("*.html")):
            rel = _norm(path.relative_to(root))
            try:
                txt = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            out.extend(client_level_reconstruction_violations(rel, txt))
    return out


def main(argv: list[str] | None = None) -> int:
    findings = scan_repo(REPO)
    if not findings:
        print("phase2a-level-lock: PASS — one computation, one materialization, "
              "carried everywhere.")
        return 0
    print(f"phase2a-level-lock: {len(findings)} violation(s)")
    for f in findings:
        print(f"  {f}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
