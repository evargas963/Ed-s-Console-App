"""Level crosses: which are recorded at a levels publication (server.level_crosses), how they
are stored, and how the one reader serves them."""

from __future__ import annotations

import json
from pathlib import Path

import server
from db import EdDB

_FX = Path(__file__).parent / "fixtures"


def test_a_cross_is_a_strict_change_of_side_in_either_direction() -> None:
    levels = [("VWAP", 501.0), ("Call g-Wall", 510.0)]
    up, ref = server.level_crosses({"VWAP": 500.0, "Call g-Wall": 500.0}, 502.0, levels)
    assert up == [("VWAP", 501.0, "up")] and ref == {"VWAP": 502.0, "Call g-Wall": 502.0}
    down, ref = server.level_crosses(ref, 500.5, levels)
    assert down == [("VWAP", 501.0, "down")]
    # several levels passed in one move are each recorded
    many, _ = server.level_crosses({"PDH": 499.0, "VWAP": 499.0, "Call g-Wall": 499.0, "Call OI": 499.0},
                                   512.0, [("PDH", 500.0), ("VWAP", 505.0), ("Call g-Wall", 510.0),
                                           ("Call OI", 520.0)])
    assert [c[0] for c in many] == ["PDH", "VWAP", "Call g-Wall"]


def test_no_reference_no_cross_and_an_unmoved_spot_crosses_nothing() -> None:
    first, ref = server.level_crosses({}, 502.0, [("VWAP", 501.0)])
    assert first == [] and ref == {"VWAP": 502.0}, "the first live publication only sets the reference"
    again, _ = server.level_crosses(ref, 502.0, [("VWAP", 501.0)])
    assert again == []
    # a level that moved across an unmoved spot is not the spot crossing it
    moved, _ = server.level_crosses(ref, 502.0, [("VWAP", 503.0)])
    assert moved == []


def test_reaching_a_level_and_turning_back_records_nothing() -> None:
    """2026-09-30 audit: arriving exactly at a level from below recorded an 'up' cross, and the
    move back down recorded nothing, so the last recorded direction said spot was above a level
    it was below. Spot at a level is on neither side."""
    levels = [("Call g-Wall", 100.0)]
    touch, ref = server.level_crosses({"Call g-Wall": 99.5}, 100.0, levels)
    assert touch == [] and ref == {"Call g-Wall": 99.5}
    back, ref = server.level_crosses(ref, 99.5, levels)
    assert back == []
    # stopping on the level and then going through it is one cross
    _, ref = server.level_crosses(ref, 100.0, levels)
    through, _ = server.level_crosses(ref, 100.4, levels)
    assert through == [("Call g-Wall", 100.0, "up")]


def test_every_cross_is_recorded_however_soon_after_the_last(tmp_path: Path, monkeypatch) -> None:
    """2026-09-30 audit: a second cross in the same direction within 60 s was dropped, so up,
    down, up inside a minute left 'down' as the last recorded direction with spot above."""
    edb = EdDB(tmp_path / "level_crosses.db")
    monkeypatch.setattr(server, "get_db", lambda: edb)
    levels, ref, t0 = [("VWAP", 501.0)], {"VWAP": 500.0}, 1_800_000_000.0
    for i, spot in enumerate((502.0, 500.0, 502.0)):
        crosses, ref = server.level_crosses(ref, spot, levels)
        server._record_level_crosses("SPY", crosses, spot, t0 + 10.0 * i)
    rows = sorted(edb.get_crosses_since("SPY", 0.0), key=lambda r: r["ts_utc"])
    assert [r["direction"] for r in rows] == ["up", "down", "up"]
    # each row carries the time and price of the trade that made the cross
    assert [(r["ts_utc"], r["spot_at_cross"]) for r in rows] == [(t0, 502.0), (t0 + 10.0, 500.0), (t0 + 20.0, 502.0)]
    assert rows[0]["ts_et"] == "2027-01-15 03:00:00 ET" and rows[0]["level_value"] == 501.0


def test_a_cross_with_no_trade_time_is_not_stamped_with_another(tmp_path: Path, monkeypatch) -> None:
    edb = EdDB(tmp_path / "level_crosses.db")
    monkeypatch.setattr(server, "get_db", lambda: edb)
    server._record_level_crosses("SPY", [("VWAP", 501.0, "up")], 502.0, None)
    assert edb.get_crosses_since("SPY", 0.0) == []


