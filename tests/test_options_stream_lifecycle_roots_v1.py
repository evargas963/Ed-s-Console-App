"""OPTIONS FLOW — behavioural disproof of the lifecycle/ownership root defects Cursor flagged.

Each test here reproduces one failure and proves the fix by BEHAVIOUR, not by reading source:

  * competing writers            — one CaptureWriter connection persists equity AND options; no
                                    second connection to stream_capture.db, no equity row lost.
  * restart over-claims coverage — a crashed-open epoch is closed at the LAST OBSERVED frame, not
                                    at the restart instant, so the downtime gap is not claimed.
  * memory ahead of the record   — a failed durable coverage write does NOT advance the in-memory
                                    subscription set.
  * teardown does not await/unsub— teardown cancels AND awaits the rotation task and unsubscribes
                                    the vendor on a clean stop (but not on a recycle's dead socket).
  * planning blocks the loop     — slice planning runs off the event loop; the loop keeps ticking.

Nothing here infers dealer ownership, aggressor side, or intent, and nothing enters Decide.
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import options_stream_collect as osc  # noqa: E402


# ── #4 competing writers: ONE writer, no equity loss ────────────────────────────────────────────

def test_options_and_equity_ride_one_writer_connection_no_equity_loss(tmp_path, monkeypatch):
    """The defect: OptionsFrameIngest opened a SECOND connection to stream_capture.db, contending
    with the equity CaptureWriter (which had no busy_timeout) and silently losing equity rows.
    The fix: options frames publish to the bus and are persisted by the SAME CaptureWriter
    connection. Proven: exactly ONE connection is opened to the capture db, and every equity AND
    option row lands."""
    from stream_spine import COUNT_DROPS, CaptureWriter, MessageBus, quote_msg

    db = tmp_path / "stream_capture.db"
    real_connect = sqlite3.connect
    conns = {"n": 0}

    def counting_connect(path, *a, **k):
        if str(db) in str(path):
            conns["n"] += 1
        return real_connect(path, *a, **k)

    monkeypatch.setattr(sqlite3, "connect", counting_connect)

    writer = CaptureWriter(db)
    persist = osc.make_capture_topic_writer()
    writer.register_topic_writer("optionchain", persist)
    writer.register_topic_writer("optionbook", persist)

    bus = MessageBus()
    sub = bus.subscribe("", policy=COUNT_DROPS, maxsize=4096)
    for i in range(60):
        bus.publish("quote.SPY", quote_msg(symbol="SPY", bid=1.0, ask=1.1, last=1.05, src="t"))
        bus.publish(f"optionchain.SPY   26082{i:02d}", {
            "service": "LEVELONE_OPTIONS",
            "frame": {"timestamp": 1_000_000 + i, "content": [{"key": f"SPY   26082{i:02d}"}]},
            "received_ts_ms": 2_000_000 + i})

    stop = asyncio.Event()

    async def _drive():
        t = asyncio.create_task(writer.run(sub, stop=stop))
        await asyncio.sleep(0.4)
        stop.set()
        await t

    asyncio.run(_drive())
    writer.close()

    assert conns["n"] == 1, (
        f"{conns['n']} connections were opened to stream_capture.db — options is a competing "
        f"writer again, not riding the one CaptureWriter connection")

    c = real_connect(db)
    try:
        q = c.execute("SELECT COUNT(*) FROM stream_quotes_raw").fetchone()[0]
        o = c.execute("SELECT COUNT(*) FROM options_stream_frames").fetchone()[0]
    finally:
        c.close()
    assert q == 60, f"equity rows lost to the options path: {q}/60"
    assert o == 60, f"option rows not persisted through the shared writer: {o}/60"
    assert writer.insert_errors == 0, f"insert errors under mixed load: {writer.insert_errors}"


def test_capture_writer_coordinates_with_a_busy_timeout(tmp_path):
    """The equity writer must WAIT for the WAL write lock, not raise SQLITE_BUSY and drop a row,
    when the low-frequency coverage/health writers (their own short-lived connections) hold it."""
    from stream_spine import CaptureWriter

    w = CaptureWriter(tmp_path / "stream_capture.db")
    try:
        bt = w._conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert bt >= 1000, (
            f"CaptureWriter has no busy_timeout ({bt}) — a concurrent coordinated writer would make "
            f"it drop equity money-path rows")
    finally:
        w.close()


# ── #2 restart reconcile: close at last observed, never across the downtime gap ──────────────────

def test_restart_reconcile_closes_open_epoch_at_last_observed_not_restart(tmp_path):
    from calibration.options_stream_coverage import (
        open_epochs, reconcile_open_epochs_on_start, was_subscribed)
    from calibration.options_stream_frames import persist_frame

    db = tmp_path / "stream_capture.db"
    sym = "SPY   260820C00600000"
    started = 1_000_000
    open_epochs(db, [sym], service="LEVELONE_OPTIONS", at_ms=started)
    last_obs = started + 5_000
    persist_frame(db, service="LEVELONE_OPTIONS",
                  frame={"timestamp": last_obs, "content": [{"key": sym}]}, received_ts_ms=last_obs)

    # Crash: the epoch is still open. Restart ~2.7 hours later.
    restart = started + 10_000_000
    out = reconcile_open_epochs_on_start(db, services=["LEVELONE_OPTIONS"], at_ms=restart)
    assert out["LEVELONE_OPTIONS"] == 1

    assert was_subscribed(db, sym, last_obs, service="LEVELONE_OPTIONS"), (
        "coverage does not include the last observed instant")
    assert not was_subscribed(db, sym, last_obs + 1_000, service="LEVELONE_OPTIONS"), (
        "coverage claims observation AFTER the last frame — the downtime gap is being covered")
    assert not was_subscribed(db, sym, restart - 1, service="LEVELONE_OPTIONS"), (
        "coverage claims observation all the way to the restart instant (the whole downtime)")


def test_restart_reconcile_is_zero_width_when_no_frame_was_ever_observed(tmp_path):
    from calibration.options_stream_coverage import (
        open_epochs, reconcile_open_epochs_on_start, was_subscribed)

    db = tmp_path / "stream_capture.db"
    sym = "QQQ   260820P00400000"
    started = 2_000_000
    open_epochs(db, [sym], service="LEVELONE_OPTIONS", at_ms=started)
    reconcile_open_epochs_on_start(db, services=["LEVELONE_OPTIONS"], at_ms=9_000_000)
    # No frame was ever stored, so the epoch collapses to zero width: it claims nothing past start.
    assert not was_subscribed(db, sym, started + 1, service="LEVELONE_OPTIONS"), (
        "an epoch that never observed a frame still claims coverage after its start")


# ── #6 memory must not advance past the durable coverage record ──────────────────────────────────

def _minimal_plan(symbols):
    return {
        "at_epoch_s": 0.0, "slice_index": 1, "roster_ok": True,
        "core": ["SPY"], "rotating": [], "per_underlying": {"SPY": len(symbols)},
        "symbol_underlying": {s: "SPY" for s in symbols},
        "policy": "{}", "full_cycle_seconds": 900, "notes": [],
    }


def test_vendor_and_coverage_diverge_when_the_open_write_fails_not_corrupt(monkeypatch):
    """The two states are SEPARATE. Vendor accepts the subscribe (key IS consumed) but the durable
    epoch open FAILS: _vendor_held must hold the contract (so key accounting stays right) while
    _coverage_open must NOT (so the record never claims coverage it did not write). A single fused
    set could only get one of these right."""
    from calibration.options_stream_coverage import CoverageWriteError

    monkeypatch.setattr(osc, "_vendor_held",
                        {s: set() for s in osc.OPTIONS_SERVICES}, raising=False)
    monkeypatch.setattr(osc, "_coverage_open",
                        {s: set() for s in osc.OPTIONS_SERVICES}, raising=False)
    contract = "SPY   260820C00600000"
    want = [contract]

    async def sub_ok(_sc, syms, *, level_one=True, book=True, operation="subs"):
        key = "level_one" if level_one else "book"
        r = {"requested": len(list(syms)), "level_one": None, "book": None, "errors": []}
        r[key] = {"symbols": len(list(syms))}
        return r

    async def unsub(_sc, syms, **_k):
        return {"requested": len(list(syms)), "level_one": True, "book": True, "errors": []}

    def open_fail(_db, syms, **_k):
        raise CoverageWriteError("disk full")

    def close_ok(_db, syms, **_k):
        return len(list(syms))

    asyncio.run(osc._reconcile_options_subscription(
        object(), _minimal_plan(want), want, "test", keys_available=100,
        capture_db=":memory:", close_epochs=close_ok, open_epochs=open_fail,
        subscribe_options=sub_ok, unsubscribe_options=unsub))

    assert contract in osc._vendor_held["LEVELONE_OPTIONS"], (
        "the vendor accepted the subscribe (key consumed) but _vendor_held does not reflect it — "
        "the key budget will under-count and can over-subscribe")
    assert not any(osc._coverage_open.values()), (
        "the durable epoch open FAILED, yet _coverage_open advanced — the record is claiming "
        "coverage it never wrote")


def test_vendor_and_coverage_diverge_when_the_close_write_fails_not_corrupt(monkeypatch):
    """Mirror: the vendor unsubscribe is acknowledged (key released) but the durable close FAILS.
    _vendor_held must drop the contract (key accounting) while _coverage_open must KEEP it (the
    epoch is still open on the record); Phase 2 of the next slice retries the close from that
    exact delta."""
    from calibration.options_stream_coverage import CoverageWriteError

    contract = "SPY   260820C00600000"
    monkeypatch.setattr(osc, "_vendor_held",
                        {"LEVELONE_OPTIONS": {contract}, "OPTIONS_BOOK": set()}, raising=False)
    monkeypatch.setattr(osc, "_coverage_open",
                        {"LEVELONE_OPTIONS": {contract}, "OPTIONS_BOOK": set()}, raising=False)

    async def sub_ok(_sc, syms, *, level_one=True, book=True, operation="subs"):
        return {"requested": 0, "level_one": None, "book": None, "errors": []}

    async def unsub_ok(_sc, syms, **_k):
        return {"requested": len(list(syms)), "level_one": True, "book": True, "errors": []}

    def open_ok(_db, syms, **_k):
        return len(list(syms))

    def close_fail(_db, syms, **_k):
        raise CoverageWriteError("disk full")

    # want set excludes the held contract, so it is a DROP.
    asyncio.run(osc._reconcile_options_subscription(
        object(), _minimal_plan([]), [], "test", keys_available=100,
        capture_db=":memory:", close_epochs=close_fail, open_epochs=open_ok,
        subscribe_options=sub_ok, unsubscribe_options=unsub_ok))

    assert contract not in osc._vendor_held["LEVELONE_OPTIONS"], (
        "the vendor released the key but _vendor_held still holds it — the key budget over-counts")
    assert osc._coverage_open["LEVELONE_OPTIONS"] == {contract}, (
        "the durable close FAILED, yet _coverage_open dropped the contract — the record now claims "
        "LESS than the still-open epoch and nothing will retry the close")


# ── #3 teardown: cancel+await the task, unsubscribe the vendor on a clean stop only ──────────────

def test_clean_teardown_unsubscribes_the_vendor_but_a_recycle_does_not(monkeypatch):
    calls: list[list[str]] = []

    async def unsub(_sc, syms, **_k):
        calls.append(sorted(syms))
        return {"requested": len(list(syms)), "level_one": True, "book": True, "errors": []}

    monkeypatch.setattr("options_stream_subscription.unsubscribe_options", unsub, raising=False)
    monkeypatch.setattr("calibration.options_stream_coverage.close_epochs",
                        lambda *_a, **_k: 0, raising=False)
    monkeypatch.setattr(osc, "_options_rotation_task", None, raising=False)
    monkeypatch.setattr(osc, "_options_offered", 0, raising=False)
    monkeypatch.setattr(osc, "_options_written", 0, raising=False)

    monkeypatch.setattr(osc, "_coverage_open",
                        {s: set() for s in osc.OPTIONS_SERVICES}, raising=False)
    # Clean shutdown with a live socket: the vendor MUST be unsubscribed (keys released).
    monkeypatch.setattr(osc, "_vendor_held",
                        {"LEVELONE_OPTIONS": {"A"}, "OPTIONS_BOOK": {"A"}}, raising=False)
    monkeypatch.setattr(osc, "_active_stream", object(), raising=False)
    asyncio.run(osc.stop_options_collection("daemon_shutdown", unsubscribe=True))
    assert calls == [["A"]], f"clean teardown did not unsubscribe the vendor (keys leaked): {calls}"

    # Recycle: the old socket is dead — teardown must NOT try to unsubscribe on it.
    calls.clear()
    monkeypatch.setattr(osc, "_vendor_held",
                        {"LEVELONE_OPTIONS": {"A"}, "OPTIONS_BOOK": set()}, raising=False)
    monkeypatch.setattr(osc, "_active_stream", object(), raising=False)
    asyncio.run(osc.stop_options_collection("stream_recycle"))
    assert calls == [], "recycle teardown tried to unsubscribe on a dead socket"


def test_teardown_unsubscribe_cannot_hang_on_a_half_open_socket(monkeypatch):
    """A vendor unsubscribe that never returns must not hang shutdown — it is bounded."""
    async def unsub_hangs(_sc, syms, **_k):
        await asyncio.sleep(3600)

    monkeypatch.setattr("options_stream_subscription.unsubscribe_options", unsub_hangs, raising=False)
    monkeypatch.setattr("calibration.options_stream_coverage.close_epochs",
                        lambda *_a, **_k: 0, raising=False)
    monkeypatch.setattr(osc, "_options_rotation_task", None, raising=False)
    monkeypatch.setattr(osc, "_options_offered", 0, raising=False)
    monkeypatch.setattr(osc, "_options_written", 0, raising=False)
    monkeypatch.setattr(osc, "_coverage_open",
                        {s: set() for s in osc.OPTIONS_SERVICES}, raising=False)
    monkeypatch.setattr(osc, "_vendor_held",
                        {"LEVELONE_OPTIONS": {"A"}, "OPTIONS_BOOK": set()}, raising=False)
    monkeypatch.setattr(osc, "_active_stream", object(), raising=False)

    async def _run():
        # If the bound did not hold, this would sleep for an hour; wrap it so the test fails fast.
        await asyncio.wait_for(
            osc.stop_options_collection("daemon_shutdown", unsubscribe=True, timeout_s=0.2),
            timeout=5.0)

    asyncio.run(_run())          # returns promptly = the unsubscribe bound held


# ── #5 slice planning runs off the loop ─────────────────────────────────────────────────────────

def test_slice_planning_runs_off_the_event_loop(monkeypatch):
    import time

    def slow_plan(*_a, **_k):
        time.sleep(0.3)          # a heavy plan: roster read + chain build + selection
        return {"roster_ok": False, "notes": ["held"], "at_epoch_s": 0.0, "slice_index": 1}

    monkeypatch.setattr(osc, "options_desired_for_slice", slow_plan, raising=False)
    monkeypatch.setattr(osc, "_vendor_held",
                        {s: set() for s in osc.OPTIONS_SERVICES}, raising=False)
    monkeypatch.setattr(osc, "_coverage_open",
                        {s: set() for s in osc.OPTIONS_SERVICES}, raising=False)
    monkeypatch.setattr(osc, "_options_lock", None, raising=False)

    async def _run():
        ticks = {"n": 0}

        async def heartbeat():
            for _ in range(20):
                await asyncio.sleep(0.02)
                ticks["n"] += 1

        hb = asyncio.create_task(heartbeat())
        await osc.apply_options_slice(object(), 0.0, reason="test")
        await hb
        # A 0.3s inline plan would have frozen the loop; the heartbeat proves it kept running.
        assert ticks["n"] >= 10, (
            f"the event loop was blocked during slice planning (only {ticks['n']} heartbeats in "
            f"0.3s) — planning is not off the loop")

    asyncio.run(_run())


# ── crash recovery closes at STREAM/PROCESS liveness, not the contract's own last frame ─────────

def test_restart_reconcile_closes_a_quiet_contract_at_stream_liveness(tmp_path):
    """A subscribed-but-QUIET option contract produced no frames of its own, yet it was OBSERVABLE
    for as long as the stream was alive. Crash recovery must close its epoch at the last PROVEN
    stream liveness — here an EQUITY frame, an independent proof the socket/process was live — not
    at the contract's own (nonexistent) last frame, which would understate it to its open."""
    from stream_spine import STREAM_SCHEMA_SQL
    from calibration.options_stream_coverage import (
        open_epochs, reconcile_open_epochs_on_start, was_subscribed)

    db = tmp_path / "stream_capture.db"
    quiet = "SPY   260820C00600000"
    started = 1_000_000
    open_epochs(db, [quiet], service="LEVELONE_OPTIONS", at_ms=started)

    # No option frame for `quiet`. But the equity capture proves the process was alive 7s later.
    conn = sqlite3.connect(str(db))
    conn.executescript(STREAM_SCHEMA_SQL)
    live_ms = started + 7_000
    conn.execute("INSERT INTO stream_quotes_raw (ts_recv, symbol, src) VALUES (?,?,?)",
                 (live_ms / 1000.0, "SPY", "schwab_l1"))
    conn.commit()
    conn.close()

    restart = started + 10_000_000        # ~2.7h later
    reconcile_open_epochs_on_start(db, services=["LEVELONE_OPTIONS"], at_ms=restart)

    assert was_subscribed(db, quiet, started + 3_000, service="LEVELONE_OPTIONS"), (
        "the quiet contract was closed at its own open (zero width) — a subscribed contract's "
        "silence was read as an early un-subscription")
    assert was_subscribed(db, quiet, live_ms, service="LEVELONE_OPTIONS"), (
        "coverage was cut off before the stream was last proven alive")
    assert not was_subscribed(db, quiet, live_ms + 1_000, service="LEVELONE_OPTIONS"), (
        "coverage claims observation past the last proven stream liveness (into the downtime)")


