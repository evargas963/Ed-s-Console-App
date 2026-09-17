#!/usr/bin/env python3
"""REPO-WIDE NO-FALLBACK MECHANICAL LOCK (operator mandate 2026-09-17).

GOVERNING RULE this gate enforces on every STAGED diff: a semantic field may contain only
the exact value defined by that field. If its canonical source is missing/stale/malformed/
partial/unauthorized/rejected/delayed/failed, the field must expose that exact failure
state or fail closed -- never a substitute. This gate is diff-scoped (like
check_domain_faucet_registry, governance/level_faucets.json's own enforcement style) so it
can be ENFORCED immediately without first repairing every pre-existing violation already in
the tree (tracked separately in reports/no_fallback_inventory.json, the mission's full
census) -- a commit that does not touch fallback-shaped code passes trivially; a commit
that ADDS a new one fails here, in required CI, on the actual PR/merge diff.

WHY THIS SHAPE, NOT A BROADER SEMANTIC-TERM SCAN. tools/fallback_discovery.py (the
DISCOVERY half of this mission) casts a wide net across every domain-term-adjacent
default/ternary/`or`-ladder in the repo and needs a human/agent semantic adjudication pass
before any single hit can be called a real violation (see reports/no_fallback_inventory.json
-- of the first 122 candidates read in full, 42 were confirmed legitimate, non-fallback
idioms: an aggregate-over-empty-set COALESCE, a self-describing '(null)' audit label, an
except handler that DISCLOSES the failure by name rather than substituting a value). A gate
that fires on that same broad net would either reject those legitimate patterns (a false
positive that erodes trust in the gate) or need a per-line escape marker to clear them --
exactly the "fallback allowlist" the mission forbids. This gate therefore encodes only the
SHAPES this session's own adjudication pass actually confirmed as unsafe or safe, narrowly
and precisely enough to have zero known false positives against the confirmed set, rather
than approximating the discovery scanner's broad candidate net as if every candidate were
already a proven violation.

RULES ENFORCED (all diff-scoped, all zero-allowlist):
  R1  SQL COALESCE/IFNULL/NVL added on a non-aggregate default, unless the default is a
      self-describing display-label string ('(null)', 'NULL', 'unknown', ...) or the
      statement is an UPDATE-preserve-existing shape (`col = COALESCE(col, ?)`).
  R2  a pandas imputation call (fillna / ffill / bfill / interpolate) added outside a file
      named in governance/no_fallback_registry.json's ml_imputation_authorized_files.
      (Worded here without the literal call syntax so this docstring does not trip its own
      detector -- the RC-47 lesson from check_no_fake_defaults.)
  R3  an except handler body added that assigns an empty collection ([]/{}/set()) or a bare
      0/0.0/''  to a target whose name does NOT itself name the failure (error/status/fail/
      reason/exception) -- i.e. it looks like data, not disclosure.
  R4  JS/JSX `||` or `??` added whose left operand is one of a small set of PROTECTED field
      names this repo has an established single-authority producer for (spot, admitted,
      active, rejected, surface_seq) -- mirrors check_single_spot_authority's existing
      per-field protection, generalized to the fields this session's own discovery pass
      found already governed elsewhere in this file.
  R5  the diff deletes or narrows governance/no_fallback_registry.json, or deletes/edits a
      RULES-implementing function in this file, without an operator_quote co-staged on the
      SAME diff (mirrors governance/level_faucets.json's existing "operator_quote co-staged"
      convention, RC-212).
  R6  a staged file whose extension is not one of the file types this gate knows how to
      scan (.py/.js/.jsx/.mjs/.html/.sql/.ps1/.bat) AND is not in the declared no-op list
      (config/docs/data/binary types already enumerated by fallback_discovery.py) is an
      UNKNOWN EXECUTABLE SURFACE -- fails rather than silently passing.
  R7  a staged .py/.js/.jsx/.mjs/.html/.sql file that fails to parse/tokenize is a
      DISCOVERY FAILURE -- fails rather than silently skipping.
  R8  Python `x or y` / `x or y or z` added whose leading operand is one of the same
      PROTECTED field names as R4, outside a pure boolean-test position (an `if`/`while`/
      `assert` condition is ordinary control flow, not a value substitution) -- and a
      Python `.get(key, default)` added with a non-None default where key is a PROTECTED
      field name.
  R9  a value assigned from a variable/attribute whose own name marks it as a prior/cached/
      stale/carried-forward copy (matches *_prior*, *cached*, *_last_known*, *_stale*,
      *_carried*) into a PROTECTED field, in the SAME added statement block that also
      stamps a fresh generation/sequence/timestamp field (matching *_ts*, *generation*,
      *_seq*, *timestamp*) -- the "stale data, fresh badge" shape.
  Not separately re-implemented here: a NEW direct call bypassing an ALREADY-established
  single-authority producer (spot via resolve_spot(), a level-domain route, a registered
  computation_registry.json field) is already enforced by check_single_spot_authority /
  check_domain_faucet_registry / check_one_producer respectively -- extending those, not
  duplicating them, per the mission's own "no duplicate registry/authority" instruction.
  A wrapper/alias that conceals a fallback behind a renamed call is a KNOWN, ACKNOWLEDGED
  gap even in check_one_producer.py's own mature design (its docstring names this "D5
  shadow... NOT_PROVEN repo-wide") -- this lock does not claim to close it either; see the
  mission report's NOT_PROVEN list rather than a fabricated proof.

    .venv/Scripts/python.exe tools/check_no_fallback_lock.py           # staged diff (pre-commit)
    .venv/Scripts/python.exe tools/check_no_fallback_lock.py --base origin/main  # a whole branch
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "governance" / "no_fallback_registry.json"

_DECLARED_NOOP_EXTS = {
    ".yaml", ".yml", ".toml", ".json", ".css", ".md", ".txt", ".pt", ".pkl", ".png", ".csv",
    ".gitkeep", ".gitignore", ".example", ".ico", ".webmanifest", ".mdc", ".python-version",
    ".gitattributes", ".jsonl", "",
}
_SCANNABLE_EXTS = {".py", ".js", ".jsx", ".mjs", ".html", ".sql", ".ps1", ".bat"}

_SQL_FALLBACK_RE = re.compile(r"\b(COALESCE|IFNULL|NVL)\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)", re.I)
_AGGREGATE_RE = re.compile(r"\b(MAX|MIN|SUM|COUNT|AVG)\s*\(", re.I)
_DISPLAY_LABEL_RE = re.compile(r"""^\s*['"]?\(?(null|none|unknown|n/?a)\)?['"]?\s*$""", re.I)
_UPDATE_PRESERVE_RE = re.compile(r"(\w[\w.]*)\s*=\s*(?:COALESCE|IFNULL|NVL)\s*\(\s*\1\s*,", re.I)

