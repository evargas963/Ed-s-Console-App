"""AGENTS.md rule 1, no patches: the code shapes a machine can refuse on a pull request.

A check of shapes only. It cannot see a design-level patch; that is review's. That a product change
is proven end to end is check_fails_before's: an end-to-end path test that fails on the old code. A
file whose code is the same once comments and docstrings are set aside (code_identical: the Python
syntax tree; page code's syntax tree from Babel, tools/js_code_tree.js), or whose change is exactly
the standard tools' own (ruff's safe fixes with the PR's committed pyproject.toml, then ruff format:
tool_fixed), is not a change of product code. An .html page or a .bat file is always one, and so
is removing code nothing calls, a deleted file included.

The whole repository is judged (operator 2026-11-04: everything is repo wide): every file's shapes
are counted on the base and the head and printed, and in every file whose code the PR changes
(tests and tools as much as product code), a shape is refused on a line the PR adds, or on an
unchanged line that did not hold it before (an old except whose log line the PR removes), matched
by what the line says, so a shape pushed down the file is not new and one fixed elsewhere does
not pay for one brought in.

The lines a PR adds carry no patch shape:
   - an except that catches everything (bare, `Exception`, `BaseException`, or a tuple holding
     one), or one whose only statement swallows the error: `pass`, `continue`, a return or an
     assignment of None or a literal, or a call with no re-raise. An except that logs the error
     and carries on is not a patch (the operator's ruling), nor one that raises it on: one whose
     body, at any depth outside a def or class, has a log call as a statement of its own
     (`.debug`, `.info`, `.warning`, `.error`, `.exception`, `.critical`, `.log`) or a raise that
     is bare or carries a cause (`from e`, not `from None`) is never refused, even when that line
     runs on one branch only;
   - `contextlib.suppress`;
   - a missing value replaced by a literal: `x or <literal>`, a None-check ternary or
     `if x is None:` that returns or assigns a literal, `.get(k, <literal>)` (positional or
     `default=`), `.setdefault(k, <number, string or bool>)`, `getattr(o, name, default)`;
   - missing data repaired: `.fillna`, `.dropna`, `.interpolate`, `.bfill`, `.ffill`,
     `nan_to_num`;
   - in page code (`.js`, `.mjs`, the scripts of `.html`): `|| <literal>`, `?? <literal>`,
     `||=` / `??=` a literal, an empty `catch`, `.catch(() => <literal>)`.
   An except, if or with is judged when its own first line is added, not when a line is added
   inside an old one. None stays allowed: it is a missing value served as missing. One running
   total is allowed, exactly `d[k] = d.get(k, 0) + x` (the same `d` and `k` on both sides, the
   default the number 0, `x` not a literal 0): the sum of nothing is 0, a real value, not a
   missing one filled in. A base plus a change has the same shape (`price[t] = price.get(t, 0)
   + move`, whose 0 is an unknown base); no check of shapes can tell it from a sum, so rule 14's
   review is the layer that refuses it
   (the operator's spec v2 of 2026-11-03, an open amendment for this construct only; any other
   default, key, mapping or use of that `.get` is still refused).

The description fills BODY_SECTIONS, with `--body-file`.

Run from the base on every pull request (.github/workflows/locks.yml), so a change cannot edit it:
    python tools/check_end_to_end.py --base origin/main --body-file pr_body.md
Exit 0: none found. Exit 1: each violation on its own line. Exit 2: the check itself failed
(git unavailable, the base unknown, a file of the PR unreadable).
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import subprocess
import sys
import tempfile
import tokenize
from collections import Counter
from pathlib import Path

#: the product files whose added lines are read for patch shapes
SHAPED_SUFFIXES = (".py", ".js", ".mjs", ".html")
PRODUCT_SUFFIXES = (*SHAPED_SUFFIXES, ".bat")
NOT_PRODUCT = ("tests/", "tools/", ".github/", "docs/", "playwright.config.mjs")
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
    r"(null|undefined(?!\w)|0(?!\w)|''|\"\"|\[\]|\{\})\s*\)"
)
SCRIPT_BLOCK = re.compile(r"<script\b[^>]*>(.*?)</script\s*>", re.S | re.I)
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
DATA_REPAIR = {"fillna", "dropna", "interpolate", "bfill", "ffill"}


class ToolError(Exception):
    pass


def _git(root: Path, *args: str, errors: str = "strict") -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, check=True
        ).stdout.decode("utf-8", errors)
    except (subprocess.CalledProcessError, FileNotFoundError, UnicodeDecodeError) as e:
        raise ToolError(f"git {' '.join(args)} failed, or its output could not be read: {e}") from e


def pr_files(root: Path, base: str, kinds: str) -> list[str]:
    """The paths the PR changes in the ways `kinds` names (git's --diff-filter letters), each as
    written (NUL-separated, never quoted), a rename read as its deletion and its addition."""
    out = _git(
        root,
        "diff",
        "--name-only",
        "-z",
        "--no-renames",
        f"--diff-filter={kinds}",
        f"{base}...HEAD",
    )
    return [f for f in out.split("\0") if f]


def _diff_path(header: str) -> str:
    """The path of a diff's `+++ ` header: git C-quotes a name holding a quote, backslash or
    non-ASCII character, and ends one holding a space with a tab."""
    name = header.removesuffix("\t")
    if name.startswith('"'):
        try:
            name = ast.literal_eval("b" + name).decode("utf-8")
        except (SyntaxError, ValueError, UnicodeDecodeError) as e:
            raise ToolError(f"git diff header {header!r} could not be read: {e}") from e
    return name.removeprefix("b/")


def pr_added_lines(root: Path, base: str) -> dict[str, set[int]]:
    """{path: the line numbers, in the PR's version, of the lines the PR adds}, one diff; a moved
    file adds every line it holds."""
    out: dict[str, set[int]] = {}
    path: str | None = None
    header = (
        False  # between a file's `diff --git` and its first hunk: an added line is not a header
    )
    # core.quotePath=true: a quoted name is all escapes, whatever the repository's own setting
    for line in _git(
        root,
        "-c",
        "core.quotePath=true",
        "diff",
        "-U0",
        "--text",  # the head's own attributes and drivers do not decide what the diff shows
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "--diff-filter=AMRT",
        f"{base}...HEAD",
        errors="replace",  # --text prints a binary file's bytes; pr_source reads what is judged
    ).split("\n"):
        if line.startswith("diff --git "):
            path, header = None, True
        elif header and line.startswith("+++ ") and line != "+++ /dev/null":
            path = _diff_path(line[len("+++ ") :])
            out[path] = set()
        elif line.startswith("@@ "):
            header = False
            m = HUNK.match(line)
            if m and path is not None:
                start, count = int(m.group(1)), int(m.group(2) or 1)
                out[path].update(range(start, start + count))
    return out


def pr_source(root: Path, path: str) -> str:
    """The PR's committed version of `path`, never the working tree."""
    return _git(root, "show", f"HEAD:{path}")


def is_product(path: str) -> bool:
    return path.endswith(PRODUCT_SUFFIXES) and not path.startswith(NOT_PRODUCT)


JS_CODE_TREE = Path(__file__).resolve().parent / "js_code_tree.js"
#: the files whose code a syntax tree reads exactly; an .html page is not one (a browser's
#: reading of its whitespace, entities and comments depends on CSS and parser details), so every
#: change to one is a change of product code
CODE_TREE_SUFFIXES = (".py", ".js", ".mjs")


def _python_code(source: str) -> str | None:
    """The module's code with its comments and docstrings set aside (its syntax tree), or None when
    it does not parse or declares an encoding other than UTF-8 (imported, its strings would read
    otherwise than this tree)."""
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(source.encode("utf-8")).readline)
        tree = ast.parse(source)
    except (SyntaxError, UnicodeError):
        return None
    if encoding not in ("utf-8", "utf-8-sig"):
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                node.body = node.body[1:] or [ast.Pass()]
    return ast.dump(tree)


def _js_code(text: str, module: bool = False) -> str | None:
    """Page code's syntax tree, comments and positions set aside (Babel, through js_code_tree.js);
    None when it does not parse or Node cannot run it, which counts as changed."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / ("code.mjs" if module else "code.js")
        src.write_bytes(text.encode("utf-8"))  # as written: no line ending translated
        try:
            run = subprocess.run(
                ["node", str(JS_CODE_TREE), str(src)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
    return run.stdout if run.returncode == 0 and run.stdout else None


def code_tree(path: str, text: str) -> str | None:
    """`path`'s code, comments and docstrings set aside: Python's syntax tree, or page code's syntax
    tree; None when it cannot be read or `path` is not one of CODE_TREE_SUFFIXES."""
    if path.endswith(".py"):
        return _python_code(text)
    if path.endswith((".js", ".mjs")):
        return _js_code(text, module=path.endswith(".mjs"))
    return None


#: the lines of ruff's resolved settings (`ruff check --show-settings`, extended files included)
#: that decide whether a fix ruff calls safe is safe here: unsafe fixes off, no fix forced safe, no
#: import required of every file, and the Python the fixes are made for the base's (a fix is safe
#: only for its target version)
FIX_SAFETY = (
    "unsafe_fixes",
    "linter.safety_table.forced_safe",
    "linter.unresolved_target_version",
    "linter.per_file_target_version",
    "formatter.unresolved_target_version",
    "formatter.per_file_target_version",
    "linter.isort.required_imports",
)


def fix_safety(root: Path, config: Path) -> dict[str, str] | None:
    """FIX_SAFETY's values as ruff resolves them from `config`; None when ruff cannot."""
    try:
        run = subprocess.run(
            [
                sys.executable,
                "-P",
                "-m",
                "ruff",
                "check",
                "--show-settings",
                "--config",
                str(config),
            ]
            + ["pyproject.toml"],
            capture_output=True,
            cwd=root,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = (line.partition(" = ") for line in run.stdout.decode("utf-8", "replace").splitlines())
    found = {k: v for k, _, v in lines if k in FIX_SAFETY}
    return found if run.returncode == 0 and len(found) == len(FIX_SAFETY) else None


def tools_fix_is_safe(root: Path, base: str) -> bool:
    """Whether ruff, run on the PR's committed pyproject.toml, takes only fixes that are safe for
    the base's Python: unsafe fixes not on, none forced safe, no import required of every file, no
    per-file target version, the same target versions."""
    try:
        _git(root, "diff", "--quiet", "HEAD", "--", "pyproject.toml")  # the tree is the commit's
        old = _git(root, "show", f"{_git(root, 'merge-base', base, 'HEAD').strip()}:pyproject.toml")
    except ToolError:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "pyproject.toml").write_text(old, encoding="utf-8")
        was = fix_safety(root, Path(tmp) / "pyproject.toml")
    now = fix_safety(root, root / "pyproject.toml")
    if was is None or now is None:
        return False
    return (
        now["unsafe_fixes"] != "enabled"
        and now["linter.safety_table.forced_safe"] == "[]"
        and now["linter.isort.required_imports"] == "[]"  # a fix that adds code, not tidies it
        and all(now[k] == "{}" for k in FIX_SAFETY if "per_file" in k)  # a map prints on many lines
        and all(now[k] == was[k] for k in FIX_SAFETY if "unresolved_target" in k)
    )


def tool_fixed(root: Path, path: str, text: str) -> str | None:
    """`text` as the repository's standard tools leave it: ruff's safe fixes with the repository's
    pyproject.toml, then `ruff format`, as the commit hook runs them; None when either cannot run on
    it (its callers first check that the configuration takes only safe fixes: tools_fix_is_safe)."""
    out = text.encode("utf-8")  # as bytes: no line ending translated on the way in or out
    for args in (
        ["check", "--fix", "--no-unsafe-fixes", "--exit-zero", "--quiet"],
        ["format", "--quiet"],
    ):
        try:
            run = subprocess.run(
                [sys.executable, "-P", "-m", "ruff", *args, "--config", "pyproject.toml"]
                + ["--stdin-filename", path, "-"],
                input=out,
                capture_output=True,
                cwd=root,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if run.returncode != 0:
            return None
        out = run.stdout
    return out.decode("utf-8")


def code_identical(root: Path, base: str, path: str) -> bool:
    """Whether the PR leaves `path`'s code as it is on `base` once comments and docstrings are set
    aside, or changes it only as the repository's standard tools do (tool_fixed, with the PR's
    committed pyproject.toml when tools_fix_is_safe, reproduces the PR's file from the base's): such
    a change has nothing for a test to fail on, so it needs none. A file new to the PR, renamed,
    deleted, not one of CODE_TREE_SUFFIXES, or one either version of which cannot be read is not
    that."""
    try:
        old = _git(root, "show", f"{_git(root, 'merge-base', base, 'HEAD').strip()}:{path}")
        new = pr_source(root, path)
    except ToolError:
        return False
    before, after = code_tree(path, old), code_tree(path, new)
    if before is None:
        return False
    if before == after:
        return True
    return (
        path.endswith(".py")
        and tools_fix_is_safe(root, base)
        and tool_fixed(root, path, old) == new
    )


def behavior_change(root: Path, base: str, path: str) -> bool:
    """A product file whose code the PR changes (is_product, and not code_identical)."""
    return is_product(path) and not code_identical(root, base, path)


def deleted_product(root: Path, base: str) -> list[str]:
    """The product files the PR deletes, a file moved away included: removing code is a change of
    it, whatever called it."""
    return [f for f in pr_files(root, base, "D") if is_product(f)]


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
    return (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], (ast.Is, ast.IsNot, ast.Eq, ast.NotEq))
        and any(_is_none(c) for c in (test.left, *test.comparators))
    )


