"""Pass 4 — level_crosses wire from server tick path.

Tests EdDB.detect_and_log_level_crosses (the producer side) and the
existing get_recent_crosses reader. New file per AGENTS § No-new-files-default
(existing tests/test_db*.py own SQLite retry / feature adapter / safety;
none owns level_crosses behavior).
"""

from __future__ import annotations

from pathlib import Path


from db import EdDB


def _seed_empty_db(tmp_path: Path) -> EdDB:
    db_path = tmp_path / "level_crosses.db"
    return EdDB(db_path)


def test_detect_logs_upward_cross(tmp_path: Path) -> None:
    edb = _seed_empty_db(tmp_path)
    crosses = edb.detect_and_log_level_crosses(
        ticker="SPY",
        prev_spot=500.0,
        cur_spot=502.0,
        levels=[(501.0, "VWAP"), (510.0, "Call g-Wall")],  # only VWAP crossed
        ts_utc=1_800_000_000.0,
        ts_et="2026-05-25 10:00:00 ET",
    )
    assert len(crosses) == 1
    assert crosses[0]["direction"] == "up"
    assert crosses[0]["level_name"] == "VWAP"
    assert crosses[0]["spot_at_cross"] == 502.0
    rows = edb.get_recent_crosses("SPY", n=10)
    assert len(rows) == 1


def test_detect_logs_downward_cross(tmp_path: Path) -> None:
    edb = _seed_empty_db(tmp_path)
    crosses = edb.detect_and_log_level_crosses(
        ticker="SPY",
        prev_spot=502.0,
        cur_spot=500.0,
        levels=[(501.0, "VWAP")],
        ts_utc=1_800_000_000.0,
        ts_et="2026-05-25 10:00:00 ET",
    )
    assert len(crosses) == 1
    assert crosses[0]["direction"] == "down"


def test_no_cross_when_spot_unchanged(tmp_path: Path) -> None:
    edb = _seed_empty_db(tmp_path)
    crosses = edb.detect_and_log_level_crosses(
        ticker="SPY",
        prev_spot=500.0,
        cur_spot=500.0,
        levels=[(501.0, "VWAP")],
        ts_utc=1_800_000_000.0,
        ts_et="ET",
    )
    assert crosses == []
    assert edb.get_recent_crosses("SPY", n=10) == []


def test_no_cross_when_level_not_traversed(tmp_path: Path) -> None:
    edb = _seed_empty_db(tmp_path)
    crosses = edb.detect_and_log_level_crosses(
        ticker="SPY",
        prev_spot=500.0,
        cur_spot=502.0,
        levels=[(510.0, "Call g-Wall")],
        ts_utc=1_800_000_000.0,
        ts_et="ET",
    )
    assert crosses == []


def test_none_levels_are_skipped(tmp_path: Path) -> None:
    edb = _seed_empty_db(tmp_path)
    crosses = edb.detect_and_log_level_crosses(
        ticker="SPY",
        prev_spot=500.0,
        cur_spot=502.0,
        levels=[(None, "Missing"), (501.0, "VWAP")],
        ts_utc=1_800_000_000.0,
        ts_et="ET",
    )
    assert len(crosses) == 1
    assert crosses[0]["level_name"] == "VWAP"


def test_debounce_blocks_second_same_direction_cross(tmp_path: Path) -> None:
    edb = _seed_empty_db(tmp_path)
    base_ts = 1_800_000_000.0
    edb.detect_and_log_level_crosses(
        ticker="SPY",
        prev_spot=500.0, cur_spot=502.0,
        levels=[(501.0, "VWAP")],
        ts_utc=base_ts, ts_et="ET",
    )
    # Same direction within debounce window — should NOT log again.
    crosses = edb.detect_and_log_level_crosses(
        ticker="SPY",
        prev_spot=501.5, cur_spot=502.5,
        levels=[(501.7, "VWAP")],
        ts_utc=base_ts + 10.0,
        ts_et="ET",
        debounce_s=60.0,
    )
    assert crosses == []
    rows = edb.get_recent_crosses("SPY", n=10)
    assert len(rows) == 1


