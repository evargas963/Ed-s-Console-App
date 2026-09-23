"""The console process's own source, as a set of files: the static import closure of server.py.

Single-producer / single-writer locks must scope to the whole running console, not to one
file -- a lock that reads only server.py passes vacuously the moment its subject is moved to a
module (RC-REHAB-1 moved most of server.py into modules). Imports are followed wherever they
appear in a file, lazy in-function imports included, so a producer reached only through a
deferred `import x` inside a function is still inside the scope. Offline tools and research
scripts the console never imports are outside it by construction.
"""
from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def console_runtime_sources() -> tuple[tuple[str, str, ast.AST], ...]:
    """(repo-relative posix path, source, parsed tree) for every repo module the console can
    import, server.py first."""
    seen: dict[str, Path] = {}
    todo = ["server"]
    while todo:
        mod = todo.pop()
        if mod in seen:
            continue
        path = ROOT / (mod.replace(".", "/") + ".py")
        if not path.is_file():
            path = ROOT / mod.replace(".", "/") / "__init__.py"
            if not path.is_file():
                continue
        seen[mod] = path
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                todo += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                todo.append(node.module)
                todo += [f"{node.module}.{a.name}" for a in node.names]
    out = []
    for mod, path in seen.items():
        src = path.read_text(encoding="utf-8")
        out.append((path.relative_to(ROOT).as_posix(), src, ast.parse(src)))
    out.sort(key=lambda t: (t[0] != "server.py", t[0]))
    return tuple(out)