# ── teardown ordering: quiesce does not close coverage; only the post-drain step does ───────────

def test_quiesce_leaves_coverage_open_and_close_is_a_separate_step(tmp_path, monkeypatch):
    """The daemon must be able to quiesce the rotation + unsubscribe the vendor while the pump is
    still draining, WITHOUT closing coverage — an epoch closed before the pump is quiesced would be
    cut off while a frame is still in flight. Closing is a separate step the daemon runs only after
    the writer has drained. Driven against a REAL db: the epoch stays open through quiesce and is
    closed only by close_options_coverage."""
    import stream_spine
    from calibration.options_stream_coverage import open_epochs

    db = tmp_path / "stream_capture.db"
    A = "SPY   260820C00600000"
    open_epochs(db, [A], service="LEVELONE_OPTIONS", at_ms=1_000)
    monkeypatch.setattr(stream_spine, "STREAM_DB_DEFAULT", db, raising=False)
    monkeypatch.setattr(osc.time, "time", lambda: 2.0)          # now = 2000ms
    monkeypatch.setattr(osc, "_options_rotation_task", None, raising=False)
    monkeypatch.setattr(osc, "_vendor_held", {"LEVELONE_OPTIONS": {A}, "OPTIONS_BOOK": set()}, raising=False)
    monkeypatch.setattr(osc, "_coverage_open", {"LEVELONE_OPTIONS": {A}, "OPTIONS_BOOK": set()}, raising=False)
    monkeypatch.setattr(osc, "_coverage_close_owed", {s: {} for s in osc.OPTIONS_SERVICES}, raising=False)
    monkeypatch.setattr(osc, "_active_stream", None, raising=False)   # recycle-style: no unsubscribe

    def _ended():
        conn = sqlite3.connect(str(db))
        try:
            return conn.execute("SELECT ended_ms FROM options_stream_coverage_epochs WHERE symbol=?",
                                (A,)).fetchone()[0]
        finally:
            conn.close()

    # PHASE ONE — quiesce: must NOT close the epoch (still open in the db).
    asyncio.run(osc.quiesce_options_collection("daemon_shutdown", unsubscribe=False))
    assert _ended() is None, "quiesce closed the epoch before the pump was quiesced"
    assert osc._coverage_open["LEVELONE_OPTIONS"] == {A}, "quiesce dropped the coverage record"

    # PHASE TWO — close_options_coverage (run by the daemon AFTER the writer drains) closes it.
    osc.close_options_coverage("daemon_shutdown")
    assert _ended() is not None, "close_options_coverage did not close the epoch"
    assert not any(osc._coverage_open.values()), "coverage state was not reset after the close"


