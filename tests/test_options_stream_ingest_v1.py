"""OPTIONS FLOW — persistence must never be able to stall the SOLE Schwab stream.

WHY THESE ARE THE TESTS. order_flow_streaming owns one StreamClient and one asyncio message
loop, and its handlers run INLINE on that loop, so time spent in a handler is time the socket is
not being read. Options frames arrive far faster than equity frames, and the raw writer touches a
38.9 GB SQLite database. Everything below is therefore about one question: can storage make the
shared LEVELONE_EQUITIES / NASDAQ_BOOK / NYSE_BOOK stream wait?

TWO OF THESE PIN DEFECTS THE MEASUREMENT ACTUALLY FOUND, not hypotheticals:
  * test_producer_is_never_stalled_by_a_slow_writer — the first implementation held the stats
    lock across an entire 500-frame batch while offer() needed that same lock on the loop
    thread. Measured worst-case offer(): 28,152 us. A 28 ms stall of the equity stream.
  * test_accounting_survives_a_writer_that_cannot_open_storage — offered=2000, written=0,
    dropped=1000 left 1000 frames unaccounted, which is the silent hole the module exists to
    prevent. Absence must be attributable.

Nothing here interprets market data or infers dealer ownership, aggressor side, or intent.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from calibration.options_stream_ingest import OptionsFrameIngest  # noqa: E402
from calibration.options_stream_frames import (  # noqa: E402
    frame_row_values,
    frame_symbol_rows,
    persist_frame,
)

CAPTURE = (REPO / "reports" / "of_capability_probe" / "options_20260820T1354Z" / "frames")


def _real_frame(service: str = "LEVELONE_OPTIONS", idx: int = 1) -> dict:
    """A REAL decoded vendor frame from the committed capture — never a hand-made dict."""
    p = CAPTURE / f"{service}_{idx:03d}_decoded.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _stamp(frame: dict) -> dict:
    g = json.loads(json.dumps(frame))
    g["timestamp"] = int(time.time() * 1000.0) - 40
    return g


def test_producer_is_never_stalled_by_a_slow_writer(tmp_path):
    """THE REGRESSION. offer() runs on the stream loop; its tail latency IS stream stall.

    The writer here is deliberately slow (25 ms per batch). If offer() were coupled to the
    writer — by a shared lock held across a batch, or by blocking when the queue fills — that
    slowness would show up in the producer. It must not.
    """
    def _slow(_conn, batch):
        time.sleep(0.025)
        return len(batch)

    db = str(tmp_path / "slow.db")
    ing = OptionsFrameIngest(db, max_queue=5000, batch_max=200, persist_batch=_slow)
    ing.start()
    fr = _real_frame()
    worst_us = 0.0
    try:
        for _ in range(3000):
            g = _stamp(fr)
            t0 = time.perf_counter_ns()
            ing.offer("LEVELONE_OPTIONS", g)
            worst_us = max(worst_us, (time.perf_counter_ns() - t0) / 1000.0)
    finally:
        ing.stop(timeout=60.0)

    # The writer sleeps 25 ms per batch. A producer coupled to it would show tens of ms.
    # 5 ms leaves generous room for interpreter/GC jitter on a loaded host while still
    # failing loudly on real coupling (the measured regression was 28 ms).
    assert worst_us < 5000.0, (
        f"offer() worst case {worst_us:.0f}us — the producer is coupled to the writer, so a "
        f"storage stall becomes an equity-stream stall")


def test_accounting_survives_a_writer_that_cannot_open_storage(tmp_path):
    """Every offered frame must end up written OR counted as dropped. Never neither.

    A frame that vanishes from the counters is worse than one that is dropped: history shows a
    gap that the health record claims does not exist, so it reads as 'the vendor sent nothing'.
    """
    # A path that is genuinely unopenable: it IS a directory, so sqlite3.connect fails.
    # A merely missing parent no longer works — the constructor creates it, matching
    # CaptureWriter — so using one here would silently test nothing.
    bad_dir = tmp_path / "this_is_a_directory.db"
    bad_dir.mkdir()
    ing = OptionsFrameIngest(str(bad_dir), max_queue=200, batch_max=100)
    ing.start()
    fr = _real_frame()
    for _ in range(1000):
        ing.offer("LEVELONE_OPTIONS", _stamp(fr))
    out = ing.stop(timeout=30.0)

    assert out["offered"] == 1000
    assert out["written"] == 0, "storage was unopenable; nothing can have been written"
    assert out["accounting_complete"], (
        f"frames vanished from the accounting: offered={out['offered']} "
        f"written={out['written']} dropped={out['dropped']}")
    assert out["offered"] == out["written"] + out["dropped"]
    assert out["write_errors"] >= 1, "an unopenable database must be reported, not hidden"


def test_bounded_queue_drops_rather_than_blocking_and_counts_every_drop(tmp_path):
    """The bound must be real and the loss must be visible."""
    def _slow(_conn, batch):
        time.sleep(0.05)
        return len(batch)

    db = str(tmp_path / "bounded.db")
    ing = OptionsFrameIngest(db, max_queue=100, batch_max=50, persist_batch=_slow)
    ing.start()
    fr = _real_frame()
    for _ in range(2000):
        ing.offer("LEVELONE_OPTIONS", _stamp(fr))
    out = ing.stop(timeout=60.0)

    assert out["dropped"] > 0, "a 100-deep queue behind a 50ms writer must overflow"
    assert out["max_queue_depth"] <= 100, "the queue exceeded its own bound"
    assert out["accounting_complete"], "dropped frames were not fully counted"


def test_batched_and_single_frame_writers_produce_identical_rows(tmp_path):
    """Two write paths into one table must agree by construction, not by coincidence.

    persist_frame (one frame, own connection) and the batched ingest writer both shape rows via
    frame_row_values/frame_symbol_rows. If either grew its own INSERT tuple they would drift on
    the first edit and the table would hold two row shapes.
    """
    fr = _stamp(_real_frame())
    rx = int(time.time() * 1000.0)

    single_db = tmp_path / "single.db"
    res = persist_frame(single_db, service="LEVELONE_OPTIONS", frame=fr, received_ts_ms=rx)
    assert res["status"] == "written", res

    batch_db = str(tmp_path / "batch.db")
    ing = OptionsFrameIngest(batch_db, max_queue=10, batch_max=10)
    ing.start()
    ing.offer("LEVELONE_OPTIONS", fr, received_ts_ms=rx)
    out = ing.stop(timeout=30.0)
    assert out["written"] == 1, out

    cols = "service, frame_ts_ms, received_ts_ms, ingest_lag_ms, n_contracts, payload_json"
    a = sqlite3.connect(str(single_db)).execute(
        f"SELECT {cols} FROM options_stream_frames").fetchone()
    b = sqlite3.connect(batch_db).execute(
        f"SELECT {cols} FROM options_stream_frames").fetchone()
    assert a == b, "the two write paths produced DIFFERENT rows for the same frame"


def test_multi_contract_frame_is_discoverable_for_every_contract(tmp_path):
    """A frame's content is a LIST. Indexing by content[0] hides every later contract."""
    fr = _stamp(_real_frame())
    entry = (fr.get("content") or [{}])[0]
    second = json.loads(json.dumps(entry))
    second["key"] = "QQQ   260820C00500000"
    fr["content"] = [entry, second]

    db = str(tmp_path / "multi.db")
    ing = OptionsFrameIngest(db, max_queue=10, batch_max=10)
    ing.start()
    ing.offer("LEVELONE_OPTIONS", fr)
    out = ing.stop(timeout=30.0)
    assert out["written"] == 1

    rows = sqlite3.connect(db).execute(
        "SELECT symbol_key, content_idx FROM options_stream_frame_symbols ORDER BY content_idx"
    ).fetchall()
    assert len(rows) == 2, f"multi-contract frame indexed only {len(rows)} contract(s): {rows}"
    assert rows[1][0] == "QQQ   260820C00500000"
    assert [r[1] for r in rows] == [0, 1], "content positions must be addressable"


