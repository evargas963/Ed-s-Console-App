"""ONE-31 (AGENTS.md rule 3, operator 2026-10-23): a Schwab field is read raw by one module.

The Schwab fields are the names in `docs/schwab_fields.csv` (each field's last name). A module reads
one raw when its code takes it out of a mapping by that name: `x["NAME"]`, `x.get("NAME")` or
`"NAME" in x`. For each field, the product modules (`check_end_to_end.is_product`, Python) that
read it are found on the base and on the pull request. The pull request is refused when a field
is read by more modules than on the base: a reader is never added, while moving a reader and
bringing every reader into one parser are allowed. `--list` names each field read by more than one
module, the second readers still to remove (ACTIVE_PROGRAM.md ONE-24).

    python tools/check_one_reader.py --base origin/main      (or --list: every field read by more than one module)
Exit 0: no field is read by more modules. Exit 1: refused, each field and module named.
Exit 2: the check itself failed (git unavailable, the base unknown).
"""
from __future__ import annotations

import argparse
import ast
import csv
import io
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_end_to_end import is_product  # noqa: E402

FIELDS_CSV = "docs/schwab_fields.csv"


class ToolError(Exception):
    pass


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8",
                              check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise ToolError(f"git {' '.join(args)} failed: {e}") from e


def schwab_fields(text: str) -> set[str]:
    """Each field's own name, from the field list's canonical names (`chains.*.gamma` -> gamma)."""
    out = set()
    for row in csv.DictReader(io.StringIO(text)):
        name = row["canonical_field"].rsplit(".", 1)[-1]
        if name and name != "*":
            out.add(name)
    return out


def _key(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def fields_read(src: str, fields: set[str]) -> set[str]:
    """The Schwab fields this module takes out of a mapping by name."""
    found = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Subscript):
            k = _key(n.slice)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and n.args:
            k = _key(n.args[0])
        elif isinstance(n, ast.Compare) and len(n.ops) == 1 and isinstance(n.ops[0], (ast.In, ast.NotIn)):
            k = _key(n.left)
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
        src = _git(root, "show", f"{rev}:{path}")
        try:
            names = fields_read(src, fields)
        except SyntaxError:
            continue
        for name in names:
            out.setdefault(name, set()).add(path)
    return out


def violations(root: Path, base: str) -> list[str]:
    fields = schwab_fields(_git(root, "show", f"HEAD:{FIELDS_CSV}"))
    before, after = readers(root, base, fields), readers(root, "HEAD", fields)
    out = []
    for name in sorted(after):
        was = before.get(name, set())
        if len(after[name]) > max(len(was), 1):
            out.append(f"{name}: read raw by {len(after[name])} modules, {len(was)} before "
                       f"(added {', '.join(sorted(after[name] - was))}); one module reads a Schwab field")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    root = Path.cwd()
    try:
        if a.list:
            fields = schwab_fields(_git(root, "show", f"HEAD:{FIELDS_CSV}"))
            for name, mods in sorted(readers(root, "HEAD", fields).items()):
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
