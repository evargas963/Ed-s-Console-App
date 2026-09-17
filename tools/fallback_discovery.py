#!/usr/bin/env python3
"""Repo-wide fallback-behavior DISCOVERY scanner (no-fallback mechanical lock mission).

This is the MECHANICAL, syntactic half of discovery: it walks every git-tracked source
surface in scope (Python, JS/JSX/MJS, inline HTML <script>, .sql files and inline SQL
strings inside Python, PowerShell, batch) and flags every location matching a KNOWN
fallback-shaped pattern. It does NOT itself decide FALLBACK vs NOT_FALLBACK -- that is a
semantic judgment call this script deliberately leaves to a human/agent adjudication pass
(see reports/no_fallback_inventory.json), because "every use of `or`, a default, or
exception handling" is explicitly NOT a fallback per se (mission instruction). What this
script guarantees is that no candidate location is silently skipped: every hit gets a
stable ID and is emitted for adjudication, defaulting to NOT_PROVEN until a human/agent
adjudicator sets `adjudication` explicitly.

A location is flagged as a CANDIDATE when a syntactic fallback-shaped construct's
left-hand/target expression references an identifier that looks like a SEMANTIC domain
field (see _SEMANTIC_TERMS) rather than a purely technical/plumbing parameter (timeout,
retries, buffer size, worker count, ...). This keeps the raw candidate count sane enough
for real adjudication instead of drowning in thousands of harmless technical defaults --
but the term list is intentionally broad and any match is still just a CANDIDATE, subject
to human/agent semantic adjudication, never a final verdict by itself.

CANDIDATE IDENTITY (operator correction, point 5, 2026-09-17): a candidate's `id` is a
deterministic fingerprint derived from (repo-relative file, enclosing symbol/context,
detector pattern, a normalized AST dump of the matched expression -- position-independent,
so renaming a variable elsewhere or reflowing whitespace never moves it -- and the guessed
semantic target), never from scan/iteration order. The PRIOR scheme assigned sequential
`FB-NNNNN` IDs purely from the order files were visited and nodes were walked -- inserting
or deleting so much as one candidate anywhere earlier in that walk silently renumbered
every later one, so an adjudication recorded against "FB-00519" could point at a
completely different, unrelated piece of code after the very next regeneration, and
nothing would detect the mismatch. Under fingerprint identity this is structurally
impossible: if the underlying expression changes, its ID changes; an adjudication that
references a since-changed candidate's old ID simply finds no match in a fresh scan
(a loud, visible "stale reference", never a silent misapplication to different code) --
see tools/apply_adjudication.py's own hard check for this. `line` is retained purely as
human-navigation metadata and is NEVER part of identity.

Usage:
    python tools/fallback_discovery.py --out reports/no_fallback_discovery_raw.json

Exits 0 always (this is a discovery tool, not a gate); the ENFORCEMENT gate is a separate,
narrower check registered in tools/check_institutional_correctness.py's CHECKS list.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# This discovery scanner's own governance meta-tooling (itself, and its adjudication-
# recording sibling): their entire content is PROSE quoting real fallback syntax found
# elsewhere as human-readable evidence strings, not executable fallback logic. Scanning
# them as ordinary source self-matches that prose (e.g. an evidence string that literally
# contains the substring "COALESCE(" to explain what was found) and manufactures fake
# candidates that pollute the census with entries that point at nothing real. The
# regression gate (tools/check_no_fallback_lock.py) already carries this exact exclusion
# for this exact reason -- imported here rather than re-declared, so the two governance
# tools cannot silently drift apart on which files are meta-tooling.
try:
    from tools.check_no_fallback_lock import (
        _META_TOOLING_EXCLUDED_FROM_CONTENT_RULES as _META_TOOLING_EXCLUDED,
        _TEST_PROOF_NAMESPACE_PREFIX,
    )
except ImportError:  # pragma: no cover -- running as a script with tools/ not on sys.path
    import sys as _sys
    _sys.path.insert(0, str(REPO))
    from tools.check_no_fallback_lock import (
        _META_TOOLING_EXCLUDED_FROM_CONTENT_RULES as _META_TOOLING_EXCLUDED,
        _TEST_PROOF_NAMESPACE_PREFIX,
    )

#: This mission's own mutation/negative-control proof namespace (see
#: check_no_fallback_lock.py's own docstring on _TEST_PROOF_NAMESPACE_PREFIX for the full
#: precedent): its tests stage FIXTURE strings containing the exact banned syntax into a
#: throwaway repo to prove the ENFORCEMENT gate rejects them. Those fixture strings
#: necessarily quote real fallback-shaped text, which would otherwise self-trigger this
#: DISCOVERY census the same way it already self-triggers on the meta-tooling files above
#: -- excluded from the census for the identical reason, reusing the SAME namespace
#: constant the enforcement gate already established rather than re-declaring it.

#: Domain/semantic field-name fragments (case-insensitive substring match on the target
#: identifier/dict-key/attribute name). Broad by design -- a match only PROMOTES a
#: syntactic hit to a candidate; it never itself adjudicates FALLBACK vs NOT_FALLBACK.
_SEMANTIC_TERMS = [
    "spot", "price", "quote", "bid", "ask", "last", "mid", "close", "open_", "high", "low",
    "gamma", "delta", "theta", "vega", "vanna", "charm", "gex", "dex", "oi", "open_interest",
    "volume", "iv", "implied_vol", "premium", "strike", "expiry", "expiration",
    "size", "qty", "quantity", "balance", "position", "pnl", "margin", "equity", "account",
    "order", "fill", "status", "state", "regime", "session", "flag", "source", "vendor",
    "provider", "seq", "sequence", "generation", "admitted", "active", "rejected", "pending",
    "coverage", "staleness", "stale", "age_sec", "ts_utc", "ts_recv", "timestamp",
    "contracts", "admission", "surface", "exposure", "chain", "greeks", "underlying",
    "watchlist", "ticker", "symbol", "book", "depth", "trade", "tape", "level",
]
_SEMANTIC_RE = re.compile("|".join(re.escape(t) for t in _SEMANTIC_TERMS), re.I)

_SKIP_DIR_PARTS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
    "archive", ".mypy_cache", "dist", "build",
}


def _tracked_files() -> list[str]:
    r = subprocess.run(["git", "ls-files"], cwd=str(REPO), capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {r.stderr}")
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _in_scope(rel: str) -> bool:
    parts = Path(rel).parts
    return not any(d in _SKIP_DIR_PARTS for d in parts)


def _normalize_ws(s: str) -> str:
    """Collapse whitespace runs so cosmetic reflow/reindent never changes identity."""
    return re.sub(r"\s+", " ", s).strip()


def _ast_normalized(node: ast.AST) -> str:
    """A position-independent structural fingerprint basis for a Python AST node:
    `ast.dump` with `include_attributes=False` (the default) omits lineno/col_offset
    entirely, so the same expression produces the same string no matter where it moves
    to in the file or how many lines were inserted/deleted around it."""
    return ast.dump(node, annotate_fields=True)


def _finalize_ids(candidates: list[dict]) -> None:
    """Assigns each candidate's final, content-derived `id` and `fingerprint` in place.

    Identity basis: (file, context, pattern, normalized_expr, semantic_field_guess) --
    deliberately NOT line number and NOT scan/insertion order, per operator point 5.
    Processed in (file, line) order purely so that the rare case of two genuinely
    identical expressions in the same file/function gets a deterministic, stable
    `-2`/`-3` disambiguating suffix rather than one dependent on dict/walk ordering.
    """
    seen: dict[str, int] = {}
    for c in sorted(candidates, key=lambda c: (c["file"], c["line"])):
        basis = json.dumps(
            [c["file"], c.get("context"), c["pattern"], c.get("normalized_expr", ""),
             c.get("semantic_field_guess")],
            sort_keys=False,
        )
        digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()
        c["fingerprint"] = digest
        n = seen.get(digest, 0)
        seen[digest] = n + 1
        base_id = f"FB-{digest[:10]}"
        c["id"] = base_id if n == 0 else f"{base_id}-{n + 1}"


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# Python detectors (AST-based)
# ---------------------------------------------------------------------------

def _name_of(node: ast.AST) -> str:
    """Best-effort identifier/attribute/key name a node writes to or reads as its
    'subject' -- used only to test against _SEMANTIC_RE, never to prove semantics."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        sl = node.slice
        if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
            return sl.value
        return _name_of(node.value)
    if isinstance(node, ast.Call):
        return _name_of(node.func)
    return ""