def test_ingest_lag_is_milliseconds_on_both_sides(tmp_path):
    """Vendor stamp and receive clock are both epoch ms, so the stored lag is a real quantity.

    Mixing seconds and milliseconds here previously produced ~1.79e12 as a 'lag'.
    """
    fr = _real_frame()
    now_ms = int(time.time() * 1000.0)
    fr = json.loads(json.dumps(fr))
    fr["timestamp"] = now_ms - 250

    db = str(tmp_path / "lag.db")
    ing = OptionsFrameIngest(db, max_queue=10, batch_max=10)
    ing.start()
    ing.offer("LEVELONE_OPTIONS", fr, received_ts_ms=now_ms)
    ing.stop(timeout=30.0)

    lag = sqlite3.connect(db).execute(
        "SELECT ingest_lag_ms FROM options_stream_frames").fetchone()[0]
    assert lag == 250, f"expected a 250 ms lag, stored {lag}"


def test_health_row_is_written_so_gaps_stay_provable_after_exit(tmp_path):
    """Counters that die with the process cannot explain a hole in history a week later."""
    db = str(tmp_path / "health.db")
    ing = OptionsFrameIngest(db, max_queue=50, batch_max=25)
    ing.start()
    fr = _real_frame()
    for _ in range(30):
        ing.offer("LEVELONE_OPTIONS", _stamp(fr))
    ing.stop(timeout=30.0)

    row = sqlite3.connect(db).execute(
        "SELECT offered, written, dropped, write_errors FROM options_stream_ingest_health"
    ).fetchone()
    assert row is not None, "no durable health record was written"
    assert row[0] == 30
    assert row[0] == row[1] + row[2], "the durable record must also balance"


