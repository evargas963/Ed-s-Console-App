#!/usr/bin/env python3
"""REPO-WIDE NO-FALLBACK MECHANICAL LOCK (operator mandate 2026-09-17, corrected 2026-09-17
after independent review rejected the first draft's self-authorized exemptions).

GOVERNING RULE this gate enforces: a semantic field may contain only the exact value defined
by that field. If its canonical source is missing/stale/malformed/partial/unauthorized/
rejected/delayed/failed, the field must expose that exact failure state or fail closed --
never a substitute. NO EXEMPTION MECHANISM EXISTS IN THIS FILE. The first draft of this gate
invented a governance/no_fallback_registry.json allowlist and self-wrote "operator_quote"
justifications into it to pre-clear ML imputation and several SQL idioms (aggregate-over-
empty-set COALESCE, display-label defaults, UPDATE-preserve-existing COALESCE) as safe. The
operator rejected this outright: "The operator did not pre-authorize ML imputation" and "these
are fallback candidates and cannot automatically pass." That registry file is deleted. Every
COALESCE/IFNULL/NVL and every pandas imputation call added in a diff is now a violation,
unconditionally -- there is no code path anywhere in this file that can clear one.

TWO DISTINCT VERDICTS THIS GATE REPORTS, NEVER CONFLATED (operator instruction 2026-09-17
clarification: "distinguish 'no new regression' from 'repository clean', but never call the
repository PASS while baseline violations remain"):
  REGRESSION CHECK (diff-scoped, this is the ENFORCED CI check): does the STAGED/compared
    diff introduce a NEW instance of a banned syntactic shape, or weaken this gate itself?
    This can legitimately PASS on an ordinary commit that touches none of these shapes --
    passing it is NOT a claim that the repository is fallback-free.
  BASELINE CENSUS (repo-wide, `--measure`): the CURRENT total count of confirmed FALLBACK
    entries (reports/no_fallback_inventory.json), NOT_PROVEN candidates, and unscanned/parse-
    failed files. This NEVER reports zero/clean while the inventory says otherwise, and
    `main()`'s own top-level verdict text distinguishes the two explicitly so neither is
    mistaken for the other.

RULES ENFORCED BY THE REGRESSION CHECK (all diff-scoped, all zero-allowlist, no per-line or
per-file escape of any kind):
  R1  ANY SQL COALESCE/IFNULL/NVL added, unconditionally. No aggregate exemption, no display-
      label exemption, no UPDATE-preserve-existing exemption -- the operator ruled all three
      "cannot automatically pass."
  R2  ANY pandas imputation call (a fillna-family method) added, unconditionally. No
      authorized-file registry of any kind.
  R3  an except handler body added that assigns an empty collection ([]/{}/set()) or a bare
      0/0.0/'' to a target whose name does NOT itself name the failure (error/status/fail/
      reason/exception) -- i.e. it looks like data, not disclosure.
  R4  JS/JSX `||` or `??` added whose left operand names a PROTECTED field (see
      _protected_field_population below -- derived from the repo's own registered producer
      censuses, not a hand-picked list).
  R5  this file (tools/check_no_fallback_lock.py) is modified in a way that removes or
      shortens a rule function, with NO bypass string of any kind recognized -- any such
      diff is unconditionally flagged for human review; there is nothing in this file that
      can silence that flag.
  R6  a staged file whose extension is not one of the file types this gate knows how to scan
      AND is not in the declared no-op list is an UNKNOWN EXECUTABLE SURFACE -- fails rather
      than silently passing.
  R7  a staged .py/.js/.jsx/.mjs/.html/.sql file that fails to parse is a DISCOVERY FAILURE
      -- fails rather than silently skipping.
  R8  Python `x or y` added whose leading operand names a PROTECTED field, outside a pure
      boolean-test position -- and a Python `.get(key, default)` added with a non-None
      default where key is a PROTECTED field.
  R9  a value assigned from a variable/attribute named as a prior/cached/stale copy into a
      PROTECTED field, in the same added block that also stamps a fresh generation/sequence/
      timestamp field -- the "stale data, fresh badge" shape.

PROTECTED FIELD POPULATION (_protected_field_population): unioned from every registered
producer census this repo already maintains -- governance/computation_registry.json's field
names and level_ids, and every string dict-key literal in server.py (the SAME 592-key payload
universe check_one_producer.py already treats as the field census, "declared payload
surfaces" -- see that file's own PayloadSurfaceMissing fail-closed behavior, reused here
directly rather than re-invented). This is NOT five hand-picked names; it is derived fresh on
every run from the repo's own registries and payload surface, so it grows/shrinks exactly as
those do.

KNOWN, ACKNOWLEDGED LIMIT: a wrapper/alias that conceals a fallback behind a renamed call, or
a same-name-different-meaning / different-name-same-meaning collision, is not mechanically
closed by this gate. check_one_producer.py's own docstring names this same class of gap "D5
shadow... NOT_PROVEN repo-wide" for its own, more mature domain. This file does not claim to
solve it either; see the mission report's own NOT_PROVEN accounting rather than a fabricated
proof of closure.

    .venv/Scripts/python.exe tools/check_no_fallback_lock.py             # regression check, staged diff
    .venv/Scripts/python.exe tools/check_no_fallback_lock.py --base origin/main  # regression check, a branch
    .venv/Scripts/python.exe tools/check_no_fallback_lock.py --measure   # baseline census (repo-wide, never PASS)
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMPUTATION_REGISTRY = REPO / "governance" / "computation_registry.json"
INVENTORY = REPO / "reports" / "no_fallback_inventory.json"

_DECLARED_NOOP_EXTS = {
    ".yaml", ".yml", ".toml", ".json", ".css", ".md", ".txt", ".pt", ".pkl", ".png", ".csv",
    ".gitkeep", ".gitignore", ".example", ".ico", ".webmanifest", ".mdc", ".python-version",
    ".gitattributes", ".jsonl", "",
}
_SCANNABLE_EXTS = {".py", ".js", ".jsx", ".mjs", ".html", ".sql", ".ps1", ".bat"}

_SQL_FALLBACK_RE = re.compile(r"\b(COALESCE|IFNULL|NVL)\s*\(")
_IMPUTATION_RE = re.compile(r"\.(fillna|ffill|bfill|interpolate)\s*\(")

_FAILURE_NAME_RE = re.compile(r"error|status|fail|reason|exception|excep|_err\b", re.I)

_JS_OR_RE = re.compile(
    r"(?P<lhs>[A-Za-z_$][\w.$\[\]'\"]*)\s*(?P<op>\|\||\?\?)\s*(?P<rhs>[^;,)\n]{1,80})")

_STALE_NAME_RE = re.compile(r"prior|cached|last_known|_stale|_carried", re.I)
_FRESH_GEN_NAME_RE = re.compile(r"_ts\b|generation|_seq\b|timestamp", re.I)

#: Rule-implementing function names R5 watches for shrinkage. Kept as an explicit list (not
#: introspected) so a NEW rule function added later is automatically covered by naming
#: convention (`_r<N>_...`) without editing this set.
_RULE_FUNC_PREFIX = "_r"


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


def _protected_field_population() -> set[str]:
    """Derived fresh from the repo's own registered producer censuses -- never a hand-picked
    list. Union of: governance/computation_registry.json's field names + level_ids, and every
    string dict-key literal in server.py (the same 592-key payload universe
    check_one_producer.py already treats as the canonical field census) -- EXCLUDING generic
    disclosure/bookkeeping keys (matching _FAILURE_NAME_RE: *_error, *_status, *_detail,
    *_reason, *_exception) since those are reused across many unrelated failure types with
    no single canonical DATA producer to protect; `ms.state_error = ms.state_error or "X"`
    is first-error-wins aggregation on a disclosure field, not a data-value substitution,
    and was a real false positive in the first version of this population before this
    exclusion was added (caught by this gate's own dogfooding against a real repair)."""
    names: set[str] = set()
    try:
        reg = json.loads(COMPUTATION_REGISTRY.read_text(encoding="utf-8"))
        for field, spec in (reg.get("fields") or {}).items():
            names.add(field)
            names.update(spec.get("level_ids") or [])
    except (OSError, ValueError):
        pass  # a missing/corrupt registry narrows the census; R6/R7 catch a missing SURFACE separately
    server_py = REPO / "server.py"
    if server_py.exists():
        try:
            tree = ast.parse(server_py.read_text(encoding="utf-8", errors="replace"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Dict):
                    for k in node.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            names.add(k.value)
        except SyntaxError:
            pass
    return {n for n in names if not _FAILURE_NAME_RE.search(n)}


#: A line asserting the BANNED pattern's own ABSENCE (the idiom every regression test that
#: locks this repair's own fixes uses, e.g. `assert "COALESCE(...)" not in source`) can
#: never itself be the violation it is proving is gone -- it is meta-code checking for the
#: pattern, structurally the same self-reference class as a comment. Matched narrowly
#: (assert ... not in) so it cannot be used to smuggle real fallback-executing code past
#: the gate under an unrelated assert.
_NEGATIVE_ASSERTION_RE = re.compile(r"\bassert\b.*\bnot\s+in\b")


def _is_comment_line(text: str) -> bool:
    """True when the ENTIRE line is a comment (Python `#` or SQL `--`) or a negative test
    assertion proving a banned pattern's absence -- see _NEGATIVE_ASSERTION_RE. An
    explanatory comment documenting a fix necessarily quotes the banned pattern in prose
    (the RC-47 lesson); a real code line that HAPPENS to carry a trailing comment still
    gets scanned (only a line whose first non-whitespace character starts the comment is
    skipped) -- this narrows false positives without reopening any actual code path."""
    stripped = text.strip()
    return (stripped.startswith("#") or stripped.startswith("--")
            or bool(_NEGATIVE_ASSERTION_RE.search(stripped)))


def _r1_sql(rel: str, added: list[tuple[int, str]]) -> list[Finding]:
    out: list[Finding] = []
    for line_no, text in added:
        if _is_comment_line(text):
            continue
        if _SQL_FALLBACK_RE.search(text):
            out.append(Finding(
                rel, line_no, "R1_SQL_COALESCE",
                f"new COALESCE/IFNULL/NVL added: {text.strip()[:160]!r}. Unconditional ban "
                f"(operator ruling 2026-09-17: no aggregate/display-label/update-preserve "
                f"exemption) -- expose the missing value's own failure state instead."))
    return out


def _r2_imputation(rel: str, added: list[tuple[int, str]]) -> list[Finding]:
    out: list[Finding] = []
    for line_no, text in added:
        if _is_comment_line(text):
            continue
        if _IMPUTATION_RE.search(text):
            out.append(Finding(
                rel, line_no, "R2_IMPUTATION",
                f"new pandas imputation call added: {text.strip()[:160]!r}. Unconditional "
                f"ban (operator ruling 2026-09-17: 'the operator did not pre-authorize ML "
                f"imputation') -- exclude/flag missing rows rather than imputing a value."))
    return out


def _r3_except_substitute(rel: str, src_after: str, added_line_nos: set[int]) -> list[Finding]:
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


def _r4_js_protected_field(rel: str, added: list[tuple[int, str]],
                           protected: set[str]) -> list[Finding]:
    out: list[Finding] = []
    for line_no, text in added:
        code = text.split("//", 1)[0]
        for m in _JS_OR_RE.finditer(code):
            lhs = m.group("lhs")
            base_name = re.split(r"[.\[]", lhs)[-1].strip("'\"")
            if base_name in protected:
                out.append(Finding(
                    rel, line_no, "R4_JS_PROTECTED_FIELD",
                    f"new {m.group('op')} substitution on protected field '{base_name}': "
                    f"{text.strip()[:160]!r}. This field is in the repo's own registered "
                    f"producer census (computation_registry.json / server.py payload keys); "
                    f"render its own disclosed unavailable/stale state instead of "
                    f"substituting a value here."))
    return out


def _r8_python_protected_field(rel: str, src_after: str, added_line_nos: set[int],
                               protected: set[str]) -> list[Finding]:
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
            if _base_name(first) in protected and not _in_bool_test(node):
                out.append(Finding(
                    rel, node.lineno, "R8_PY_PROTECTED_FIELD_OR",
                    f"new `or`-ladder value substitution on protected field "
                    f"'{_base_name(first)}' -- disclose its own unavailable/stale state "
                    f"instead."))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and len(node.args) >= 2):
            key_node = node.args[0]
            key = key_node.value if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str) else ""
            default_trivial = isinstance(node.args[1], ast.Constant) and node.args[1].value is None
            if key in protected and not default_trivial:
                out.append(Finding(
                    rel, node.lineno, "R8_PY_PROTECTED_FIELD_GET",
                    f"new .get('{key}', <non-None default>) on protected field '{key}' -- "
                    f"disclose absence explicitly instead of defaulting it."))
    return out