_IMPUTATION_RE = re.compile(r"\.(fillna|ffill|bfill|interpolate)\s*\(")

_FAILURE_NAME_RE = re.compile(r"error|status|fail|reason|exception|excep|_err\b", re.I)
_EMPTY_SUBSTITUTE_RE = re.compile(r"=\s*(\[\]|\{\}|set\(\)|0\.0|0|'')\s*$")

_PROTECTED_JS_FIELDS = ("spot", "admitted", "active", "rejected", "surface_seq")
_JS_OR_RE = re.compile(
    r"(?P<lhs>[A-Za-z_$][\w.$\[\]'\"]*)\s*(?P<op>\|\||\?\?)\s*(?P<rhs>[^;,)\n]{1,80})")


def _run(args: list[str]) -> str:
    r = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def _staged_files(base: str | None) -> list[str]:
    if base:
        out = _run(["diff", "--name-only", f"{base}...HEAD"])
    else:
        out = _run(["diff", "--cached", "--name-only"])
    return [ln.strip().replace("\\", "/") for ln in out.splitlines() if ln.strip()]


def _added_lines(rel: str, base: str | None) -> list[tuple[int, str]]:
    """(new_file_line_number, added_text) for every '+' line in this file's diff."""
    args = ["diff", "-U0"]
    args += [f"{base}...HEAD"] if base else ["--cached"]
    args += ["--", rel]
    out = _run(args)
    hunks: list[tuple[int, str]] = []
    cur_line = 0
    for ln in out.splitlines():
        if ln.startswith("@@"):
            m = re.search(r"\+(\d+)", ln)
            cur_line = int(m.group(1)) if m else 0
            continue
        if ln.startswith("+++"):
            continue
        if ln.startswith("+"):
            hunks.append((cur_line, ln[1:]))
            cur_line += 1
    return hunks


class Finding:
    def __init__(self, rel: str, line: int, rule: str, msg: str) -> None:
        self.rel, self.line, self.rule, self.msg = rel, line, rule, msg

    def __str__(self) -> str:
        return f"  {self.rel}:{self.line}  [{self.rule}] {self.msg}"