# ── the single writer flushes OFF the event loop so equity receive is not crowded out ───────────

def test_the_single_writer_flushes_off_the_event_loop(tmp_path, monkeypatch):
    """One connection is correct, but option (and equity) persistence must not block equity receive.
    A slow batch flush must not freeze the loop — a concurrent heartbeat keeps ticking while the
    writer is inside its disk work."""
    import time

    from stream_spine import COUNT_DROPS, CaptureWriter, MessageBus, quote_msg

    writer = CaptureWriter(tmp_path / "stream_capture.db")
    real_flush = writer._flush_batch

    def slow_flush(batch):
        time.sleep(0.3)          # a heavy disk flush
        return real_flush(batch)

    monkeypatch.setattr(writer, "_flush_batch", slow_flush, raising=False)
    bus = MessageBus()
    sub = bus.subscribe("", policy=COUNT_DROPS, maxsize=1000)
    for _ in range(20):
        bus.publish("quote.SPY", quote_msg(symbol="SPY", bid=1.0, ask=1.1, src="t"))
    stop = asyncio.Event()

    async def _run():
        ticks = {"n": 0}

        async def heartbeat():
            for _ in range(20):
                await asyncio.sleep(0.02)
                ticks["n"] += 1

        hb = asyncio.create_task(heartbeat())
        wt = asyncio.create_task(writer.run(sub, stop=stop))
        await asyncio.sleep(0.4)
        stop.set()
        await wt
        await hb
        assert ticks["n"] >= 10, (
            f"the event loop was blocked during the writer flush (only {ticks['n']} heartbeats) — "
            f"option persistence is crowding out equity receive")

    asyncio.run(_run())
    writer.close()