def test_debounce_does_not_block_opposite_direction(tmp_path: Path) -> None:
    """Up then down within debounce window: down must still log
    (otherwise a legitimate reversal is silently dropped)."""
    edb = _seed_empty_db(tmp_path)
    base_ts = 1_800_000_000.0
    edb.detect_and_log_level_crosses(
        ticker="SPY",
        prev_spot=500.0, cur_spot=502.0,
        levels=[(501.0, "VWAP")],
        ts_utc=base_ts, ts_et="ET",
    )
    crosses = edb.detect_and_log_level_crosses(
        ticker="SPY",
        prev_spot=502.0, cur_spot=500.5,
        levels=[(501.0, "VWAP")],
        ts_utc=base_ts + 10.0,
        ts_et="ET",
    )
    assert len(crosses) == 1
    assert crosses[0]["direction"] == "down"
    rows = edb.get_recent_crosses("SPY", n=10)
    assert len(rows) == 2


def test_debounce_clears_after_window(tmp_path: Path) -> None:
    edb = _seed_empty_db(tmp_path)
    base_ts = 1_800_000_000.0
    edb.detect_and_log_level_crosses(
        ticker="SPY", prev_spot=500.0, cur_spot=502.0,
        levels=[(501.0, "VWAP")],
        ts_utc=base_ts, ts_et="ET",
    )
    crosses = edb.detect_and_log_level_crosses(
        ticker="SPY", prev_spot=501.0, cur_spot=503.0,
        levels=[(502.0, "VWAP")],
        ts_utc=base_ts + 120.0,  # well past 60s debounce
        ts_et="ET",
        debounce_s=60.0,
    )
    assert len(crosses) == 1


def test_multiple_levels_in_one_tick(tmp_path: Path) -> None:
    edb = _seed_empty_db(tmp_path)
    crosses = edb.detect_and_log_level_crosses(
        ticker="SPY",
        prev_spot=499.0,
        cur_spot=512.0,
        levels=[
            (500.0, "PDH"),
            (505.0, "VWAP"),
            (510.0, "Call g-Wall"),
            (520.0, "Call OI Wall"),  # not crossed
        ],
        ts_utc=1_800_000_000.0,
        ts_et="ET",
    )
    assert len(crosses) == 3
    names = sorted(c["level_name"] for c in crosses)
    assert names == ["Call g-Wall", "PDH", "VWAP"]


def test_coincident_crossings_collapse_to_one_event(tmp_path):
    """Eight names on one strike is ONE crossing, and the endpoint must say so."""
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    # the one merge and its consumer (/api/desk/events)
    seg = "".join(ast.get_source_segment(src, node) or "" for node in ast.walk(ast.parse(src))
                  if isinstance(node, ast.FunctionDef) and node.name in ("get_desk_events", "_merged_recent_crosses"))
    assert "_merged_recent_crosses(get_db()" in seg, "get_desk_events not found or not using the one merge"
    assert "coincident_levels" in seg, (
        "RC-88 regression: the endpoint no longer reports how many levels shared the crossing, so "
        "a collapsed event is indistinguishable from a lone one"
    )
    assert "level_names" in seg, (
        "collapsing without naming WHICH levels coincided destroys the information the extra rows "
        "carried — the fix must not be a plain de-duplication"
    )


def test_collapse_keys_on_price_event_not_level_name():
    """The merge key must be the market event (ts, value, direction). Keying on level_name would
    reproduce exactly the producer-side bug this fixes."""
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    seg = next(ast.get_source_segment(src, n) for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.FunctionDef) and n.name == "_merged_recent_crosses")
    assert 'r.get("ts_utc"), r.get("level_value"), r.get("direction")' in seg, (
        "the collapse key is no longer the price event; a level_name-keyed merge cannot see two "
        "names sharing one strike, which is the whole defect"
    )