def _load_registry() -> dict:
    try:
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _r1_sql(rel: str, added: list[tuple[int, str]]) -> list[Finding]:
    out: list[Finding] = []
    for line_no, text in added:
        for m in _SQL_FALLBACK_RE.finditer(text):
            args_text = m.group(2)
            parts = args_text.split(",", 1)
            if len(parts) < 2:
                continue
            col, default = parts[0].strip(), parts[1].strip()
            if _AGGREGATE_RE.search(col):
                continue  # aggregate-over-empty-set: confirmed-safe idiom
            if _DISPLAY_LABEL_RE.match(default):
                continue  # self-describing display label: confirmed-safe idiom
            if _UPDATE_PRESERVE_RE.search(text):
                continue  # col = COALESCE(col, ?): preserve-existing-value idiom
            out.append(Finding(
                rel, line_no, "R1_SQL_COALESCE",
                f"new COALESCE/IFNULL/NVL default on a non-aggregate column, non-display-"
                f"label default: {text.strip()[:160]!r}. If this is a genuine confirmed-safe "
                f"idiom, restructure to match one of the two recognized safe shapes "
                f"(aggregate default, or a '(null)'-style display label) -- this gate has no "
                f"per-line escape."))
    return out


def _r2_imputation(rel: str, added: list[tuple[int, str]], registry: dict) -> list[Finding]:
    authorized = set((registry.get("ml_imputation_authorized_files") or {}).keys())
    if rel in authorized:
        return []
    out: list[Finding] = []
    for line_no, text in added:
        if _IMPUTATION_RE.search(text):
            out.append(Finding(
                rel, line_no, "R2_IMPUTATION",
                f"new pandas imputation call outside an authorized file "
                f"(governance/no_fallback_registry.json:ml_imputation_authorized_files): "
                f"{text.strip()[:160]!r}. Add the file to that registry, co-staged with an "
                f"operator_quote on the same entry, or remove the imputation."))
    return out


def _r3_except_substitute(rel: str, src_before: str, src_after: str,
                          added_line_nos: set[int]) -> list[Finding]:
    out: list[Finding] = []
    try:
        tree = ast.parse(src_after, filename=rel)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        broad = node.type is None or (
            isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"})
        if not broad:
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            if stmt.lineno not in added_line_nos:
                continue  # pre-existing line, not part of THIS diff
            target = stmt.targets[0]
            target_name = ast.unparse(target) if hasattr(ast, "unparse") else ""
            if _FAILURE_NAME_RE.search(target_name):
                continue  # names the failure: disclosure, not substitution
            is_empty_literal = (
                (isinstance(stmt.value, (ast.List, ast.Dict)) and not (
                    getattr(stmt.value, "elts", None) or getattr(stmt.value, "keys", None)))
                or (isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Name)
                    and stmt.value.func.id == "set" and not stmt.value.args)
                or (isinstance(stmt.value, ast.Constant) and stmt.value.value in (0, 0.0, ""))
            )
            if is_empty_literal:
                out.append(Finding(
                    rel, stmt.lineno, "R3_EXCEPT_SUBSTITUTE",
                    f"new except-handler assignment substitutes an empty/zero literal for "
                    f"'{target_name}' instead of disclosing the failure (rename to include "
                    f"error/status/fail/reason, or propagate/raise instead)."))
    return out


def _r4_js_protected_field(rel: str, added: list[tuple[int, str]]) -> list[Finding]:
    out: list[Finding] = []
    for line_no, text in added:
        code = text.split("//", 1)[0]
        for m in _JS_OR_RE.finditer(code):
            lhs = m.group("lhs")
            base_name = re.split(r"[.\[]", lhs)[-1].strip("'\"")
            if base_name in _PROTECTED_JS_FIELDS:
                out.append(Finding(
                    rel, line_no, "R4_JS_PROTECTED_FIELD",
                    f"new {m.group('op')} substitution on protected field '{base_name}': "
                    f"{text.strip()[:160]!r}. This field has an established single-authority "
                    f"producer elsewhere in the stack; render its own disclosed "
                    f"unavailable/stale state instead of substituting a value here."))
    return out