def _reports(handler: ast.ExceptHandler) -> bool:
    """At any depth of its own body, the except has a log call as a statement of its own, or a
    raise that is bare or carries a cause (`from e`, not `from None`): not a patch. A def or
    class inside it does not run when the error does, so it is not read."""
    stack: list[ast.AST] = list(handler.body)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(n, ast.Raise) and (
            n.exc is None or (n.cause is not None and not _is_none(n.cause))
        ):
            return True
        if (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Attribute)
            and n.value.func.attr in LOG_METHODS
        ):
            return True
        stack.extend(ast.iter_child_nodes(n))
    return False


def _swallows(stmt: ast.stmt) -> bool:
    """The one statement of an except body turns the error into silence."""
    value = getattr(stmt, "value", None)
    return (
        isinstance(stmt, (ast.Pass, ast.Continue, ast.Expr))
        or (isinstance(stmt, ast.Return) and (value is None or _is_none(value) or _literal(value)))
        or (
            isinstance(stmt, (ast.Assign, ast.AnnAssign))
            and value is not None
            and (_is_none(value) or _literal(value))
        )
    )


def _literal_fallback(stmt: ast.stmt) -> bool:
    """The one statement of an `if x is None:` returns or assigns a literal."""
    value = getattr(stmt, "value", None)
    return (
        isinstance(stmt, (ast.Return, ast.Assign, ast.AnnAssign))
        and value is not None
        and _literal(value)
    )