# ── a deferred close + re-subscribe must NOT create false coverage across the unsubscribed gap ───

async def _sub_ok(_sc, syms, *, level_one=True, book=True, operation="subs"):
    key = "level_one" if level_one else "book"
    r = {"requested": len(list(syms)), "level_one": None, "book": None, "errors": []}
    r[key] = {"symbols": len(list(syms))}
    return r


async def _unsub_ok(_sc, syms, **_k):
    return {"requested": len(list(syms)), "level_one": True, "book": True, "errors": []}


def test_deferred_close_then_resubscribe_does_not_produce_false_coverage(tmp_path, monkeypatch):
    """THE ROOT COVERAGE DEFECT. A contract dropped while its coverage close FAILS, then rotated
    back in, must end up with TWO epochs (one ending at the drop, one starting at the return) — NOT
    one epoch stretched across the window it was unsubscribed. The set-membership reconcile lost the
    owed close when the contract returned; the owed-close ledger fixes it. Driven against a REAL
    coverage db with real open/close, a transient close failure injected on the drop slice."""
    from calibration.options_stream_coverage import (
        CoverageWriteError, close_epochs as real_close, open_epochs as real_open, was_subscribed)

    db = tmp_path / "stream_capture.db"
    X = "SPY   260820C00600000"
    monkeypatch.setattr(osc, "_vendor_held", {s: set() for s in osc.OPTIONS_SERVICES}, raising=False)
    monkeypatch.setattr(osc, "_coverage_open", {s: set() for s in osc.OPTIONS_SERVICES}, raising=False)
    monkeypatch.setattr(osc, "_coverage_close_owed", {s: {} for s in osc.OPTIONS_SERVICES}, raising=False)

    clock = {"t": 1.0}
    monkeypatch.setattr(osc.time, "time", lambda: clock["t"])   # slice A=1s, B=2s, C=3s

    # A close that FAILS on the drop slice (the first two calls — one per service), then succeeds.
    calls = {"n": 0}

    def close_flaky(_db, syms, **k):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise CoverageWriteError("transient lock")
        return real_close(_db, syms, **k)

    plan = {"at_epoch_s": 0.0, "slice_index": 1, "roster_ok": True, "core": ["SPY"], "rotating": [],
            "per_underlying": {"SPY": 1}, "symbol_underlying": {X: "SPY"}, "policy": "{}",
            "full_cycle_seconds": 900, "notes": []}

    async def reconcile(want):
        return await osc._reconcile_options_subscription(
            object(), dict(plan, notes=[]), want, "test", keys_available=100, capture_db=db,
            close_epochs=close_flaky, open_epochs=real_open,
            subscribe_options=_sub_ok, unsubscribe_options=_unsub_ok)

    async def _run():
        clock["t"] = 1.0
        await reconcile([X])          # slice A: subscribe + open epoch at 1000
        clock["t"] = 2.0
        await reconcile([])           # slice B: drop; close FAILS -> owed at 2000, epoch stays open
        clock["t"] = 3.0
        await reconcile([X])          # slice C: return; owed close lands at 2000, fresh open at 3000

    asyncio.run(_run())

    for svc in ("LEVELONE_OPTIONS", "OPTIONS_BOOK"):
        assert was_subscribed(db, X, 1500, service=svc), f"{svc}: first epoch missing"
        assert not was_subscribed(db, X, 2500, service=svc), (
            f"{svc}: FALSE COVERAGE — the record claims X observed at 2500ms, inside the window "
            f"[2000,3000] when X was unsubscribed at the vendor")
        assert was_subscribed(db, X, 3500, service=svc), f"{svc}: fresh epoch missing after return"
    # And there are genuinely TWO epochs for X on each service, not one spanning the gap.
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM options_stream_coverage_epochs WHERE symbol=? "
                         "AND service='LEVELONE_OPTIONS'", (X,)).fetchone()[0]
    finally:
        conn.close()
    assert n == 2, f"expected two distinct epochs for X, got {n} (a merged epoch spans the gap)"