def _r9_stale_fresh_badge(rel: str, src_after: str, added_line_nos: set[int],
                          protected: set[str]) -> list[Finding]:
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
            if target_name in protected and _STALE_NAME_RE.search(value_name):
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


def _r5_lock_weakened(files: list[str], base: str | None) -> list[Finding]:
    """No bypass string of any kind is recognized here -- a shrinking diff to this file is
    ALWAYS flagged for human review; there is nothing that can silence it from inside a
    commit message, a comment, or a co-staged file."""
    rel = "tools/check_no_fallback_lock.py"
    if rel not in files:
        return []
    removed_args = ["diff", "-U0"]
    removed_args += [f"{base}...HEAD"] if base else ["--cached"]
    removed_args += ["--", rel]
    diff_out = _run(removed_args)
    removed_text = "\n".join(
        ln[1:] for ln in diff_out.splitlines() if ln.startswith("-") and not ln.startswith("---"))
    removed_rule_def = bool(re.search(rf"^def {_RULE_FUNC_PREFIX}\d+_\w+", removed_text, re.M))
    if removed_rule_def:
        return [Finding(rel, 0, "R5_LOCK_WEAKENED",
                        f"{rel}'s diff removes a rule-implementing function definition -- "
                        f"flagged unconditionally for human review; this gate has no "
                        f"mechanism, string, or marker that can clear this flag.")]
    return []