def _call_patch(node: ast.Call) -> str | None:
    f = node.func
    attr = f.attr if isinstance(f, ast.Attribute) else None
    name = f.id if isinstance(f, ast.Name) else None
    if attr == "get" and (
        len(node.args) == 2
        and _literal(node.args[1])
        or any(k.arg == "default" and _literal(k.value) for k in node.keywords)
    ):
        return "a missing value replaced by a literal (`.get(key, <literal>)`)"
    if (
        attr == "setdefault"
        and len(node.args) == 2
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value is not None
    ):
        return "a missing value replaced by a literal (`.setdefault(key, <literal>)`)"
    if attr in DATA_REPAIR:
        return f"missing data repaired (`.{attr}(...)`) instead of served as missing"
    if "nan_to_num" in (attr, name):
        return "NaN turned into a number (`nan_to_num`) instead of served as missing"
    if name == "getattr" and len(node.args) == 3:
        return "a missing value replaced by a default (`getattr(o, name, default)`)"
    return None


def _zero_literal(node: ast.expr) -> bool:
    """A literal zero or empty value, signed or not (`0`, `0.0`, `-0`, `''`, `None`)."""
    while isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        node = node.operand
    return isinstance(node, ast.Constant) and not node.value


def _running_totals(tree: ast.AST) -> set[int]:
    """The `.get` calls of running totals, `d[k] = d.get(k, 0) + x`: the same mapping and key on
    both sides, the default the number 0 (an int or float, never a bool), and `x` not a literal
    zero or empty value (`d.get(k, 0) + 0` writes a filled-in 0)."""
    out = set()
    for n in ast.walk(tree):
        if not (
            isinstance(n, ast.Assign)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Subscript)
            and isinstance(n.value, ast.BinOp)
            and isinstance(n.value.op, ast.Add)
            and isinstance(n.value.left, ast.Call)
        ):
            continue
        target, call = n.targets[0], n.value.left
        if (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "get"
            and len(call.args) == 2
            and not call.keywords
            and isinstance(call.args[1], ast.Constant)
            and type(call.args[1].value) in (int, float)
            and call.args[1].value == 0
            and ast.dump(call.func.value) == ast.dump(target.value)
            and ast.dump(call.args[0]) == ast.dump(target.slice)
            and not _zero_literal(n.value.right)
        ):
            out.add(id(call))
    return out