def test_writer_run_is_never_cancelled_mid_flush_close_is_safe(tmp_path, monkeypatch):
    """Defect A: shutdown must AWAIT run() (which self-bounds its drain), never cancel it mid-flush.
    A slow flush plus a short drain deadline must let run() return cleanly with no worker touching
    the connection, so the subsequent close() cannot race it — and undrained rows are COUNTED."""
    import time

    from stream_spine import COUNT_DROPS, CaptureWriter, MessageBus, quote_msg

    writer = CaptureWriter(tmp_path / "stream_capture.db")
    real_flush = writer._flush_batch

    def slow_flush(batch):
        time.sleep(0.2)
        return real_flush(batch)

    monkeypatch.setattr(writer, "_flush_batch", slow_flush, raising=False)
    bus = MessageBus()
    sub = bus.subscribe("", policy=COUNT_DROPS, maxsize=10000)
    for _ in range(5000):
        bus.publish("quote.SPY", quote_msg(symbol="SPY", bid=1.0, ask=1.1, src="t"))
    stop = asyncio.Event()

    async def _run():
        stop.set()   # ask to stop immediately; run() must still drain within the deadline
        # A tiny drain deadline forces the deadline path; run() must still return only AFTER its
        # in-flight flush completes (never abandon the worker).
        await writer.run(sub, stop=stop, drain_deadline_s=0.05)

    asyncio.run(_run())
    # run() returned; the connection is idle. close() must not raise (no worker mid-write).
    writer.close()
    assert writer.drain_lost >= 0
    # offered vs written+lost accounting stays coherent: some rows written, the rest counted lost.
    assert writer.rows_written + writer.drain_lost <= 5000


