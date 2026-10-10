"""Cleanup: a name a change deletes leaves no mention behind.

A name is deleted when the change removes its definition from the Python files it changes: a
module-level function, class, constant or variable, a method, a class attribute, a dataclass field,
an attribute a method assigns on `self`, or a table or column its SQL creates. If, after the change,
the name is bound nowhere in the repository's Python (no definition, assignment, argument, import,
dict key, SQL table or column, or module of that name), every remaining mention of it in the
repository's files (in the working tree, also those git would add) is stale and the change is
refused: code, comments, docstrings, documents, scripts and pages. Data is not searched: data files
(.json, .jsonl, .csv) hold payloads as they were recorded, and a string literal in a test under
tests/ (not its docstring) is what the test expects or asserts absent.
A name that is a plain word (letters only: lowercase, Capitalized or ALL CAPS) is searched only
where it can name the deleted definition, in Python code: a bare name, an attribute of `self`,
`cls` or a repository module, or an import from a repository module. In prose, in JavaScript and
on a library's objects the same word is a different thing.

    python tools/check_stale_references.py --base origin/main [--head REV]
Without --head the working tree is judged. Exit 0: no stale mention. Exit 1: refused, each mention
named. Exit 2: the check itself failed (git unavailable, the base unknown, a file that will not parse).
"""
from __future__ import annotations

import argparse
import ast
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

DATA_FILES = (".json", ".jsonl", ".csv")
IDENTIFIER = re.compile(r"(?<![\w$])[A-Za-z_$][\w$]*")
PLAIN_WORD = re.compile(r"[A-Za-z][a-z]*|[A-Z]+")
SQL_CREATE = re.compile(r"CREATE\s+(?:TEMP(?:ORARY)?\s+)?(?:TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.I)
SQL_ADD_COLUMN = re.compile(r"ADD\s+COLUMN\s+(\w+)", re.I)
SQL_CONSTRAINTS = {"PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT"}
STRING_TOKENS = {tokenize.STRING, tokenize.FSTRING_MIDDLE}


class ToolError(Exception):
    pass


def _git(root: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
    except FileNotFoundError as e:
        raise ToolError(f"git unavailable: {e}") from e
    if r.returncode != 0:
        raise ToolError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


class Tree:
    """The files of one revision, read through one `git cat-file` process, or of the working tree
    when `rev` is None."""

    def __init__(self, root: Path, rev: str | None) -> None:
        self.root, self.rev = root, rev
        self._cat = None if rev is None else subprocess.Popen(
            ["git", "cat-file", "--batch"], cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def read(self, path: str) -> str | None:
        if self._cat is None:
            p = self.root / path
            return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None
        self._cat.stdin.write(f"{self.rev}:{path}\n".encode())
        self._cat.stdin.flush()
        header = self._cat.stdout.readline().split()
        if len(header) != 3 or header[1] != b"blob":
            return None
        data = self._cat.stdout.read(int(header[2]) + 1)[:-1]
        return data.decode("utf-8", errors="replace")

    def paths(self) -> list[str]:
        """The revision's files, or the working tree's files git tracks or would add."""
        listing = ["ls-tree", "-r", "--name-only", self.rev] if self.rev else [
            "ls-files", "--cached", "--others", "--exclude-standard"]
        return [p for p in _git(self.root, *listing).splitlines() if self.rev or (self.root / p).is_file()]

    def close(self) -> None:
        if self._cat is not None:
            self._cat.stdin.close()
            self._cat.wait()


def definitions(src: str) -> set[str]:
    """Module-level and class-level names, and attributes the class's methods assign on self."""
    out: set[str] = set()

    def targets(node: ast.AST) -> list[str]:
        if isinstance(node, ast.Name):
            return [node.id]
        if isinstance(node, (ast.Tuple, ast.List)):
            return [n for e in node.elts for n in targets(e)]
        return []

    def scope(body: list[ast.stmt], in_class: bool) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.add(node.name)
            if isinstance(node, ast.ClassDef):
                scope(node.body, True)
            elif isinstance(node, ast.Assign):
                out.update(n for t in node.targets for n in targets(t))
            elif isinstance(node, ast.AnnAssign):
                out.update(targets(node.target))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and in_class:
                out.update(n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)
                           and isinstance(n.ctx, ast.Store) and isinstance(n.value, ast.Name)
                           and n.value.id == "self")
            elif isinstance(node, (ast.If, ast.Try, ast.With)):
                scope([s for s in ast.iter_child_nodes(node) if isinstance(s, ast.stmt)], in_class)

    tree = ast.parse(src)
    scope(tree.body, False)
    return out | _sql_definitions(tree)


def _sql_definitions(tree: ast.AST) -> set[str]:
    """Tables, views and columns the module's SQL strings create."""
    out: set[str] = set()
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Constant) and isinstance(n.value, str)):
            continue
        sql = re.sub(r"--[^\n]*", "", n.value)
        out.update(SQL_ADD_COLUMN.findall(sql))
        for m in SQL_CREATE.finditer(sql):
            out.add(m.group(1))
            depth, start, items = 0, 0, []
            for i, ch in enumerate(sql[m.end():]):
                if ch == "(":
                    depth += 1
                    start = i + 1 if depth == 1 else start
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        items.append(sql[m.end() + start:m.end() + i])
                        break
                elif ch == "," and depth == 1:
                    items.append(sql[m.end() + start:m.end() + i])
                    start = i + 1
                elif depth == 0 and not ch.isspace():
                    break
            out.update(w[0].strip('"`[]') for w in (it.split() for it in items)
                       if w and w[0].upper() not in SQL_CONSTRAINTS)
    return out


