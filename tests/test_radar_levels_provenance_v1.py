"""RC-82: every radar row declares WHICH producer computed its walls.

The radar merges the terrain loop's wide-chain levels with stored-chain fallback rows and sorts
them against each other by wall distance. Wall selection depends on how much of the wing the chain
covers — RC-80 measured an 11-point difference on SPY between the two widths — so a fallback row's
walls sit systematically inward of a loop row's.

MEASURED 2026-07-27 on the live console: /api/terrain/radar returned 12 rows carrying call_wall,
put_wall and gamma_flip with no provenance field whatsoever. The merge is deliberate and cannot be
removed (per-symbol vendor calls measured a 40.5s cold sweep that always timed out), so the duty
is to make the difference visible rather than to pretend it is absent.

2026-09-26: the stored-chain fallback producer (_radar_fallback_recompute), the radar row builder
(_radar_row) and the /api/terrain/radar route were deleted as uncalled, taking the two-producer
merge with them. What remains is the one wide-chain producer's stamp on the terrain cache; if a
second level producer ever returns, the RC-82 distinguishability tests must return with it.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

os.environ.setdefault("PYTEST_CURRENT_TEST", "boot")

import server  # noqa: E402

SRC = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)


def _fn(name: str) -> str:
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.get_source_segment(SRC, n) or ""
    raise AssertionError(f"{name} not found")


def test_the_one_level_producer_stamps_itself():
    assert "LEVELS_SOURCE_WIDE_CHAIN" in _fn("_publish_levels"), (
        "the wide-chain loop no longer stamps its output with the producer that made it"
    )
    # The narrower stored-chain producer and its label are gone; a re-added one must come
    # back with a distinguishable stamp (and the RC-82 tests), not silently.
    assert not hasattr(server, "LEVELS_SOURCE_STORED_CHAIN")
    assert not hasattr(server, "_radar_fallback_recompute")