def _r6_r7_unknown_and_parse(files: list[str]) -> list[Finding]:
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
                           f"not know how to scan and is not declared no-op -- an unscanned "
                           f"executable surface fails rather than silently passing."))
    return out


#: This mission's OWN mutation-proof test namespace (tests/test_no_fallback_lock*.py): its
#: entire purpose is to embed the exact banned shapes as fixture strings to prove the gate
#: rejects them (a mission-required PROOF, not production code). Excluding it from content
#: scanning is not a general "tests are exempt" loophole (every OTHER test file, and every
#: fixture inside THIS file's own test bodies for OTHER repos, stays fully in scope) -- it is
#: narrowly this gate's own proof harness reading ITS OWN SOURCE, the same self-reference the
#: RC-47 precedent already forced on check_no_fake_defaults's docstring. This exclusion never
#: applies when THIS gate is run against a DIFFERENT repository (the mutation tests build
#: their own throwaway repo per test; this exclusion is keyed on this gate's own tree only).
_TEST_PROOF_NAMESPACE_PREFIX = "tests/test_no_fallback_lock"

#: The mission's own discovery/adjudication META-TOOLING: these files' entire job is to
#: CATALOG example fallback-shaped snippets found elsewhere (as evidence strings/comments
#: quoting real code from OTHER files, and prose ABOUT the rules this gate enforces) for
#: human/agent reading -- they are governance artifacts about the census, never an
#: execution surface the GOVERNING RULE itself targets. Excluding them is not a fallback
#: allowlist (no PRODUCTION or TEST code path is exempted); it is the same class of
#: exclusion _production_py_files() already applies to tests/tools/research/archive
#: elsewhere in this framework, applied to the files whose necessarily-literal quoted
#: evidence/prose would otherwise self-trigger the gate (the RC-47 lesson, generalized).
_META_TOOLING_EXCLUDED_FROM_CONTENT_RULES = (
    "tools/fallback_discovery.py", "tools/apply_adjudication.py",
)