def bindings(src: str) -> set[str]:
    """Every name the source binds anywhere: definitions, assignments, arguments, imports, and
    the tables and columns its SQL creates."""
    tree = ast.parse(src)
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store):
            out.add(n.attr)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, ast.alias):
            out.add((n.asname or n.name).split(".")[0])
        elif isinstance(n, ast.Dict):
            out.update(k.value for k in n.keys if isinstance(k, ast.Constant) and isinstance(k.value, str))
        elif isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store) and isinstance(
                n.slice, ast.Constant) and isinstance(n.slice.value, str):
            out.add(n.slice.value)
    return out | _sql_definitions(tree)


def _code_words(src: str, repo_modules: set[str]) -> dict[int, set[str]]:
    """{line: identifiers} of Python code that can name a repository definition: names, and
    attributes of `self`, `cls` or a repository module."""
    tree = ast.parse(src)
    owners = {"self", "cls"} | {(a.asname or a.name).split(".")[0] for n in ast.walk(tree)
                                if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names
                                if (getattr(n, "module", None) or a.name).split(".")[0] in repo_modules}
    out: dict[int, set[str]] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            out.setdefault(n.lineno, set()).add(n.id)
        elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in owners:
            out.setdefault(n.end_lineno, set()).add(n.attr)
        elif isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] in repo_modules | {""}:
            out.setdefault(n.lineno, set()).update(a.name for a in n.names)
    return out


def removed_names(root: Path, base: Tree, head: Tree) -> dict[str, str]:
    """{name: the file whose change removed its definition}."""
    revs = [base.rev] if head.rev is None else [base.rev, head.rev]
    out: dict[str, str] = {}
    for line in _git(root, "diff", "--name-status", "-M", *revs, "--", "*.py").splitlines():
        parts = line.split("\t")
        old, new = parts[1], parts[-1]
        before = base.read(old)
        if before is None:
            continue
        after = None if parts[0].startswith("D") else head.read(new)
        for name in definitions(before) - (definitions(after) if after else set()):
            out.setdefault(name, old)
    return out


def _without_test_data(src: str) -> str:
    """A test's source with its string literals blanked, docstrings kept: a name a test holds as
    data (an expected finding, an absence it asserts) is not a reference to it."""
    try:
        tree = ast.parse(src)
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (SyntaxError, tokenize.TokenError):
        return src
    docstrings = {(n.body[0].lineno, n.body[0].col_offset) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)
                  and isinstance(n.body[0].value.value, str)}
    lines = src.splitlines(keepends=True)
    for tok in tokens:
        if tok.type not in STRING_TOKENS or tok.start in docstrings:
            continue
        (r0, c0), (r1, c1) = tok.start, tok.end
        for r in range(r0, r1 + 1):
            line = lines[r - 1]
            a, b = (c0 if r == r0 else 0), (c1 if r == r1 else len(line.rstrip("\r\n")))
            lines[r - 1] = line[:a] + " " * (b - a) + line[b:]
    return "".join(lines)


def _mentions(head: Tree, paths: list[str], names: set[str]) -> list[tuple[str, int, str]]:
    """(path, line number, name) for every word of a text file in `paths` that is one of `names`."""
    out = []
    for path in paths:
        text = "" if path.endswith(DATA_FILES) else head.read(path) or ""
        if "\0" in text or not names.intersection(IDENTIFIER.findall(text)):
            continue
        if path.endswith(".py") and "tests" in path.split("/")[:-1]:
            text = _without_test_data(text)
        for num, line in enumerate(text.splitlines(), 1):
            out.extend((path, num, w) for w in dict.fromkeys(IDENTIFIER.findall(line)) if w in names)
    return out


def stale_mentions(root: Path, base: Tree, head: Tree) -> list[str]:
    removed = removed_names(root, base, head)
    if not removed:
        return []
    paths = head.paths()
    python = [p for p in paths if p.endswith(".py")]
    repo_modules = {part.removesuffix(".py") for p in python for part in p.split("/")}
    bound = set(repo_modules)
    for path in sorted({p for p, _, _ in _mentions(head, python, set(removed))}):
        bound |= bindings(head.read(path) or "")
    stale = set(removed) - bound
    code: dict[str, dict[int, set[str]]] = {}
    out = []
    for path, num, name in _mentions(head, paths, stale) if stale else []:
        if PLAIN_WORD.fullmatch(name):
            if not path.endswith(".py"):
                continue
            if path not in code:
                code[path] = _code_words(head.read(path) or "", repo_modules)
            if name not in code[path].get(num, set()):
                continue
        out.append(f"{path}:{num}: `{name}` is still mentioned; this change removed its last "
                   f"definition ({removed[name]})")
    return out


def violations(root: Path, base: str, head: str | None = None) -> list[str]:
    trees = Tree(root, base), Tree(root, head)
    try:
        return stale_mentions(root, *trees)
    finally:
        for t in trees:
            t.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default=None, help="a revision; the working tree when omitted")
    a = ap.parse_args(argv)
    try:
        found = violations(Path.cwd(), a.base, a.head)
    except (ToolError, SyntaxError) as e:
        print(f"the check failed: {e}", file=sys.stderr)
        return 2
    for v in found:
        print(v)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