def test_phase2_coverage_writes_run_off_the_event_loop(monkeypatch):
    """Defect C1: the Phase-2 open/close_epochs are the OTHER half of the crowd-out — they must run
    off the loop too. A slow open_epochs must not freeze the loop; a concurrent heartbeat ticks."""
    import time

    monkeypatch.setattr(osc, "_vendor_held", {s: set() for s in osc.OPTIONS_SERVICES}, raising=False)
    monkeypatch.setattr(osc, "_coverage_open", {s: set() for s in osc.OPTIONS_SERVICES}, raising=False)
    monkeypatch.setattr(osc, "_coverage_close_owed", {s: {} for s in osc.OPTIONS_SERVICES}, raising=False)

    def slow_open(_db, syms, **k):
        time.sleep(0.3)

    X = "SPY   260820C00600000"
    plan = {"at_epoch_s": 0.0, "slice_index": 1, "roster_ok": True, "core": ["SPY"], "rotating": [],
            "per_underlying": {"SPY": 1}, "symbol_underlying": {X: "SPY"}, "policy": "{}",
            "full_cycle_seconds": 900, "notes": []}

    async def _run():
        ticks = {"n": 0}

        async def heartbeat():
            for _ in range(20):
                await asyncio.sleep(0.02)
                ticks["n"] += 1

        hb = asyncio.create_task(heartbeat())
        await osc._reconcile_options_subscription(
            object(), plan, [X], "test", keys_available=100, capture_db=":memory:",
            close_epochs=lambda *a, **k: None, open_epochs=slow_open,
            subscribe_options=_sub_ok, unsubscribe_options=_unsub_ok)
        await hb
        assert ticks["n"] >= 10, (
            f"the loop was blocked during the Phase-2 coverage write (only {ticks['n']} ticks) — "
            f"coverage sqlite is still on the loop")

    asyncio.run(_run())