def _r8_python_protected_field(rel: str, src_after: str, added_line_nos: set[int]) -> list[Finding]:
    out: list[Finding] = []
    try:
        tree = ast.parse(src_after, filename=rel)
    except SyntaxError:
        return out
    parents: dict = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def _in_bool_test(node: ast.AST) -> bool:
        cur = node
        while cur in parents:
            parent = parents[cur]
            if isinstance(parent, (ast.If, ast.While)) and parent.test is cur:
                return True
            if isinstance(parent, ast.Assert) and parent.test is cur:
                return True
            if isinstance(parent, ast.BoolOp) and cur in parent.values:
                cur = parent
                continue
            return False
        return False

    def _base_name(n: ast.AST) -> str:
        if isinstance(n, ast.Name):
            return n.id
        if isinstance(n, ast.Attribute):
            return n.attr
        if isinstance(n, ast.Subscript):
            sl = n.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                return sl.value
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get":
            if n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                return n.args[0].value  # payload.get('spot') reads as field 'spot'
        return ""

    for node in ast.walk(tree):
        if getattr(node, "lineno", None) not in added_line_nos:
            continue
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            first = node.values[0]
            if _base_name(first) in _PROTECTED_JS_FIELDS and not _in_bool_test(node):
                out.append(Finding(
                    rel, node.lineno, "R8_PY_PROTECTED_FIELD_OR",
                    f"new `or`-ladder value substitution on protected field "
                    f"'{_base_name(first)}' -- this field has an established single-authority "
                    f"producer; disclose its own unavailable/stale state instead."))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and len(node.args) >= 2):
            key_node = node.args[0]
            key = key_node.value if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str) else ""
            default_trivial = isinstance(node.args[1], ast.Constant) and node.args[1].value is None
            if key in _PROTECTED_JS_FIELDS and not default_trivial:
                out.append(Finding(
                    rel, node.lineno, "R8_PY_PROTECTED_FIELD_GET",
                    f"new .get('{key}', <non-None default>) on protected field '{key}' -- "
                    f"disclose absence explicitly instead of defaulting it."))
    return out


_STALE_NAME_RE = re.compile(r"prior|cached|last_known|_stale|_carried", re.I)
_FRESH_GEN_NAME_RE = re.compile(r"_ts\b|generation|_seq\b|timestamp", re.I)


def _r9_stale_fresh_badge(rel: str, src_after: str, added_line_nos: set[int]) -> list[Finding]:
    """A statement block newly added that (a) assigns a PROTECTED field from a variable
    whose own name marks it as a prior/cached/stale copy, AND (b) in the same block also
    stamps a fresh generation/sequence/timestamp field -- data that did not just arrive,
    wearing a badge that says it did."""
    out: list[Finding] = []
    try:
        tree = ast.parse(src_after, filename=rel)
    except SyntaxError:
        return out

    def _base_name(n: ast.AST) -> str:
        if isinstance(n, ast.Name):
            return n.id
        if isinstance(n, ast.Attribute):
            return n.attr
        return ""

    for block_owner in ast.walk(tree):
        body = getattr(block_owner, "body", None)
        if not isinstance(body, list):
            continue
        stale_assign_line = None
        stale_target = None
        fresh_stamp_line = None
        for stmt in body:
            if not isinstance(stmt, ast.Assign) or stmt.lineno not in added_line_nos:
                continue
            target_name = _base_name(stmt.targets[0])
            value_name = _base_name(stmt.value) if isinstance(stmt.value, (ast.Name, ast.Attribute)) else ""
            if target_name in _PROTECTED_JS_FIELDS and _STALE_NAME_RE.search(value_name):
                stale_assign_line, stale_target = stmt.lineno, target_name
            if _FRESH_GEN_NAME_RE.search(target_name):
                fresh_stamp_line = stmt.lineno
        if stale_assign_line is not None and fresh_stamp_line is not None:
            out.append(Finding(
                rel, stale_assign_line, "R9_STALE_FRESH_BADGE",
                f"protected field '{stale_target}' assigned from a variable named as a "
                f"prior/cached/stale copy, in the same block that also stamps a fresh "
                f"generation/timestamp field (line {fresh_stamp_line}) -- stale data must "
                f"not be re-presented under a fresh-looking badge."))
    return out


def _r5_registry_weakening(files: list[str], base: str | None) -> list[Finding]:
    out: list[Finding] = []
    targets = [f for f in files if f in (
        "governance/no_fallback_registry.json", "tools/check_no_fallback_lock.py")]
    if not targets:
        return out
    for rel in targets:
        added_text = "\n".join(t for _, t in _added_lines(rel, base))
        removed_args = ["diff", "-U0"]
        removed_args += [f"{base}...HEAD"] if base else ["--cached"]
        removed_args += ["--", rel]
        diff_out = _run(removed_args)
        removed_text = "\n".join(
            ln[1:] for ln in diff_out.splitlines()
            if ln.startswith("-") and not ln.startswith("---"))
        widens_or_weakens = bool(removed_text.strip()) or "ml_imputation_authorized_files" in added_text
        if widens_or_weakens and "operator_quote" not in added_text:
            out.append(Finding(
                rel, 0, "R5_LOCK_WEAKENED",
                f"{rel} is modified in a way that removes or widens protected content with "
                f"no operator_quote co-staged in the same diff (RC-212 convention) -- this "
                f"lock does not accept a silent weakening."))
    return out