def _semantic(node: ast.AST) -> bool:
    return bool(_SEMANTIC_RE.search(_name_of(node)))


def _build_parent_map(tree: ast.AST) -> dict:
    parents: dict = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _in_boolean_test_context(node: ast.AST, parents: dict) -> bool:
    """True when `node` (a BoolOp) is consumed as a pure boolean CONTROL-FLOW test --
    the `test` of an If/While/Assert/IfExp's condition, or nested inside another
    BoolOp/UnaryOp-Not that is itself in such a position -- rather than as a VALUE that
    gets assigned, returned, or passed on. `if a or b:` is ordinary logic; `x = a or b`
    is a value-substitution candidate. Only the latter shape is a fallback candidate."""
    cur = node
    while cur in parents:
        parent = parents[cur]
        if isinstance(parent, (ast.If, ast.While)) and parent.test is cur:
            return True
        if isinstance(parent, ast.Assert) and parent.test is cur:
            return True
        if isinstance(parent, ast.comprehension) and cur in parent.ifs:
            return True
        if isinstance(parent, ast.BoolOp) and cur in parent.values:
            cur = parent
            continue
        if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not) and parent.operand is cur:
            cur = parent
            continue
        return False
    return False


def _enclosing_context(tree: ast.AST, lineno: int) -> str:
    best = None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            lo, hi = n.lineno, getattr(n, "end_lineno", n.lineno)
            if lo <= lineno <= hi and (best is None or lo > best[0]):
                best = (lo, getattr(n, "name", "?"))
    return best[1] if best else "<module>"