def test_a_stored_captures_price_is_no_reference_for_a_live_cross(tmp_path, monkeypatch, pin_clock) -> None:
    """The first live price after the levels were priced from a stored capture (startup, a closed
    market) was compared with the capture's price, days old, and every level between the two
    was recorded as crossed just now. Only a live price is a reference; the next live move is
    recorded, at the time of the trade that made it. Real PCG chain (2026-09-25,
    tests/fixtures/real_pcg_two_day_chain.json), stored as the daemon writes it. Stand-ins
    (named): the two live prices, one above and one below every published level."""
    from calibration.complete_chain_capture import (CAPTURE_BASIS, last_capture_per_day,
                                                    persist_complete_chain_capture)
    day = json.loads((_FX / "real_pcg_two_day_chain.json").read_text(encoding="utf-8"))["days"][-1]
    db = tmp_path / "ed.db"
    by_exp: dict = {}
    for c in day["contracts"]:
        by_exp.setdefault(str(c.get("expirationDate") or "")[:10], []).append(c)
    for exp, cs in by_exp.items():
        persist_complete_chain_capture(db, ticker="PCG", expiry=exp, contracts=cs, spot=day["spot"],
                                       completeness_basis=CAPTURE_BASIS, ts_utc=day["ts_utc"])
    edb = EdDB(db)
    monkeypatch.setattr(server, "get_db", lambda: edb)
    monkeypatch.setattr(server, "_terrain_cache", {})
    pin_clock(2026, 9, 27, 12, 0)                                        # Sunday: the capture is priced
    snap = server._publish_levels("PCG", captures=last_capture_per_day(str(db), "PCG", 2),
                                  now=time_et_ts(2026, 9, 27, 12, 0))
    levels = [getattr(snap, k) for k, _ in server.CROSS_LEVELS if getattr(snap, k) is not None]
    above, below = max(levels) + 1.0, min(levels) - 1.0
    assert below < day["spot"] < above and len(levels) >= 3

    pin_clock(2026, 9, 28, 10, 0)                                        # Monday, live
    t1 = time_et_ts(2026, 9, 28, 10, 0)
    monkeypatch.setattr(server, "resolve_spot", lambda tk: (above, "streaming_plane", t1 - 2.0))
    server._publish_levels("PCG", day["contracts"], t1, now=t1)
    assert edb.get_crosses_since("PCG", 0.0) == []
    monkeypatch.setattr(server, "resolve_spot", lambda tk: (below, "streaming_plane", t1 + 3.0))
    live = server._publish_levels("PCG", day["contracts"], t1 + 5.0, now=t1 + 5.0)
    rows = edb.get_crosses_since("PCG", 0.0)
    crossed = {getattr(live, k) for k, _ in server.CROSS_LEVELS if getattr(live, k) is not None}
    assert rows and {r["level_value"] for r in rows} == crossed
    assert {(r["direction"], r["ts_utc"], r["spot_at_cross"]) for r in rows} == {("down", t1 + 3.0, below)}


def time_et_ts(y: int, mo: int, d: int, h: int, mi: int) -> float:
    from datetime import datetime

    import time_et
    return datetime(y, mo, d, h, mi, tzinfo=time_et.ET).timestamp()


def test_levels_crossed_together_are_one_event_naming_every_level():
    """RC-88: one price crossing a strike where several levels sit is stored as one row per level.
    The one reader (server._merged_crosses_since) serves one event per (time, value, direction)
    that names every level. Real SPY rows, tests/fixtures/real_spy_level_crosses.json: 400 rows,
    243 events, up to 6 levels on one event."""
    rows = json.loads((_FX / "real_spy_level_crosses.json").read_text(encoding="utf-8"))["rows"]

    class _Stored:                                   # stand-in: the stored rows, as the DB returns them
        def get_crosses_since(self, ticker, since):
            return [r for r in rows if r["ts_utc"] >= since]

    assert len(rows) == 400
    events = server._merged_crosses_since(_Stored(), "SPY", 0.0)
    assert len(events) == 243
    assert max(len(e["level_names"]) for e in events) == 6