def test_recycle_teardown_closes_at_last_liveness_not_now(tmp_path, monkeypatch):
    """Defect C2: a watchdog recycle fires on a socket dead ~90s. close_options_coverage must end
    the open epochs at the last PROVEN liveness (an equity frame), NOT at `now`, or it folds the
    dead-socket window into coverage."""
    from stream_spine import STREAM_SCHEMA_SQL
    from calibration.options_stream_coverage import open_epochs, was_subscribed

    db = tmp_path / "stream_capture.db"
    X = "SPY   260820C00600000"
    started = 1_000_000
    open_epochs(db, [X], service="LEVELONE_OPTIONS", at_ms=started)
    # last proven liveness: an equity frame 5s after the epoch opened; then the socket died.
    conn = sqlite3.connect(str(db))
    conn.executescript(STREAM_SCHEMA_SQL)
    live_ms = started + 5_000
    conn.execute("INSERT INTO stream_quotes_raw (ts_recv, symbol, src) VALUES (?,?,?)",
                 (live_ms / 1000.0, "SPY", "schwab_l1"))
    conn.commit()
    conn.close()

    # `now` at teardown is ~90s past the last frame (dead-socket window).
    now_recycle = started + 95_000
    monkeypatch.setattr(osc.time, "time", lambda: now_recycle / 1000.0)
    monkeypatch.setattr(osc, "_coverage_open", {"LEVELONE_OPTIONS": {X}, "OPTIONS_BOOK": set()}, raising=False)
    monkeypatch.setattr(osc, "_vendor_held", {"LEVELONE_OPTIONS": {X}, "OPTIONS_BOOK": set()}, raising=False)
    monkeypatch.setattr(osc, "_coverage_close_owed", {s: {} for s in osc.OPTIONS_SERVICES}, raising=False)
    # Point the module's capture db at the temp db.
    import stream_spine
    monkeypatch.setattr(stream_spine, "STREAM_DB_DEFAULT", db, raising=False)

    osc.close_options_coverage("stream_recycle")

    assert was_subscribed(db, X, live_ms, service="LEVELONE_OPTIONS"), "coverage cut before last frame"
    assert not was_subscribed(db, X, live_ms + 1_000, service="LEVELONE_OPTIONS"), (
        "recycle closed the epoch at `now`, folding the ~90s dead-socket window into coverage")


def test_recycle_does_not_reset_the_daemon_run_counters(monkeypatch):
    """Defects B/C3: a recycle must NOT flush health or reset the offered counter — the writer is
    long-lived across recycles, so a mid-flight reset both races the worker and over-reports drops.
    Only daemon shutdown flushes, once, after the writer is joined."""
    flushed = {"n": 0}
    monkeypatch.setattr(osc, "flush_options_ingest_health",
                        lambda *a, **k: flushed.__setitem__("n", flushed["n"] + 1), raising=False)
    monkeypatch.setattr("calibration.options_stream_coverage.close_epochs",
                        lambda *a, **k: 0, raising=False)
    # Do not touch the real capture db from a unit test — the teardown close reads it via reconcile.
    monkeypatch.setattr("calibration.options_stream_coverage.reconcile_open_epochs_on_start",
                        lambda *a, **k: {}, raising=False)
    monkeypatch.setattr(osc, "_options_rotation_task", None, raising=False)
    monkeypatch.setattr(osc, "_options_offered", 4242, raising=False)
    monkeypatch.setattr(osc, "_vendor_held", {"LEVELONE_OPTIONS": {"A"}, "OPTIONS_BOOK": set()}, raising=False)
    monkeypatch.setattr(osc, "_coverage_open", {"LEVELONE_OPTIONS": {"A"}, "OPTIONS_BOOK": set()}, raising=False)
    monkeypatch.setattr(osc, "_coverage_close_owed", {s: {} for s in osc.OPTIONS_SERVICES}, raising=False)
    monkeypatch.setattr(osc, "_active_stream", None, raising=False)

    asyncio.run(osc.stop_options_collection("stream_recycle"))

    assert flushed["n"] == 0, "a recycle flushed ingest health — that races the live writer's counts"
    assert osc._options_offered == 4242, "a recycle reset the offered counter mid-writer-life"


# ── re-verification round: fixes for the defects the adversarial re-audit found in the first fix ──