def scan_python(rel: str, src: str) -> list[dict]:
    out: list[dict] = []
    try:
        tree = ast.parse(src, filename=rel)
    except SyntaxError as e:
        return [{
            "file": rel, "line": e.lineno or 0,
            "language": "python", "pattern": "PARSE_FAILURE",
            "snippet": f"SyntaxError: {e.msg}",
            "semantic_field_guess": None, "context": None,
            "normalized_expr": f"PARSE_FAILURE:{e.msg}",
            "adjudication": "NOT_PROVEN",
            "evidence": "file failed to parse -- an unscanned executable surface is a "
                        "discovery failure, not a pass; must be resolved by hand",
        }]
    lines = src.splitlines()
    parents = _build_parent_map(tree)

    for node in ast.walk(tree):
        # `x or y` / `x or y or z` ladders -- excluding pure boolean control-flow use
        # (`if a or b:`), which is ordinary logic, not a value substitution.
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            first = node.values[0]
            if _semantic(first) and not _in_boolean_test_context(node, parents):
                ln = node.lineno
                out.append({
                    "file": rel, "line": ln, "language": "python",
                    "pattern": "OR_LADDER",
                    "snippet": (lines[ln - 1].strip() if 0 <= ln - 1 < len(lines) else ""),
                    "semantic_field_guess": _name_of(first),
                    "context": _enclosing_context(tree, ln),
                    "normalized_expr": _ast_normalized(node),
                    "adjudication": "NOT_PROVEN",
                    "evidence": "boolean-or ladder whose leading operand's name matches a "
                                "domain-semantic term",
                })
        # ternary `a if cond else b` where the true-branch (the intended value) looks semantic
        if isinstance(node, ast.IfExp):
            if _semantic(node.body):
                ln = node.lineno
                out.append({
                    "file": rel, "line": ln, "language": "python",
                    "pattern": "TERNARY",
                    "snippet": (lines[ln - 1].strip() if 0 <= ln - 1 < len(lines) else ""),
                    "semantic_field_guess": _name_of(node.body),
                    "context": _enclosing_context(tree, ln),
                    "normalized_expr": _ast_normalized(node),
                    "adjudication": "NOT_PROVEN",
                    "evidence": "conditional expression whose primary branch's name matches "
                                "a domain-semantic term",
                })
        # `.get(key, default)` two-arg dict access
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            if len(node.args) >= 2:
                target_name = _name_of(node.func.value) + "." + (
                    node.args[0].value if isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str) else ""
                )
                default_is_trivial = (
                    isinstance(node.args[1], ast.Constant)
                    and node.args[1].value in (None,)
                )
                if _SEMANTIC_RE.search(target_name) and not default_is_trivial:
                    ln = node.lineno
                    out.append({
                        "file": rel, "line": ln, "language": "python",
                        "pattern": "DICT_GET_DEFAULT",
                        "snippet": (lines[ln - 1].strip() if 0 <= ln - 1 < len(lines) else ""),
                        "semantic_field_guess": target_name,
                        "context": _enclosing_context(tree, ln),
                        "normalized_expr": _ast_normalized(node),
                        "adjudication": "NOT_PROVEN",
                        "evidence": ".get(key, default) with a non-None default on a key "
                                    "matching a domain-semantic term",
                    })
        # getattr(obj, name, default) three-arg form
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "getattr" and len(node.args) >= 3):
            name_arg = node.args[1]
            key = name_arg.value if isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str) else ""
            default_is_trivial = isinstance(node.args[2], ast.Constant) and node.args[2].value is None
            if _SEMANTIC_RE.search(key) and not default_is_trivial:
                ln = node.lineno
                out.append({
                    "file": rel, "line": ln, "language": "python",
                    "pattern": "GETATTR_DEFAULT",
                    "snippet": (lines[ln - 1].strip() if 0 <= ln - 1 < len(lines) else ""),
                    "semantic_field_guess": key,
                    "context": _enclosing_context(tree, ln),
                    "normalized_expr": _ast_normalized(node),
                    "adjudication": "NOT_PROVEN",
                    "evidence": "getattr(obj, name, default) with a non-None default on a "
                                "name matching a domain-semantic term",
                })
        # pandas-style imputation
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in (
                "fillna", "ffill", "bfill", "interpolate"):
            ln = node.lineno
            out.append({
                "file": rel, "line": ln, "language": "python",
                "pattern": "IMPUTATION",
                "snippet": (lines[ln - 1].strip() if 0 <= ln - 1 < len(lines) else ""),
                "semantic_field_guess": _name_of(node.func.value),
                "context": _enclosing_context(tree, ln),
                "normalized_expr": _ast_normalized(node),
                "adjudication": "NOT_PROVEN",
                "evidence": f"pandas-style imputation call ({node.func.attr}) -- always a "
                            f"candidate regardless of name match (imputation is inherently "
                            f"a substitution of missing data)",
            })
        # except handler whose body returns/assigns something (not just pass/raise/log) --
        # overlaps only partially with check_no_silent_swallow (which only catches
        # pass-only bodies); this flags a handler that produces a SUBSTITUTE VALUE.
        if isinstance(node, ast.ExceptHandler):
            broad = node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"})
            if broad:
                for stmt in node.body:
                    substitute_return = (
                        isinstance(stmt, ast.Return) and stmt.value is not None
                        and not (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)
                    )
                    substitute_assign = isinstance(stmt, (ast.Assign, ast.AugAssign))
                    if substitute_return or substitute_assign:
                        target = stmt.value if substitute_return else (
                            stmt.targets[0] if isinstance(stmt, ast.Assign) else stmt.target)
                        if _semantic(target) or (substitute_return and _semantic(stmt.value)):
                            ln = stmt.lineno
                            out.append({
                                "file": rel, "line": ln,
                                "language": "python", "pattern": "EXCEPT_SUBSTITUTE",
                                "snippet": (lines[ln - 1].strip() if 0 <= ln - 1 < len(lines) else ""),
                                "semantic_field_guess": _name_of(target),
                                "context": _enclosing_context(tree, ln),
                                "normalized_expr": _ast_normalized(stmt),
                                "adjudication": "NOT_PROVEN",
                                "evidence": "broad except handler returns/assigns a "
                                            "substitute value for a domain-semantic field "
                                            "instead of propagating/marking failure",
                            })
        # inline SQL strings passed anywhere (heuristic: a string constant containing
        # COALESCE/IFNULL/NVL, case-insensitive). A multi-line triple-quoted literal
        # reports node.lineno as the literal's OPENING line, not the match's own line --
        # walk the literal's own text to find the real offset instead of pointing at
        # the string's start. EXCLUDES a literal whose only use is as the operand of an
        # `in`/`not in` membership test (`"COALESCE(...)" not in some_source_text`) --
        # this repo's own regression-proof tests assert a REPAIR by searching for the
        # banned pattern's ABSENCE in real source text, which necessarily quotes the
        # banned syntax as a string to search FOR, not to execute as SQL (confirmed via
        # a direct false-positive: tests/test_horizon_bar_outcomes.py and
        # tests/test_operable_surface_gate.py's own `assert "COALESCE(...)" not in
        # code_only` proof lines were being counted as production SQL-fallback
        # candidates). A string executed as SQL is passed to a query call or returned/
        # assigned, never merely compared via membership -- this exclusion cannot hide a
        # real violation, only a search-pattern quotation of one.
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            parent = parents.get(node)
            in_membership_test = (
                isinstance(parent, ast.Compare)
                and any(isinstance(op, (ast.In, ast.NotIn)) for op in parent.ops)
            )
            m = None if in_membership_test else _SQL_FALLBACK_RE.search(node.value)
            if m:
                line_offset_in_literal = node.value.count("\n", 0, m.start())
                ln = node.lineno + line_offset_in_literal
                literal_lines = node.value.splitlines()
                match_line_text = (literal_lines[line_offset_in_literal].strip()
                                    if 0 <= line_offset_in_literal < len(literal_lines) else "")
                snippet = (match_line_text or
                           (lines[ln - 1].strip() if 0 <= ln - 1 < len(lines) else ""))[:200]
                out.append({
                    "file": rel, "line": ln, "language": "sql-in-python",
                    "pattern": "SQL_COALESCE_STYLE",
                    "snippet": snippet,
                    "semantic_field_guess": None,
                    "context": _enclosing_context(tree, ln),
                    "normalized_expr": _normalize_ws(snippet),
                    "adjudication": "NOT_PROVEN",
                    "evidence": "string literal contains COALESCE/IFNULL/NVL -- inline SQL "
                                "fallback substitution",
                })
    return out


