"""AGENTS.md rule 1, no patches: the code shapes a machine can refuse on a pull request.

A check of shapes only. It cannot see a design-level patch, and it cannot tell whether a changed
test covers the changed behavior; those are proven by behavior tests and review.

1. A PR that changes product code also adds real lines (not blank, not a comment) to an
   end-to-end path test: `tests/test_data_path_*.py` or `tests/e2e/*.spec.js`.
2. The product lines it adds carry no patch shape:
   - an except that catches everything (bare, `Exception`, `BaseException`, or a tuple holding
     one), or one whose only statement swallows the error: `pass`, `continue`, a return or an
     assignment of None or a literal, or a call with no re-raise. An except that logs the error
     and carries on is not a patch (the operator's ruling): one whose body logs (`.debug`,
     `.info`, `.warning`, `.error`, `.exception`, `.critical`, `.log`) is never refused;
   - `contextlib.suppress`;
   - a missing value replaced by a literal: `x or <literal>`, a None-check ternary or
     `if x is None:` that returns or assigns a literal, `.get(k, <literal>)` (positional or
     `default=`), `.setdefault(k, <number, string or bool>)`, `getattr(o, name, default)`;
   - missing data repaired: `.fillna`, `.dropna`, `.interpolate`, `.bfill`, `.ffill`,
     `nan_to_num`;
   - in page code (`.js`, `.mjs`, the scripts of `.html`): `|| <literal>`, `?? <literal>`,
     `||=` / `??=` a literal, an empty `catch`, `.catch(() => <literal>)`.
   An except, if or with is judged when its own first line is added, not when a line is added
   inside an old one. None stays allowed: it is a missing value served as missing.
3. Its description has "Schwab → screen:", "Deleted:" and "End-to-end test:", each with content
   ("->" and "=>" are read as "→").

Run in CI on every pull request (.github/workflows/hardening.yml):
    python tools/check_end_to_end.py --base origin/main --body-file pr_body.md
Exit 0: none found. Exit 1: each violation on its own line. Exit 2: the check itself failed
(git unavailable, the base unknown, a file of the PR unreadable).
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

PRODUCT_SUFFIXES = (".py", ".js", ".mjs", ".html")
NOT_PRODUCT = ("tests/", "tools/", ".github/", "docs/")
END_TO_END = (re.compile(r"^tests/test_data_path_[^/]+\.py$"),
              re.compile(r"^tests/e2e/[^/]+\.spec\.js$"))
BODY_SECTIONS = ("Schwab → screen:", "Deleted:", "End-to-end test:")
CATCH_ALL = ("Exception", "BaseException")
LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
JS_LITERAL = r"(0(?!\w)|''|\"\"|\[\]|\{\}|null(?!\w))"
JS_PATCH = re.compile(
    rf"\|\|\s*{JS_LITERAL}"
    rf"|\?\?\s*{JS_LITERAL}"
    rf"|(\|\||\?\?)=\s*{JS_LITERAL}"
    r"|catch\s*(\([^)]*\))?\s*\{\s*\}"
    r"|\.catch\(\s*(\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*"
    r"(null|undefined(?!\w)|0(?!\w)|''|\"\"|\[\]|\{\})\s*\)")
SCRIPT_BLOCK = re.compile(r"<script\b[^>]*>(.*?)</script\s*>", re.S | re.I)
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
DATA_REPAIR = {"fillna", "dropna", "interpolate", "bfill", "ffill"}


class ToolError(Exception):
    pass


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True,
                              text=True, encoding="utf-8", check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise ToolError(f"git {' '.join(args)} failed: {e}") from e


def pr_added_lines(root: Path, base: str) -> dict[str, set[int]]:
    """{path: the line numbers, in the PR's version, of the lines the PR adds}, one diff."""
    out: dict[str, set[int]] = {}
    path: str | None = None
    for line in _git(root, "diff", "-U0", "--diff-filter=AMR", f"{base}...HEAD").splitlines():
        if line.startswith("diff --git "):
            path = None
        elif line.startswith("+++ b/"):
            path = line[len("+++ b/"):]
            out[path] = set()
        elif line.startswith("@@ ") and path is not None:
            m = HUNK.match(line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) or 1)
                out[path].update(range(start, start + count))
    return out


