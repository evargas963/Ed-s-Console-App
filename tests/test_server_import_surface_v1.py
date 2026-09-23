"""Every `from server import X` in the repo must resolve (RC-REHAB-1, 2026-09-23).

The server.py decomposition moves code out of server.py slice by slice. Thirty-third slice:
removing server.py's now-unused `total_gamma_raw_at_strike` import broke
app/api/routes/terrain.py, which imported that pure math helper THROUGH server inside a
multi-line `from server import (...)` inside a function body. A text grep for the name on
the import line missed it, and only the terrain-strikes route tests caught it. This walks
every tracked .py file's AST, so any importer of a name server.py no longer exports fails
here, before a route 500s at request time.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_every_from_server_import_resolves():
    import server

    files = subprocess.run(["git", "ls-files", "*.py"], cwd=REPO, capture_output=True,
                           text=True, check=True).stdout.split()
    assert files, "git ls-files returned nothing -- the scan population is empty"
    missing = []
    for rel in files:
        try:
            tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "server" and node.level == 0:
                missing += [f"{rel}:{node.lineno} {a.name}" for a in node.names
                            if a.name != "*" and not hasattr(server, a.name)]
    assert not missing, (
        "names imported from server that server.py no longer exports (import them from "
        "their real module instead of re-adding a server.py alias): " + ", ".join(missing))