def test_raw_options_capture_can_never_target_the_operational_db():
    """RC-6 LAW (BLOCKING): raw streams never touch ed_console.db.

    governance/CONSOLE_REBUILD_PLAN_CR_V1.md S4 states raw stream capture goes to a dedicated
    stream_capture.db and "the operational DB grows by zero bytes". Options frames are raw
    stream data and are no exception: at the canary size alone they would add ~10.4 GB per RTH
    day to a file already at 38.9 GB. The first version of this ingest wrote to db.DB_PATH,
    which is precisely the violation.

    The traversal case is not hypothetical — CaptureWriter shipped with a basename-only guard
    that `data/x/../ed_console.db` walked straight through, and it was recorded as an RC-6 law
    hole. Both guards here resolve() first.
    """
    import pytest

    from calibration.options_stream_coverage import coverage_db_path

    op = REPO / "data" / "ed_console.db"
    for target in (op, REPO / "data" / "x" / ".." / "ed_console.db"):
        with pytest.raises(ValueError, match="RC-6"):
            OptionsFrameIngest(str(target))
        with pytest.raises(ValueError, match="RC-6"):
            coverage_db_path(str(target))


def test_contract_ceiling_is_derived_from_the_key_budget_not_chosen():
    """Schwab bills KEYS (symbol x service), so the ceiling must follow the budget.

    The old fixed 240 sat just under the limit with books on (240x2 + 3 = 483) by luck, and
    would have been wrong the moment books were disabled — leaving ~477 keys unused — or the
    equity path held more symbols.
    """
    from options_stream_subscription import (
        KEY_SAFETY_MARGIN, SCHWAB_STREAM_KEY_LIMIT, contract_budget_from_key_limit,
    )

    on = contract_budget_from_key_limit(equity_symbols=1, book_enabled=True)
    off = contract_budget_from_key_limit(equity_symbols=1, book_enabled=False)

    assert on["equity_keys_held"] == 3, "L1 + NASDAQ_BOOK + NYSE_BOOK are three separate keys"
    assert on["contracts_allowed"] * 2 + on["equity_keys_held"] <= \
        SCHWAB_STREAM_KEY_LIMIT - KEY_SAFETY_MARGIN, "budget overruns the documented key limit"
    assert off["contracts_allowed"] > on["contracts_allowed"], (
        "dropping OPTIONS_BOOK must free keys for more contracts — that trade-off is the "
        "whole reason the budget is computed rather than fixed")
    # More equity symbols must shrink the options budget, never silently overrun.
    more = contract_budget_from_key_limit(equity_symbols=5, book_enabled=True)
    assert more["contracts_allowed"] < on["contracts_allowed"]


def test_frame_without_vendor_timestamp_is_rejected_not_invented(tmp_path):
    """A missing clock must not be replaced with our own — that would fabricate provenance."""
    fr = _real_frame()
    fr = json.loads(json.dumps(fr))
    fr.pop("timestamp", None)
    assert frame_row_values("LEVELONE_OPTIONS", fr, int(time.time() * 1000)) is None
    assert frame_symbol_rows(1, {"content": [{"no_key": 1}]}) == []
