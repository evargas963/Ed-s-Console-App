"""ENF-23 (AGENTS.md rule 3): no module becomes a raw reader of a Schwab field another module reads.

The fields judged are the names in `docs/schwab_fields.csv` that are Schwab's own: each canonical
field's last name in Schwab's spelling, an uppercase streamer field (`LAST_PRICE`, `DELTA`) or a
camelCase REST field (`openInterest`). A plain lowercase word (`status`, `symbol`, `gamma`) is also the name
of our own records' keys, so a read of it says nothing about Schwab; it is not judged. The list is
read from the base and from the pull request, so removing a row does not take a field out.

A module reads a field raw when its code takes it out of a mapping by that name: `x["NAME"]`,
`x.get("NAME")`, `x.pop("NAME")` or `"NAME" in x` / `not in x`, the name written as text or as a
module-level constant holding it (`K = "LAST_PRICE"` ... `x.get(K)`). A write (`x["NAME"] = v`) is
not a read. For each field, the product Python modules (`check_end_to_end.is_product`) that read it
are found at the merge base and on the pull request, and the pull request is refused when a module
that did not read the field at the merge base reads it and the field is then read by more than one
module. Moving a field's one reader and bringing readers into one parser pass; renaming one of
several readers is refused like a new one. Reads through a helper, a constant imported from another
module, a loop over a table of names, `getattr`, `itemgetter` or a `match` pattern are not seen. A field is
keyed by its last name, so two Schwab fields that share one (a quote's BID_PRICE and a book level's)
count together, and a module reading our own record kept in Schwab's spelling counts as a reader
(a record crossing modules is a typed record, ENF-10). `--list` names each field read by name in
more than one module: the candidates to check, each one either a second reader to remove or one of
those two cases.

    python tools/check_one_reader.py --base origin/main      (or --list)
Exit 0: no module began reading a field that has another reader. Exit 1: refused, each field and
module named.
Exit 2: the check itself failed (git unavailable, the base unknown, a file it cannot read or parse,
a field list without its canonical_field column).
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import re
import subprocess
import sys
from pathlib import Path

from tools.check_end_to_end import is_product

FIELDS_CSV = "docs/schwab_fields.csv"
#: Schwab's own spelling: an uppercase streamer field (one word or UPPER_SNAKE) or a camelCase REST field
SCHWAB_SPELLING = re.compile(r"[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)*|[a-z]+(?:[A-Z][a-z0-9]*)+")


class ToolError(Exception):
    pass


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", check=True
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError, UnicodeDecodeError) as e:
        raise ToolError(f"git {' '.join(args)} failed: {e}") from e


def schwab_fields(text: str) -> set[str]:
    """Each field's own name in Schwab's spelling, from the field list's canonical names."""
    out = set()
    for row in csv.DictReader(io.StringIO(text)):
        if "canonical_field" not in row:
            raise ToolError(f"{FIELDS_CSV} has no canonical_field column")
        name = row["canonical_field"].rsplit(".", 1)[-1]
        if SCHWAB_SPELLING.fullmatch(name):
            out.add(name)
    return out


def _constants(tree: ast.Module) -> dict[str, str]:
    """Module-level names bound once to a text (`K = "LAST_PRICE"`)."""
    out = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def fields_read(src: str, fields: set[str]) -> set[str]:
    """The Schwab fields this module takes out of a mapping by name."""
    tree = ast.parse(src)
    named = _constants(tree)

    def key(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return named.get(node.id)
        return None

    found = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Load):
            k = key(n.slice)
        elif (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("get", "pop")
            and n.args
        ):
            k = key(n.args[0])
        elif (
            isinstance(n, ast.Compare)
            and len(n.ops) == 1
            and isinstance(n.ops[0], (ast.In, ast.NotIn))
        ):
            k = key(n.left)
        else:
            continue
        if k in fields:
            found.add(k)
    return found


def readers(root: Path, rev: str, fields: set[str]) -> dict[str, set[str]]:
    """field -> the product modules at `rev` that read it raw."""
    out: dict[str, set[str]] = {}
    for path in _git(root, "ls-tree", "-r", "--name-only", rev).splitlines():
        if not (path.endswith(".py") and is_product(path)):
            continue
        try:
            names = fields_read(_git(root, "show", f"{rev}:{path}"), fields)
        except SyntaxError as e:
            raise ToolError(f"{rev}:{path} does not parse: {e}") from e
        for name in names:
            out.setdefault(name, set()).add(path)
    return out


def _field_list(root: Path, rev: str) -> set[str]:
    return schwab_fields(_git(root, "show", f"{rev}:{FIELDS_CSV}"))


def violations(root: Path, base: str) -> list[str]:
    fork = _git(root, "merge-base", base, "HEAD").strip()
    fields = _field_list(root, fork) | _field_list(root, "HEAD")
    before, after = readers(root, fork, fields), readers(root, "HEAD", fields)
    out = []
    for name in sorted(after):
        was = before.get(name, set())
        added = after[name] - was
        if added and len(after[name]) > 1:
            out.append(
                f"{name}: read raw by {len(after[name])} modules, {len(was)} before "
                f"(added {', '.join(sorted(added))}); one module reads a Schwab field"
            )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    root = Path.cwd()
    try:
        if a.list:
            for name, mods in sorted(readers(root, "HEAD", _field_list(root, "HEAD")).items()):
                if len(mods) > 1:
                    print(f"{name}: {len(mods)} modules: {', '.join(sorted(mods))}")
            return 0
        if not a.base:
            ap.error("--base or --list")
        found = violations(root, a.base)
    except ToolError as e:
        print(f"the check failed: {e}", file=sys.stderr)
        return 2
    for v in found:
        print(v)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