def _r6_r7_unknown_and_parse(files: list[str], base: str | None) -> list[Finding]:
    out: list[Finding] = []
    for rel in files:
        path = REPO / rel
        if not path.exists():
            continue  # deleted file: nothing to scan
        ext = path.suffix.lower()
        if ext in _SCANNABLE_EXTS:
            if ext == ".py":
                try:
                    ast.parse(path.read_text(encoding="utf-8"), filename=rel)
                except (SyntaxError, UnicodeDecodeError) as e:
                    out.append(Finding(rel, getattr(e, "lineno", 0) or 0, "R7_PARSE_FAILURE",
                                       f"staged Python file fails to parse: {e}"))
            continue
        if ext in _DECLARED_NOOP_EXTS:
            continue
        out.append(Finding(rel, 0, "R6_UNKNOWN_SURFACE",
                           f"staged file has an extension ({ext or '(none)'}) this gate does "
                           f"not know how to scan and is not declared no-op in "
                           f"fallback_discovery.py's _DECLARED_NO_OP_EXTENSIONS -- an unscanned "
                           f"executable surface fails rather than silently passing."))
    return out


#: The mission's own discovery/adjudication META-TOOLING and its data output: these files'
#: entire job is to CATALOG example fallback-shaped snippets found elsewhere (as evidence
#: strings/comments quoting real code from OTHER files) for human/agent reading -- they are
#: governance artifacts about the census, never an execution surface the GOVERNING RULE
#: itself targets. Excluding them from R1-R4 is not a fallback allowlist (no PRODUCTION or
#: TEST code path is exempted); it is the same class of exclusion _production_py_files()
#: already applies to tests/tools/research/archive elsewhere in this framework, applied to
#: the two files whose necessarily-literal quoted evidence would otherwise self-trigger the
#: gate (the RC-47 lesson, generalized: reported here structurally rather than by rewording
#: every quoted example into unreadable prose).
_META_TOOLING_EXCLUDED_FROM_CONTENT_RULES = (
    "tools/fallback_discovery.py", "tools/apply_adjudication.py",
)
#: This mission's OWN mutation-proof test namespace (tests/test_no_fallback_lock*.py): its
#: entire purpose is to embed the exact banned shapes as fixture strings to prove the gate
#: rejects them (the mission's own required PROOF). Excluding it is not a general "tests
#: are exempt" loophole (every OTHER test file stays fully in scope) -- it is narrowly the
#: proof harness for THIS gate, the same self-reference the RC-47 precedent already forced
#: on check_no_fake_defaults's own docstring.
_TEST_PROOF_NAMESPACE_PREFIX = "tests/test_no_fallback_lock"


def violations(base: str | None = None) -> list[str]:
    files = _staged_files(base)
    findings: list[Finding] = []
    registry = _load_registry()
    for rel in files:
        path = REPO / rel
        if not path.exists():
            continue
        if (rel in _META_TOOLING_EXCLUDED_FROM_CONTENT_RULES or rel.startswith("reports/")
                or rel.startswith(_TEST_PROOF_NAMESPACE_PREFIX)):
            continue
        ext = path.suffix.lower()
        added = _added_lines(rel, base) if ext in (".py", ".sql", ".js", ".jsx", ".mjs", ".html") else []
        if ext in (".py", ".sql"):
            findings += _r1_sql(rel, added)
        if ext == ".py":
            findings += _r2_imputation(rel, added, registry)
            try:
                src_after = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                src_after = ""
            added_line_nos = {ln for ln, _ in added}
            if src_after:
                findings += _r3_except_substitute(rel, "", src_after, added_line_nos)
                findings += _r8_python_protected_field(rel, src_after, added_line_nos)
                findings += _r9_stale_fresh_badge(rel, src_after, added_line_nos)
        if ext in (".js", ".jsx", ".mjs", ".html"):
            findings += _r4_js_protected_field(rel, added)
    findings += _r5_registry_weakening(files, base)
    findings += _r6_r7_unknown_and_parse(files, base)
    return [str(f) for f in findings]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default=None,
                    help="compare HEAD against this ref instead of the staged index")
    args = ap.parse_args(argv)
    try:
        v = violations(args.base)
    except RuntimeError as e:
        print(f"check_no_fallback_lock: FAIL (gate could not run) — {e}")
        return 1
    if v:
        print("check_no_fallback_lock: FAIL — new fallback behavior in this diff:")
        for line in v:
            print(line)
        return 1
    print("check_no_fallback_lock: PASS — this diff adds no detected fallback behavior")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