def pr_source(root: Path, path: str) -> str:
    """The PR's committed version of `path`, never the working tree."""
    return _git(root, "show", f"HEAD:{path}")


def is_product(path: str) -> bool:
    return path.endswith(PRODUCT_SUFFIXES) and not path.startswith(NOT_PRODUCT)


def _spans_added(node: ast.AST, added: set[int]) -> bool:
    start = node.lineno
    return any(n in added for n in range(start, (node.end_lineno or start) + 1))


def _is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _literal(node: ast.AST) -> bool:
    """A non-None literal standing in for a missing value."""
    if isinstance(node, ast.Constant):
        return node.value is not None
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(isinstance(e, ast.Constant) and e.value is not None for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(isinstance(k, ast.Constant) and k.value is not None for k in node.keys)
    return False


def _catches_everything(handler: ast.ExceptHandler) -> bool:
    t = handler.type
    names = t.elts if isinstance(t, ast.Tuple) else [t]
    return t is None or any(isinstance(n, ast.Name) and n.id in CATCH_ALL for n in names)


def _none_check(test: ast.AST) -> bool:
    return (isinstance(test, ast.Compare) and len(test.ops) == 1
            and isinstance(test.ops[0], (ast.Is, ast.IsNot, ast.Eq, ast.NotEq))
            and any(_is_none(c) for c in (test.left, *test.comparators)))


def _logs(handler: ast.ExceptHandler) -> bool:
    """The except logs the error and carries on: not a patch."""
    return any(isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
               and isinstance(s.value.func, ast.Attribute) and s.value.func.attr in LOG_METHODS
               for s in handler.body)


def _swallows(stmt: ast.stmt) -> bool:
    """The one statement of an except body turns the error into silence."""
    value = getattr(stmt, "value", None)
    return (isinstance(stmt, (ast.Pass, ast.Continue, ast.Expr))
            or (isinstance(stmt, ast.Return) and (value is None or _is_none(value) or _literal(value)))
            or (isinstance(stmt, (ast.Assign, ast.AnnAssign)) and value is not None
                and (_is_none(value) or _literal(value))))


def _literal_fallback(stmt: ast.stmt) -> bool:
    """The one statement of an `if x is None:` returns or assigns a literal."""
    value = getattr(stmt, "value", None)
    return isinstance(stmt, (ast.Return, ast.Assign, ast.AnnAssign)) and value is not None and _literal(value)


def _call_patch(node: ast.Call) -> str | None:
    f = node.func
    attr = f.attr if isinstance(f, ast.Attribute) else None
    name = f.id if isinstance(f, ast.Name) else None
    if attr == "get" and (len(node.args) == 2 and _literal(node.args[1]) or any(
            k.arg == "default" and _literal(k.value) for k in node.keywords)):
        return "a missing value replaced by a literal (`.get(key, <literal>)`)"
    if attr == "setdefault" and len(node.args) == 2 and isinstance(node.args[1], ast.Constant) \
            and node.args[1].value is not None:
        return "a missing value replaced by a literal (`.setdefault(key, <literal>)`)"
    if attr in DATA_REPAIR:
        return f"missing data repaired (`.{attr}(...)`) instead of served as missing"
    if "nan_to_num" in (attr, name):
        return "NaN turned into a number (`nan_to_num`) instead of served as missing"
    if name == "getattr" and len(node.args) == 3:
        return "a missing value replaced by a default (`getattr(o, name, default)`)"
    return None


def python_patches(source: str, added: set[int]) -> list[tuple[int, str]]:
    """The patch shapes the PR adds to a Python file."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [(e.lineno or 1, f"does not parse: {e.msg}")]
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.ExceptHandler, ast.If, ast.With)):
            if node.lineno not in added:          # an old block with a line added inside it
                continue
            if isinstance(node, ast.ExceptHandler):
                if _logs(node):
                    continue
                if _catches_everything(node):
                    found.append((node.lineno, "an except that catches everything"))
                if len(node.body) == 1 and _swallows(node.body[0]):
                    found.append((node.lineno, "an except that swallows the error"))
            elif isinstance(node, ast.If):
                if _none_check(node.test) and len(node.body) == 1 and _literal_fallback(node.body[0]):
                    found.append((node.lineno, "a missing value replaced by a literal "
                                               "(`if x is None:` then a literal)"))
            elif any(isinstance(i.context_expr, ast.Call)
                     and "suppress" in (getattr(i.context_expr.func, "id", None),
                                        getattr(i.context_expr.func, "attr", None))
                     for i in node.items):
                found.append((node.lineno, "an error swallowed (`contextlib.suppress`)"))
        elif isinstance(node, (ast.BoolOp, ast.IfExp, ast.Call)) and _spans_added(node, added):
            if isinstance(node, ast.BoolOp):
                if isinstance(node.op, ast.Or) and _literal(node.values[-1]):
                    found.append((node.lineno, "a missing value replaced by a literal (`or <literal>`)"))
            elif isinstance(node, ast.IfExp):
                if _none_check(node.test) and (_literal(node.body) or _literal(node.orelse)):
                    found.append((node.lineno, "a missing value replaced by a literal "
                                               "(a None-check ternary)"))
            elif (what := _call_patch(node)) is not None:
                found.append((node.lineno, what))
    return sorted(set(found))


def js_patches(path: str, source: str, added: set[int]) -> list[tuple[int, str]]:
    """The patch shapes the PR adds to page code (an .html file: its scripts only)."""
    blocks = ([(m.start(1), m.group(1)) for m in SCRIPT_BLOCK.finditer(source)]
              if path.endswith(".html") else [(0, source)])
    found = []
    for offset, text in blocks:
        first = source.count("\n", 0, offset) + 1
        for m in JS_PATCH.finditer(text):
            start = first + text.count("\n", 0, m.start())
            end = first + text.count("\n", 0, m.end())
            if any(n in added for n in range(start, end + 1)):
                found.append((start, "a missing value replaced by a literal, an empty catch, "
                                     "or a swallowing .catch"))
    return sorted(set(found))


def adds_real_lines(source: str, added: set[int]) -> bool:
    return any(n in added and (s := text.strip()) and not s.startswith(("#", "//"))
               for n, text in enumerate(source.splitlines(), start=1))


def body_violations(body: str) -> list[str]:
    text = body.replace("->", "→").replace("=>", "→")
    at = sorted((text.find(s), s) for s in BODY_SECTIONS)
    out = [f"the PR description lacks: {s}" for i, s in at if i < 0]
    present = [(i, s) for i, s in at if i >= 0]
    for k, (i, s) in enumerate(present):
        end = present[k + 1][0] if k + 1 < len(present) else len(text)
        if not text[i + len(s):end].strip():
            out.append(f"the PR description's {s} is empty")
    return out


def violations(root: Path, base: str, body: str | None) -> list[str]:
    added = pr_added_lines(root, base)
    product = sorted(f for f in added if is_product(f))
    out = []
    if product and not any(p.match(f) and adds_real_lines(pr_source(root, f), added[f])
                           for f in added for p in END_TO_END):
        out.append(f"product code changed ({', '.join(product)}) but no end-to-end path test "
                   "(tests/test_data_path_*.py or tests/e2e/*.spec.js) gained a real line")
    for f in product:
        source = pr_source(root, f)
        found = python_patches(source, added[f]) if f.endswith(".py") else js_patches(f, source, added[f])
        out.extend(f"{f}:{line}: {what}" for line, what in found)
    if body is not None:
        out.extend(body_violations(body))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--body-file")
    a = ap.parse_args(argv)
    try:
        body = Path(a.body_file).read_text(encoding="utf-8") if a.body_file else None
        found = violations(Path.cwd(), a.base, body)
    except ToolError as e:
        print(f"the check failed: {e}", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")       # the section names carry "→"
    for v in found:
        print(v)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