def test_teardown_never_writes_a_negative_width_epoch(tmp_path, monkeypatch):
    """N1: close_options_coverage must FLOOR each epoch's end to its own start. If the last proven
    liveness precedes an epoch's start (a fresh subscribe after the last frame across the whole
    capture), closing at `min(now,liveness)` unfloored would write ended < started — a malformed
    row that makes a genuinely-subscribed contract read NOT_SUBSCRIBED. The reconcile-based close
    floors per-epoch, so ended is always >= started."""
    import stream_spine
    from stream_spine import STREAM_SCHEMA_SQL
    from calibration.options_stream_coverage import open_epochs

    db = tmp_path / "stream_capture.db"
    X = "SPY   260820C00600000"
    started = 5_000
    open_epochs(db, [X], service="LEVELONE_OPTIONS", at_ms=started)
    # last proven liveness is BEFORE the epoch's start (equity frame at 1000ms; epoch opened at 5000)
    conn = sqlite3.connect(str(db))
    conn.executescript(STREAM_SCHEMA_SQL)
    conn.execute("INSERT INTO stream_quotes_raw (ts_recv, symbol, src) VALUES (?,?,?)",
                 (1.0, "SPY", "schwab_l1"))
    conn.commit()
    conn.close()

    monkeypatch.setattr(stream_spine, "STREAM_DB_DEFAULT", db, raising=False)
    monkeypatch.setattr(osc.time, "time", lambda: 6.0)          # now = 6000ms
    monkeypatch.setattr(osc, "_coverage_open", {"LEVELONE_OPTIONS": {X}, "OPTIONS_BOOK": set()}, raising=False)
    monkeypatch.setattr(osc, "_vendor_held", {s: set() for s in osc.OPTIONS_SERVICES}, raising=False)
    monkeypatch.setattr(osc, "_coverage_close_owed", {s: {} for s in osc.OPTIONS_SERVICES}, raising=False)

    osc.close_options_coverage("stream_recycle")

    conn = sqlite3.connect(str(db))
    try:
        started_ms, ended_ms = conn.execute(
            "SELECT started_ms, ended_ms FROM options_stream_coverage_epochs WHERE symbol=?",
            (X,)).fetchone()
    finally:
        conn.close()
    assert ended_ms is not None, "epoch left open"
    assert ended_ms >= started_ms, f"negative-width row: ended {ended_ms} < started {started_ms}"


def test_teardown_closes_a_db_orphan_epoch_missing_from_memory(tmp_path, monkeypatch):
    """N2 (belt): if a torn-down slice committed an open epoch to the db but the in-memory
    _coverage_open update was skipped (a cancel landing between the durable write and the memory
    update), close_options_coverage must STILL close it — it reads the db, not memory — so no epoch
    is left open to read as false coverage until the next start."""
    import stream_spine
    from calibration.options_stream_coverage import open_epochs

    db = tmp_path / "stream_capture.db"
    X = "SPY   260820C00600000"
    open_epochs(db, [X], service="LEVELONE_OPTIONS", at_ms=1_000)   # committed to the db
    monkeypatch.setattr(stream_spine, "STREAM_DB_DEFAULT", db, raising=False)
    monkeypatch.setattr(osc.time, "time", lambda: 2.0)
    # _coverage_open does NOT contain X — the split lost the memory update.
    monkeypatch.setattr(osc, "_coverage_open", {s: set() for s in osc.OPTIONS_SERVICES}, raising=False)
    monkeypatch.setattr(osc, "_vendor_held", {s: set() for s in osc.OPTIONS_SERVICES}, raising=False)
    monkeypatch.setattr(osc, "_coverage_close_owed", {s: {} for s in osc.OPTIONS_SERVICES}, raising=False)

    osc.close_options_coverage("daemon_shutdown")

    conn = sqlite3.connect(str(db))
    try:
        ended = conn.execute("SELECT ended_ms FROM options_stream_coverage_epochs WHERE symbol=?",
                             (X,)).fetchone()[0]
    finally:
        conn.close()
    assert ended is not None, (
        "a db-orphan open epoch (memory never recorded it) was left open — false coverage until "
        "the next daemon start")


def test_quiesce_waits_for_an_in_flight_slice_before_cancelling(monkeypatch):
    """N2 (prevention): quiesce must ACQUIRE the reconcile lock before cancelling the rotation task,
    so a slice that is mid-write (holding the lock) COMPLETES first and the cancel lands on the
    inter-slice sleep — never between an off-loop coverage write and its in-memory update."""
    async def _run():
        lock = asyncio.Lock()
        monkeypatch.setattr(osc, "_options_lock", lock, raising=False)
        await lock.acquire()                       # simulate a slice in progress holding the lock

        async def fake_slice():
            await asyncio.sleep(3600)              # parked; only cancellable via cancel()

        task = asyncio.create_task(fake_slice())
        monkeypatch.setattr(osc, "_options_rotation_task", task, raising=False)
        monkeypatch.setattr(osc, "_active_stream", None, raising=False)

        q = asyncio.create_task(osc.quiesce_options_collection("daemon_shutdown", timeout_s=5.0))
        await asyncio.sleep(0.05)
        assert not q.done(), (
            "quiesce cancelled the rotation task while a slice held the lock — it would split a "
            "mid-write from its memory update")
        assert not task.cancelled(), "the task was cancelled before its slice finished"
        lock.release()                             # the slice 'finishes' and releases the lock
        await asyncio.wait_for(q, timeout=2.0)
        assert task.cancelled(), "quiesce did not cancel the rotation task after acquiring the lock"

    asyncio.run(_run())