def python_patches(source: str, added: set[int]) -> list[tuple[int, str]]:
    """The patch shapes the PR adds to a Python file."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [(e.lineno or 1, f"does not parse: {e.msg}")]
    totals = _running_totals(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.ExceptHandler, ast.If, ast.With)):
            if node.lineno not in added:  # an old block with a line added inside it
                continue
            if isinstance(node, ast.ExceptHandler):
                if _reports(node):
                    continue
                if _catches_everything(node):
                    found.append((node.lineno, "an except that catches everything"))
                if len(node.body) == 1 and _swallows(node.body[0]):
                    found.append((node.lineno, "an except that swallows the error"))
            elif isinstance(node, ast.If):
                if (
                    _none_check(node.test)
                    and len(node.body) == 1
                    and _literal_fallback(node.body[0])
                ):
                    found.append(
                        (
                            node.lineno,
                            "a missing value replaced by a literal "
                            "(`if x is None:` then a literal)",
                        )
                    )
            elif any(
                isinstance(i.context_expr, ast.Call)
                and "suppress"
                in (
                    getattr(i.context_expr.func, "id", None),
                    getattr(i.context_expr.func, "attr", None),
                )
                for i in node.items
            ):
                found.append((node.lineno, "an error swallowed (`contextlib.suppress`)"))
        elif isinstance(node, (ast.BoolOp, ast.IfExp, ast.Call)) and _spans_added(node, added):
            if isinstance(node, ast.BoolOp):
                if isinstance(node.op, ast.Or) and _literal(node.values[-1]):
                    found.append(
                        (node.lineno, "a missing value replaced by a literal (`or <literal>`)")
                    )
            elif isinstance(node, ast.IfExp):
                if _none_check(node.test) and (_literal(node.body) or _literal(node.orelse)):
                    found.append(
                        (
                            node.lineno,
                            "a missing value replaced by a literal (a None-check ternary)",
                        )
                    )
            elif id(node) not in totals and (what := _call_patch(node)) is not None:
                found.append((node.lineno, what))
    return sorted(set(found))


def js_patches(path: str, source: str, added: set[int]) -> list[tuple[int, str]]:
    """The patch shapes the PR adds to page code (an .html file: its scripts only)."""
    blocks = (
        [(m.start(1), m.group(1)) for m in SCRIPT_BLOCK.finditer(source)]
        if path.endswith(".html")
        else [(0, source)]
    )
    found = []
    for offset, text in blocks:
        first = source.count("\n", 0, offset) + 1
        for m in JS_PATCH.finditer(text):
            start = first + text.count("\n", 0, m.start())
            end = first + text.count("\n", 0, m.end())
            if any(n in added for n in range(start, end + 1)):
                found.append(
                    (
                        start,
                        "a missing value replaced by a literal, an empty catch, "
                        "or a swallowing .catch",
                    )
                )
    return sorted(set(found))


def shapes(path: str, source: str) -> list[tuple[int, str, str]]:
    """Every patch shape in `source`, each line judged: (line, what, that line's text)."""
    every = set(range(1, source.count("\n") + 2))
    found = (
        python_patches(source, every) if path.endswith(".py") else js_patches(path, source, every)
    )
    text = source.split("\n")
    return [(line, what, text[line - 1].strip()) for line, what in found]


def shapes_at(root: Path, rev: str) -> int:
    """How many patch shapes every file of the repository holds at `rev`."""
    return sum(
        len(shapes(f, _git(root, "show", f"{rev}:{f}", errors="replace")))
        for f in _git(root, "ls-tree", "-r", "-z", "--name-only", rev).split("\0")
        if f.endswith(SHAPED_SUFFIXES)
    )


def violations(root: Path, base: str) -> list[str]:
    """Each patch shape the PR brings into any file of the repository: on a line it adds, or one
    no added line carries (an old except whose log line it removes), matched by what the line says
    so a shape moved down the file is not new and one removed elsewhere does not pay for it."""
    fork = _git(root, "merge-base", base, "HEAD").strip()
    print(f"patch shapes, repo wide: {shapes_at(root, fork)} -> {shapes_at(root, 'HEAD')}")
    out = []
    added = pr_added_lines(root, base)
    new_files = set(pr_files(root, base, "A"))
    for f in pr_files(root, base, "AMT"):
        if not f.endswith(SHAPED_SUFFIXES) or code_identical(root, base, f):
            continue
        old_text = "" if f in new_files else _git(root, "show", f"{fork}:{f}", errors="replace")
        was = shapes(f, old_text) if old_text else []
        old = Counter((what, text) for _, what, text in was)
        for line, what, text in shapes(f, pr_source(root, f)):
            if line not in added.get(f, set()) and old[(what, text)]:
                old[(what, text)] -= 1  # an unchanged line that held this shape already
            else:
                out.append(f"{f}:{line}: {what}")
    return out


def body_violations(body: str) -> list[str]:
    """Each section the description must fill: BODY_SECTIONS, with an arrow in any spelling."""
    norm = re.sub(r"<!--.*?-->", "", body, flags=re.S).replace("->", "→").replace("=>", "→")
    hits = sorted((norm.find(s), s) for s in BODY_SECTIONS if s in norm)
    out = [f"the description lacks: {s}" for s in BODY_SECTIONS if s not in norm]
    ends = [at for at, _section in hits[1:]] + [len(norm)]
    for (at, section), end in zip(hits, ends, strict=False):
        if not norm[at + len(section) : end].split("\n## ")[0].strip():
            out.append(f"the description's {section} is empty")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--body-file", type=Path)
    a = ap.parse_args(argv)
    try:
        found = violations(Path.cwd(), a.base)
        if a.body_file:
            found += body_violations(a.body_file.read_text(encoding="utf-8"))
    except (ToolError, OSError) as e:
        print(f"the check failed: {e}", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")  # a file name may hold any character
    for v in found:
        print(v)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
