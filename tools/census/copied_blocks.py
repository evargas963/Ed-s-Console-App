"""Blocks of 8 or more lines copied within a file or from one into another: the census's count.

Each file's lines are compared stripped, a run of spaces read as one, leaving out lines of 3
characters or fewer, comments, docstring openers and, in Python, import statements, as pylint's
similarities checker (duplicate-code, R0801) does by default ("Imports are removed from the
similarity computation", ignore-imports, default True; pylint 4.1.4): two modules importing the
same names in isort's order copied nothing.
"""

from __future__ import annotations

import ast
import hashlib
import re
from collections.abc import Iterator

#: the fewest lines a copied block holds
WIN = 8


def import_lines(tree: ast.Module) -> set[int]:
    """Return the lines a Python module's import statements take, numbered from 1."""
    return {
        n
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for n in range(node.lineno, (node.end_lineno or node.lineno) + 1)
    }


def copied(files: dict[str, tuple[str, set[int]]]) -> Iterator[tuple[str, str]]:
    """Yield each copied block as (where it is, where it was first), each `file:line`.

    `files` maps each file, in the order read, to its text and the lines left out of it (its
    imports). A block found is not counted again within its own 8 lines.
    """
    seen: dict[str, tuple[tuple[str, int], str]] = {}
    for f, (text, left_out) in files.items():
        lines = [(n, re.sub(r"\s+", " ", ln.strip())) for n, ln in enumerate(text.splitlines(), 1)]
        lines = [
            (n, s)
            for n, s in lines
            if n not in left_out and len(s) > 3 and not s.startswith(("#", "//", '"""'))
        ]
        last_hit = -WIN
        for i in range(len(lines) - WIN + 1):
            block = "\n".join(s for _, s in lines[i : i + WIN]).encode()
            h = hashlib.sha1(block, usedforsecurity=False).hexdigest()
            if h in seen and seen[h][0] != (f, i) and i >= last_hit + WIN:
                yield f"{f}:{lines[i][0]}", seen[h][1]
                last_hit = i
            seen.setdefault(h, ((f, i), f"{f}:{lines[i][0]}"))