_SQL_FALLBACK_RE = re.compile(r"\bCOALESCE\s*\(|\bIFNULL\s*\(|\bNVL\s*\(", re.I)


# ---------------------------------------------------------------------------
# JS / inline-HTML-script detectors (regex-based -- no build step, no TS, plain JS)
# ---------------------------------------------------------------------------

_JS_OR_RE = re.compile(
    r"(?P<target>[A-Za-z_$][\w.$\[\]'\"]*)\s*(?:=|:|\breturn\b)?\s*"
    r"(?P<lhs>[A-Za-z_$][\w.$\[\]'\"]*)\s*(?P<op>\|\||\?\?)\s*(?P<rhs>[^;,)\n]{1,80})"
)


def scan_js_text(rel: str, src: str, line_offset: int = 0) -> list[dict]:
    out: list[dict] = []
    for i, line in enumerate(src.splitlines(), 1):
        if "//" in line:
            code_part = line.split("//", 1)[0]
        else:
            code_part = line
        for m in _JS_OR_RE.finditer(code_part):
            lhs = m.group("lhs")
            if _SEMANTIC_RE.search(lhs):
                out.append({
                    "file": rel, "line": i + line_offset,
                    "language": "javascript",
                    "pattern": "OR_OR" if m.group("op") == "||" else "NULLISH_COALESCE",
                    "snippet": line.strip()[:200],
                    "semantic_field_guess": lhs,
                    "context": None,
                    "normalized_expr": _normalize_ws(m.group(0)),
                    "adjudication": "NOT_PROVEN",
                    "evidence": f"{m.group('op')} substitution whose left operand's name "
                                f"matches a domain-semantic term",
                })
    return out