def violations(base: str | None = None) -> list[str]:
    """The REGRESSION check: does this diff add a new instance of a banned shape? A clean
    result here is NOT a claim the repository is fallback-free -- see measure_baseline()."""
    files = _staged_files(base)
    findings: list[Finding] = []
    protected = _protected_field_population()
    for rel in files:
        path = REPO / rel
        if not path.exists():
            continue
        if (rel.startswith(_TEST_PROOF_NAMESPACE_PREFIX)
                or rel in _META_TOOLING_EXCLUDED_FROM_CONTENT_RULES):
            continue
        ext = path.suffix.lower()
        added = _added_lines(rel, base) if ext in (".py", ".sql", ".js", ".jsx", ".mjs", ".html") else []
        if ext in (".py", ".sql"):
            findings += _r1_sql(rel, added)
        if ext == ".py":
            findings += _r2_imputation(rel, added)
            try:
                src_after = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                src_after = ""
            added_line_nos = {ln for ln, _ in added}
            if src_after:
                findings += _r3_except_substitute(rel, src_after, added_line_nos)
                findings += _r8_python_protected_field(rel, src_after, added_line_nos, protected)
                findings += _r9_stale_fresh_badge(rel, src_after, added_line_nos, protected)
        if ext in (".js", ".jsx", ".mjs", ".html"):
            findings += _r4_js_protected_field(rel, added, protected)
    findings += _r5_lock_weakened(files, base)
    findings += _r6_r7_unknown_and_parse(files)
    return [str(f) for f in findings]


