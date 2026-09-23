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

os.environ.setdefault("PYTEST_CURRENT_TEST", "boot")  # caps-ok: test-boot env switch read by import-time guards to recognise a pytest process; setdefault keeps a value pytest already set, it seeds no market data

import terrain_state
import terrain_radar

from tests.console_runtime import console_runtime_sources

# every function the radar provenance lock names is looked up across the console runtime
_SOURCES = tuple((src, tree) for _path, src, tree in console_runtime_sources())


def _fn(name: str) -> str:
    for src, tree in _SOURCES:
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
                return ast.get_source_segment(src, n) or ""
    raise AssertionError(f"{name} not found")


def test_the_two_producers_are_distinguishable():
    assert terrain_state.LEVELS_SOURCE_WIDE_CHAIN != terrain_state.LEVELS_SOURCE_STORED_CHAIN
    assert terrain_state.LEVELS_SOURCE_UNKNOWN not in (
        terrain_state.LEVELS_SOURCE_WIDE_CHAIN, terrain_state.LEVELS_SOURCE_STORED_CHAIN)


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
    atr = terrain_radar._radar_atr("SPY")
    row = terrain_radar._radar_row(
        {"ticker": "SPY", "regime": "SHORT_GAMMA_TREND", "posture": "X",
         "call_wall": 750.0, "put_wall": 740.0, "gamma_flip": 746.0, "confidence": "TRUSTED"},
        745.0, atr, "AT WALL", "call wall", 750.0, 5.0, 0.5, sort_key=None)
    assert row["levels_source"] == terrain_state.LEVELS_SOURCE_UNKNOWN


def test_a_stamped_snapshot_is_carried_through_verbatim():
    atr = terrain_radar._radar_atr("SPY")
    row = terrain_radar._radar_row(
        {"ticker": "SPY", "call_wall": 750.0, "put_wall": 740.0, "confidence": "TRUSTED",
         "levels_source": terrain_state.LEVELS_SOURCE_STORED_CHAIN},
        745.0, atr, "AT WALL", "call wall", 750.0, 5.0, 0.5, sort_key=None)
    assert row["levels_source"] == terrain_state.LEVELS_SOURCE_STORED_CHAIN
