"""RC-82: every radar row declares WHICH producer computed its walls.

The radar merges the terrain loop's wide-chain levels with stored-chain fallback rows and sorts
them against each other by wall distance. Wall selection depends on how much of the wing the chain
covers — RC-80 measured an 11-point difference on SPY between the two widths — so a fallback row's
walls sit systematically inward of a loop row's.

MEASURED 2026-07-27 on the live console: /api/terrain/radar returned 12 rows carrying call_wall,
put_wall and gamma_flip with no provenance field whatsoever. The merge is deliberate and cannot be
removed (per-symbol vendor calls measured a 40.5s cold sweep that always timed out), so the duty
is to make the difference visible rather than to pretend it is absent.
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


def test_the_two_producers_are_distinguishable():
    assert server.LEVELS_SOURCE_WIDE_CHAIN != server.LEVELS_SOURCE_STORED_CHAIN
    assert server.LEVELS_SOURCE_UNKNOWN not in (
        server.LEVELS_SOURCE_WIDE_CHAIN, server.LEVELS_SOURCE_STORED_CHAIN)


def test_each_producer_stamps_itself():
    assert "LEVELS_SOURCE_WIDE_CHAIN" in _fn("_terrain_refresh_one"), (
        "the wide-chain loop no longer stamps its output, so its rows become indistinguishable "
        "from the narrower fallback's"
    )
    assert "LEVELS_SOURCE_STORED_CHAIN" in _fn("_radar_fallback_recompute"), (
        "the stored-chain fallback no longer labels itself as provisional"
    )


def test_the_row_carries_the_stamp_and_unstamped_reads_as_unknown():
    seg = _fn("_radar_row")
    assert '"levels_source"' in seg, "radar rows no longer publish which producer made them"
    assert "LEVELS_SOURCE_UNKNOWN" in seg, (
        "an unstamped snapshot must read as unknown — defaulting it to the trusted wide chain is "
        "how a provisional row would pass as a measured one"
    )


def test_a_row_built_from_an_unstamped_snapshot_is_not_called_trusted():
    """Drive the REAL row builder, not a reading of it."""
    atr = server._radar_atr("SPY")
    row = server._radar_row(
        {"ticker": "SPY", "regime": "SHORT_GAMMA_TREND", "posture": "X",
         "call_wall": 750.0, "put_wall": 740.0, "gamma_flip": 746.0, "confidence": "TRUSTED"},
        745.0, atr, "AT WALL", "call wall", 750.0, 5.0, 0.5, sort_key=None)
    assert row["levels_source"] == server.LEVELS_SOURCE_UNKNOWN


def test_a_stamped_snapshot_is_carried_through_verbatim():
    atr = server._radar_atr("SPY")
    row = server._radar_row(
        {"ticker": "SPY", "call_wall": 750.0, "put_wall": 740.0, "confidence": "TRUSTED",
         "levels_source": server.LEVELS_SOURCE_STORED_CHAIN},
        745.0, atr, "AT WALL", "call wall", 750.0, 5.0, 0.5, sort_key=None)
    assert row["levels_source"] == server.LEVELS_SOURCE_STORED_CHAIN
