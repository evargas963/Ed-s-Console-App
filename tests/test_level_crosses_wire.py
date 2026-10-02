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
    # a cross recorded live and the same cross loaded at startup are the same row, cross_id included
    assert edb.get_recent_crosses("SPY", n=10) == crosses


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


def test_levels_crossed_together_are_one_event_naming_every_level(monkeypatch) -> None:
    """RC-88: one price crossing a strike where several levels sit is stored as one row per level.
    The one reader (server._merged_recent_crosses) serves one event per (time, value, direction)
    that names every level. Real SPY rows, tests/fixtures/real_spy_level_crosses.json: 400 rows,
    243 events, up to 6 levels on one event, loaded as the console's start loads them."""
    import json

    import server

    rows = json.loads((Path(__file__).parent / "fixtures" / "real_spy_level_crosses.json")
                      .read_text(encoding="utf-8"))["rows"]

    class _Stored:                                   # stand-in: the stored rows, as the DB returns them
        def get_recent_crosses(self, ticker, n):
            return rows[:n]

    assert len(rows) == 400
    monkeypatch.setattr(server, "get_db", lambda: _Stored())
    monkeypatch.setattr(server, "_crosses", {})
    server._load_crosses(["SPY"])
    events = server._merged_recent_crosses("SPY", 400)
    assert len(events) == 243
    assert max(len(e["level_names"]) for e in events) == 6