_HTML_SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.I | re.S)


def scan_html(rel: str, src: str) -> list[dict]:
    out: list[dict] = []
    for m in _HTML_SCRIPT_RE.finditer(src):
        body = m.group(1)
        start_line = src.count("\n", 0, m.start(1))
        out.extend(scan_js_text(rel, body, line_offset=start_line))
    return out


# ---------------------------------------------------------------------------
# .sql file detector
# ---------------------------------------------------------------------------

def scan_sql_file(rel: str, src: str) -> list[dict]:
    out: list[dict] = []
    for i, line in enumerate(src.splitlines(), 1):
        if _SQL_FALLBACK_RE.search(line):
            snippet = line.strip()[:200]
            out.append({
                "file": rel, "line": i, "language": "sql",
                "pattern": "SQL_COALESCE_STYLE",
                "snippet": snippet,
                "semantic_field_guess": None, "context": None,
                "normalized_expr": _normalize_ws(snippet),
                "adjudication": "NOT_PROVEN",
                "evidence": "COALESCE/IFNULL/NVL in a .sql file",
            })
    return out


# ---------------------------------------------------------------------------
# PowerShell / batch detectors
# ---------------------------------------------------------------------------

_PS_FALLBACK_RE = re.compile(r"\?\?|\bif\s*\(\s*-not\b")
_BAT_FALLBACK_RE = re.compile(r"if\s+not\s+defined\b|if\s+\"%\w+%\"\s*==\s*\"\"", re.I)