def measure_baseline() -> dict:
    """The BASELINE CENSUS: the repo's true current state, read from
    reports/no_fallback_inventory.json. Never reports clean while the inventory says
    otherwise; missing/unreadable inventory is itself reported as a failure, not silence."""
    if not INVENTORY.exists():
        return {"error": f"{INVENTORY} is missing -- the baseline census cannot be read, "
                          f"which is a FAIL, not an empty/clean result"}
    try:
        data = json.loads(INVENTORY.read_text(encoding="utf-8"))
    except ValueError as e:
        return {"error": f"{INVENTORY} does not parse ({e}) -- FAIL, not silence"}
    verdicts = data.get("verdict_counts") or {}
    return {
        "candidate_count": data.get("candidate_count"),
        "fallback": verdicts.get("FALLBACK", 0),
        "not_proven": verdicts.get("NOT_PROVEN", 0),
        "not_fallback": verdicts.get("NOT_FALLBACK", 0),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default=None,
                    help="compare HEAD against this ref instead of the staged index")
    ap.add_argument("--measure", action="store_true",
                    help="print the baseline census instead of running the regression check")
    args = ap.parse_args(argv)

    if args.measure:
        m = measure_baseline()
        if "error" in m:
            print(f"check_no_fallback_lock --measure: FAIL — {m['error']}")
            return 1
        print(f"BASELINE CENSUS (repo-wide, not diff-scoped): "
              f"{m['fallback']} FALLBACK, {m['not_proven']} NOT_PROVEN, "
              f"{m['not_fallback']} NOT_FALLBACK, of {m['candidate_count']} candidates.")
        if m["fallback"] or m["not_proven"]:
            print("check_no_fallback_lock --measure: FAIL — baseline violations remain; "
                  "this is never reported as PASS/clean while any FALLBACK or NOT_PROVEN "
                  "entry exists.")
            return 1
        print("check_no_fallback_lock --measure: PASS — baseline census is clean.")
        return 0

    try:
        v = violations(args.base)
    except RuntimeError as e:
        print(f"check_no_fallback_lock: FAIL (regression check could not run) — {e}")
        return 1
    if v:
        print("check_no_fallback_lock: FAIL (regression) — this diff adds new fallback "
              "behavior:")
        for line in v:
            print(line)
        return 1
    print("check_no_fallback_lock: PASS (regression) — this diff adds no NEW fallback "
          "behavior. This is NOT a claim the repository is fallback-free; run --measure "
          "for the baseline census.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
