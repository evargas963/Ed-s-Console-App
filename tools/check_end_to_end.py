"""AGENTS.md rule 1, no patches, only end-to-end fixes: what a machine can check on a pull request.

1. A PR that changes product code also changes an end-to-end path test: a
   `tests/test_data_path_*.py` file (a Schwab frame through the real daemon and console) or a
   `tests/e2e/*.spec.js` file (the real page).
2. The product lines it adds carry no patch shape:
   - an except that catches everything (bare `except:`, `except Exception`, `BaseException`);
   - an except that swallows (its body only `pass`, `continue`, or a return of None or a literal);
   - a missing value replaced by a literal: `x or 0` / `or ""` / `or []` / `or {}`,
     `d.get(k, <literal>)`, `getattr(o, name, <default>)`; in page code `|| <literal>`,
     `?? <literal>` and an empty `catch`.
   There is no exceptions list: a defect is fixed where the value is produced.
3. Its description has the sections "Schwab → screen:", "Deleted:" and "End-to-end test:".

Run in CI on every pull request (.github/workflows/hardening.yml):
    python tools/check_end_to_end.py --base origin/main --body-file pr_body.md
Exit 1 lists every violation; exit 0 when there is none.
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

PRODUCT_SUFFIXES = (".py", ".js", ".html")
NOT_PRODUCT = ("tests/", "tools/", ".github/", "docs/")
END_TO_END = (re.compile(r"^tests/test_data_path_[^/]+\.py$"), re.compile(r"^tests/e2e/[^/]+\.spec\.js$"))
BODY_SECTIONS = ("Schwab → screen:", "Deleted:", "End-to-end test:")
JS_PATCH = re.compile(r"\|\|\s*(0|''|\"\"|\[\]|\{\}|null)\b|\?\?\s*(0|''|\"\"|\[\]|\{\})|"
                      r"catch\s*(\([^)]*\))?\s*\{\s*\}|\.catch\(\s*function\s*\([^)]*\)\s*\{\s*\}\s*\)")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def changed_files(root: Path, base: str) -> list[str]:
    return [f for f in _git(root, "diff", "--name-only", "--diff-filter=AMR", f"{base}...HEAD").splitlines() if f]


def added_lines(root: Path, base: str, path: str) -> set[int]:
    """Line numbers, in the PR's version of `path`, of the lines the PR adds."""
    lines: set[int] = set()
    for m in re.finditer(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", _git(root, "diff", "-U0", f"{base}...HEAD", "--", path), re.M):
        start, count = int(m.group(1)), int(m.group(2) or 1)
        lines.update(range(start, start + count))
    return lines


def is_product(path: str) -> bool:
    return path.endswith(PRODUCT_SUFFIXES) and not path.startswith(NOT_PRODUCT)


def _literal(node: ast.AST) -> bool:
    return (isinstance(node, ast.Constant) and node.value is not None) or (
        isinstance(node, (ast.List, ast.Dict, ast.Tuple, ast.Set)) and not getattr(node, "elts", getattr(node, "keys", [1])))


def python_patches(source: str, added: set[int]) -> list[tuple[int, str]]:
    """The patch shapes on `added` lines of a Python file."""
    found = []
    for node in ast.walk(ast.parse(source)):
        line = getattr(node, "lineno", None)
        if line not in added:
            continue
        if isinstance(node, ast.ExceptHandler):
            names = {getattr(node.type, "id", None)} if node.type is not None else {None}
            if names & {None, "Exception", "BaseException"}:
                found.append((line, "an except that catches everything"))
            body = node.body
            if len(body) == 1 and (isinstance(body[0], (ast.Pass, ast.Continue)) or (
                    isinstance(body[0], ast.Return) and (body[0].value is None or isinstance(body[0].value, ast.Constant)))):
                found.append((line, "an except that swallows the error"))
        elif isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or) and _literal(node.values[-1]):
            found.append((line, "a missing value replaced by a literal (`or <literal>`)"))
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "get" and len(node.args) == 2 and _literal(node.args[1]):
                found.append((line, "a missing value replaced by a literal (`.get(key, <literal>)`)"))
            elif isinstance(f, ast.Name) and f.id == "getattr" and len(node.args) == 3:
                found.append((line, "a missing value replaced by a default (`getattr(o, name, default)`)"))
    return sorted(set(found))


def js_patches(source: str, added: set[int]) -> list[tuple[int, str]]:
    return [(n, "a missing value replaced by a literal, or an empty catch")
            for n, text in enumerate(source.splitlines(), start=1) if n in added and JS_PATCH.search(text)]


def violations(root: Path, base: str, body: "str | None") -> list[str]:
    files = changed_files(root, base)
    product = [f for f in files if is_product(f)]
    out = []
    if product and not any(p.match(f) for f in files for p in END_TO_END):
        out.append(f"product code changed ({', '.join(product)}) but no end-to-end path test "
                   "(tests/test_data_path_*.py or tests/e2e/*.spec.js) changed")
    for f in product:
        added = added_lines(root, base, f)
        source = (root / f).read_text(encoding="utf-8")
        found = python_patches(source, added) if f.endswith(".py") else js_patches(source, added)
        out.extend(f"{f}:{line}: {what}" for line, what in found)
    if body is not None:
        missing = [s for s in BODY_SECTIONS if s not in body]
        if missing:
            out.append(f"the PR description lacks: {', '.join(missing)}")
    return out


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--body-file")
    a = ap.parse_args(argv)
    body = Path(a.body_file).read_text(encoding="utf-8") if a.body_file else None
    found = violations(Path.cwd(), a.base, body)
    sys.stdout.reconfigure(encoding="utf-8")       # the section names carry "→"
    for v in found:
        print(v)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