def scan_ps1(rel: str, src: str) -> list[dict]:
    out: list[dict] = []
    for i, line in enumerate(src.splitlines(), 1):
        if _PS_FALLBACK_RE.search(line):
            snippet = line.strip()[:200]
            out.append({
                "file": rel, "line": i, "language": "powershell",
                "pattern": "PS_NULL_COALESCE_OR_GUARD",
                "snippet": snippet,
                "semantic_field_guess": None, "context": None,
                "normalized_expr": _normalize_ws(snippet),
                "adjudication": "NOT_PROVEN",
                "evidence": "PowerShell null-coalesce (??) or an if-not guard that may "
                            "assign a substitute value",
            })
    return out


def scan_bat(rel: str, src: str) -> list[dict]:
    out: list[dict] = []
    for i, line in enumerate(src.splitlines(), 1):
        if _BAT_FALLBACK_RE.search(line):
            snippet = line.strip()[:200]
            out.append({
                "file": rel, "line": i, "language": "batch",
                "pattern": "BAT_DEFAULT_VAR",
                "snippet": snippet,
                "semantic_field_guess": None, "context": None,
                "normalized_expr": _normalize_ws(snippet),
                "adjudication": "NOT_PROVEN",
                "evidence": "batch 'if not defined'/'if var==\"\"' default-assignment shape",
            })
    return out


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

_HANDLERS = {
    ".py": ("python", scan_python),
    ".js": ("javascript", None),   # handled via scan_js_text below
    ".mjs": ("javascript", None),
    ".jsx": ("javascript", None),
    ".html": ("html", scan_html),
    ".sql": ("sql", scan_sql_file),
    ".ps1": ("powershell", scan_ps1),
    ".bat": ("batch", scan_bat),
}

#: Extensions this tool has NO detector for at all, that still sit in an "executable/
#: source surface" location the mission's SCOPE names (config, APIs). Emitted as explicit
#: UNSCANNED_SURFACE entries -- never silently dropped -- per "fail nonzero on ... unknown
#: executable surfaces."
_DECLARED_NO_OP_EXTENSIONS = {".yaml", ".yml", ".toml", ".json", ".css"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/no_fallback_discovery_raw.json")
    args = ap.parse_args()

    candidates: list[dict] = []
    scanned_by_type: dict[str, int] = {}
    unscanned_declared: dict[str, int] = {}
    unscanned_unknown: list[str] = []
    meta_tooling_excluded: dict[str, int] = {}

    for rel in _tracked_files():
        if not _in_scope(rel):
            continue
        if rel in _META_TOOLING_EXCLUDED or rel.startswith(_TEST_PROOF_NAMESPACE_PREFIX):
            # This tool's own governance meta-tooling, and its mutation/negative-control
            # proof-test namespace (see the module docstring): their content is prose or
            # fixture strings ABOUT fallback shapes found elsewhere, not fallback logic
            # itself. Recorded distinctly (never silently dropped) so the report itself
            # proves the exclusion is narrow and enumerable, not a silent skip.
            meta_tooling_excluded[rel] = meta_tooling_excluded.get(rel, 0) + 1
            continue
        path = REPO / rel
        ext = path.suffix.lower()
        if ext == ".py":
            src = _read(path)
            if src is None:
                candidates.append({
                    "file": rel, "line": 0, "language": "python",
                    "pattern": "READ_FAILURE", "snippet": "", "semantic_field_guess": None,
                    "context": None, "normalized_expr": "READ_FAILURE",
                    "adjudication": "NOT_PROVEN",
                    "evidence": "file could not be read as UTF-8 -- unscanned surface",
                })
                continue
            scanned_by_type["python"] = scanned_by_type.get("python", 0) + 1
            candidates.extend(scan_python(rel, src))
        elif ext in (".js", ".mjs", ".jsx"):
            src = _read(path)
            if src is None:
                continue
            scanned_by_type["javascript"] = scanned_by_type.get("javascript", 0) + 1
            candidates.extend(scan_js_text(rel, src))
        elif ext == ".html":
            src = _read(path)
            if src is None:
                continue
            scanned_by_type["html"] = scanned_by_type.get("html", 0) + 1
            candidates.extend(scan_html(rel, src))
        elif ext == ".sql":
            src = _read(path)
            if src is None:
                continue
            scanned_by_type["sql"] = scanned_by_type.get("sql", 0) + 1
            candidates.extend(scan_sql_file(rel, src))
        elif ext == ".ps1":
            src = _read(path)
            if src is None:
                continue
            scanned_by_type["powershell"] = scanned_by_type.get("powershell", 0) + 1
            candidates.extend(scan_ps1(rel, src))
        elif ext == ".bat":
            src = _read(path)
            if src is None:
                continue
            scanned_by_type["batch"] = scanned_by_type.get("batch", 0) + 1
            candidates.extend(scan_bat(rel, src))
        elif ext in _DECLARED_NO_OP_EXTENSIONS:
            unscanned_declared[ext] = unscanned_declared.get(ext, 0) + 1
        elif ext in ("", ".md", ".txt", ".pt", ".pkl", ".png", ".csv", ".gitkeep",
                     ".gitignore", ".example", ".ico", ".webmanifest", ".mdc",
                     ".python-version", ".gitattributes", ".migrated_issue22", ".jsonl"):
            unscanned_declared[ext or "(no-ext)"] = unscanned_declared.get(ext or "(no-ext)", 0) + 1
        else:
            unscanned_unknown.append(rel)

    _finalize_ids(candidates)

    report = {
        "scanned_by_type": scanned_by_type,
        "unscanned_declared_noop_by_ext": unscanned_declared,
        "unscanned_unknown_extensions": unscanned_unknown,
        "meta_tooling_excluded_from_scan": meta_tooling_excluded,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    out_path = REPO / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"scanned_by_type: {scanned_by_type}")
    print(f"unscanned_declared_noop_by_ext: {unscanned_declared}")
    print(f"unscanned_unknown_extensions: {len(unscanned_unknown)} -> {unscanned_unknown[:20]}")
    print(f"meta_tooling_excluded_from_scan: {meta_tooling_excluded}")
    print(f"candidate_count: {len(candidates)}")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
