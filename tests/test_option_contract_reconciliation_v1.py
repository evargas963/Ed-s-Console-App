"""OPTIONS_ORDER_FLOW_V1 — per-service option-contract reconciliation negative controls.

Two real defects, found by operator-directed adversarial review of the daemon code this
mission's own earlier commits landed:

  #2 COVERAGE-EPOCH DURABILITY: _apply_active_option_contract_subs used to return the
     newly-requested contract as "current" even when the durable coverage-epoch OPEN
     write failed — IN-MEMORY CURRENT CONTRACT = X while DURABLE COVERAGE EPOCH FOR X =
     ABSENT, a direct violation of CoverageWriteError's own documented contract ("memory
     must never claim coverage the epoch table never recorded"). The symmetric CLOSE path
     had the mirror bug: a failed close unconditionally discarded the epoch id, silently
     abandoning it open-ended forever.

  #3 PARTIAL LEVELONE_OPTIONS/OPTIONS_BOOK SUBSCRIPTION FAILURE: the two Schwab services
     were reconciled as one all-or-nothing unit — one succeeding while the other raised
     collapsed the WHOLE tick to "failed, return the stale old state", discarding a real
     vendor-side success and risking a duplicate subscribe (or a stuck state) on retry.

Root fix (tools/run_stream_capture.py): _reconcile_option_service handles ONE Schwab
service at a time, called independently for "l1" and "book"; _open_coverage_epoch_tracked/
_close_coverage_epoch_tracked/_retry_pending_epoch_closes track failures for retry instead
of discarding them. This file proves both fixes hold under real failure injection — the
in-memory state (contract_state, epoch_state) and the actual stream_coverage_epochs table
are cross-checked directly, not just the function's return value.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time

import pytest

from stream_spine import (
    CaptureWriter,
    CoverageWriteError,
    read_active_option_contract_signal,
    write_active_option_contract_signal,
)
import tools.run_stream_capture as rsc
from tools.run_stream_capture import (
    _active_option_contract_poll_loop,
    _apply_active_option_contract_subs,
    _close_coverage_epoch_tracked,
    _reconcile_option_service,
    _retry_pending_epoch_closes,
)

_SPY_CONTRACT = "SPY   260820C00767000"
_QQQ_CONTRACT = "QQQ   260820C00450000"


def _failing_close(*_a, **_k):
    """A durable coverage CLOSE that persistently fails for the tick."""
    raise CoverageWriteError("simulated durable-write outage on close")


class _FlakyOptionStream:
    """Records (un)subscribe calls; can be configured to raise on specific calls, so a
    partial-failure tick (one service ok, one erroring) can be reproduced deterministically
    — never a synthetic shortcut around the real async call shape _reconcile_option_service
    actually drives."""
    def __init__(self, *, fail_calls: set[str] | None = None):
        self.calls: list[tuple] = []
        self.fail_calls = fail_calls or set()

    async def _maybe_fail(self, name, syms):
        self.calls.append((name, tuple(syms)))
        if name in self.fail_calls:
            raise RuntimeError(f"simulated vendor failure: {name}")

    async def level_one_option_subs(self, syms):
        await self._maybe_fail("l1_option_sub", syms)

    async def options_book_subs(self, syms):
        await self._maybe_fail("options_book_sub", syms)

    async def level_one_option_unsubs(self, syms):
        await self._maybe_fail("l1_option_unsub", syms)

    async def options_book_unsubs(self, syms):
        await self._maybe_fail("options_book_unsub", syms)


def _epochs(db_path):
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT symbol, service, ended_ts FROM stream_coverage_epochs ORDER BY id").fetchall()
    con.close()
    return rows


def _pending_ids(epoch_state, key):
    """Epoch ids queued for close-retry, independent of how the queue is represented.

    It is a {epoch_id: surrendered_ts} map: a deferred close must replay the instant
    coverage was GIVEN UP, not the instant the database finally accepted the write.
    Tests assert on the ids here; the timestamps are asserted where they carry meaning
    (test_deferred_close_records_the_surrender_time_not_the_retry_time)."""
    return set(epoch_state.get(f"{key}_pending_close") or {})


# ─────────────────────────────────────────────────────────────────────────────
# #2 — COVERAGE-EPOCH DURABILITY negative controls (operator's A-E)
# ─────────────────────────────────────────────────────────────────────────────

def test_A_subscribe_and_coverage_open_both_succeed_advances_cleanly(tmp_path, monkeypatch):
    """A. option subscriptions succeed + coverage OPEN write succeeds -> state advances."""
    monkeypatch.setattr("tools.run_stream_capture.read_active_option_contract_signal",
                        lambda: _SPY_CONTRACT)
    stream = _FlakyOptionStream()
    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=1, batch_sec=10.0)
    epoch_state: dict = {"l1": None, "book": None}

    async def go():
        state = {"l1": None, "book": None}
        new_state = await _apply_active_option_contract_subs(
            stream, state, writer=writer, epoch_state=epoch_state)
        assert new_state == {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}
        assert epoch_state["l1"] is not None and epoch_state["book"] is not None
    asyncio.run(go())
    writer.close()


def test_B_coverage_open_write_fails_compensates_by_unsubscribing(tmp_path, monkeypatch):
    """B (PR214 premerge gap 4, attack A). option subscriptions succeed + coverage OPEN
    write fails.

    This test previously asserted that vendor-held truth ADVANCED while durable coverage
    stayed absent — which the arbiter correctly identified as the defect, not the fix: a
    LIVE VENDOR SUBSCRIPTION with NO DURABLE COVERAGE EPOCH makes any later gap in the
    data unattributable between "not subscribed" and "subscribed, vendor silent", which
    is the entire causal purpose of the ledger. Steady-state capture must never continue
    in that shape.

    The invariant this test has always been about ("never falsely claims durable
    coverage") is preserved and STRENGTHENED: durable truth is still never fabricated,
    AND the vendor subscription is now given back, so VENDOR_HELD ⇒ DURABLE_OPEN_EPOCH
    holds at the tick boundary. The next tick retries cleanly."""
    monkeypatch.setattr("tools.run_stream_capture.read_active_option_contract_signal",
                        lambda: _SPY_CONTRACT)
    stream = _FlakyOptionStream()
    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=1, batch_sec=10.0)

    def _boom(*a, **k):
        raise CoverageWriteError("simulated durable-write outage")
    monkeypatch.setattr(writer, "open_coverage_epoch", _boom)
    epoch_state: dict = {"l1": None, "book": None}

    async def go():
        state = {"l1": None, "book": None}
        new_state = await _apply_active_option_contract_subs(
            stream, state, writer=writer, epoch_state=epoch_state)
        # COMPENSATED: the subscribe really happened, the epoch could not be recorded,
        # so the subscription was handed back -- nothing is vendor-held.
        assert new_state == {"l1": None, "book": None}, (
            "a vendor subscription whose coverage start cannot be durably recorded must "
            "be compensated away, not carried into steady state")
        # Durable truth: still never fabricated.
        assert epoch_state["l1"] is None and epoch_state["book"] is None
    asyncio.run(go())
    assert _epochs(tmp_path / "cap.db") == [], (
        "no epoch row may exist when every open_coverage_epoch call was made to fail")
    # The compensating unsubscribes were really issued, for both services.
    unsubs = [c for c in stream.calls if c[0].endswith("_unsub")]
    assert ("l1_option_unsub", (_SPY_CONTRACT,)) in unsubs
    assert ("options_book_unsub", (_SPY_CONTRACT,)) in unsubs
    writer.close()


def test_B2_compensating_unsubscribe_failure_fails_closed_not_continue(tmp_path, monkeypatch):
    """PR214 premerge gap 4, attack B. vendor sub succeeds -> epoch open fails ->
    the COMPENSATING UNSUB ALSO fails. True vendor state is now uncertain and durable
    coverage cannot be guaranteed, so the system must NOT continue as healthy/held: it
    raises OptionCoverageCompensationError, which the poll loop escalates into the
    existing stream-recycle path rather than absorbing as an ordinary bad tick."""
    from tools.run_stream_capture import OptionCoverageCompensationError

    monkeypatch.setattr("tools.run_stream_capture.read_active_option_contract_signal",
                        lambda: _SPY_CONTRACT)
    # the compensating unsubscribe fails too
    stream = _FlakyOptionStream(fail_calls={"l1_option_unsub"})
    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=1, batch_sec=10.0)

    def _boom(*a, **k):
        raise CoverageWriteError("simulated durable-write outage")
    monkeypatch.setattr(writer, "open_coverage_epoch", _boom)
    epoch_state: dict = {"l1": None, "book": None}

    async def go():
        return await _apply_active_option_contract_subs(
            stream, {"l1": None, "book": None}, writer=writer, epoch_state=epoch_state)

    with pytest.raises(OptionCoverageCompensationError) as exc:
        asyncio.run(go())
    msg = str(exc.value)
    assert "compensating unsubscribe also failed" in msg
    assert "forcing stream recycle" in msg
    assert _epochs(tmp_path / "cap.db") == [], "no durable coverage was ever recorded"
    writer.close()


def test_B3_poll_loop_escalates_compensation_failure_into_recycle(tmp_path, monkeypatch):
    """PR214 premerge gap 4: the poll loop's generic handler deliberately survives one
    bad tick -- correct for a transient error, WRONG for an uncertain-vendor-state
    compensation failure. Prove that ONE error sets the recycle request instead of being
    swallowed, while an ordinary error still does not."""
    import asyncio as _aio

    from tools.run_stream_capture import (
        OptionCoverageCompensationError,
        _active_option_contract_poll_loop,
    )

    async def drive(exc):
        stop = _aio.Event()
        recycle = _aio.Event()

        async def _boom(*a, **k):
            stop.set()          # one tick only
            raise exc
        monkeypatch.setattr("tools.run_stream_capture._apply_active_option_contract_subs", _boom)
        await _active_option_contract_poll_loop(
            lambda: object(), lambda: {"l1": None, "book": None}, lambda c: None,
            stop, writer=None, epoch_state=None, interval_sec=0.01,
            request_recycle=recycle)
        return recycle.is_set()

    assert asyncio.run(drive(OptionCoverageCompensationError("uncertain vendor state"))) is True, (
        "a compensation failure must force the recycle path")
    assert asyncio.run(drive(RuntimeError("ordinary transient vendor error"))) is False, (
        "an ordinary bad tick must still be survivable without recycling the stream")


def test_C_coverage_close_write_fails_keeps_the_old_epoch_open_and_held(tmp_path, monkeypatch):
    """C. old subscription changes + coverage CLOSE write fails -> the old durable epoch
    must NOT be silently forgotten, and (PR214 bidirectional coverage truth) the vendor
    must not race ahead of it.

    This test previously asserted that vendor truth ADVANCED to QQQ while SPY's epoch
    stayed open and merely queued for retry. Measured, that produced TWO open epochs on
    one service -- and since these epochs are now also read as producer subscription
    identity, that state makes "what is this service subscribed to" unanswerable. The
    original claim (a failed close leaves the OLD epoch genuinely OPEN, never fabricated
    as closed) is preserved and now paired with the restored vendor state that makes it
    coherent."""
    p = tmp_path / "signal.json"
    write_active_option_contract_signal(_QQQ_CONTRACT, path=p)
    monkeypatch.setattr("tools.run_stream_capture.read_active_option_contract_signal",
                        lambda: read_active_option_contract_signal(path=p))
    stream = _FlakyOptionStream()
    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=1, batch_sec=10.0)
    writer._conn.execute(
        "INSERT INTO stream_coverage_epochs(id,symbol,service,started_ts,reason) "
        "VALUES(1,?,?,0,?),(2,?,?,0,?)",
        (_SPY_CONTRACT, "LEVELONE_OPTIONS", "seed", _SPY_CONTRACT, "OPTIONS_BOOK", "seed"))
    writer._conn.commit()
    real_close = writer.close_coverage_epoch

    def _flaky_close(epoch_id, **k):
        if epoch_id in (1, 2):
            raise CoverageWriteError("simulated durable-write outage on close")
        return real_close(epoch_id, **k)
    monkeypatch.setattr(writer, "close_coverage_epoch", _flaky_close)
    epoch_state: dict = {"l1": 1, "book": 2}

    async def go():
        state = {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}
        new_state = await _apply_active_option_contract_subs(
            stream, state, writer=writer, epoch_state=epoch_state)
        # Vendor truth is RESTORED to SPY, not advanced to QQQ: the ledger still says
        # SPY is the open window, so the vendor must still be holding SPY.
        assert new_state == {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}
        # The restored epochs are current again, and no longer queued for closing.
        assert epoch_state["l1"] == 1 and epoch_state["book"] == 2
        assert _pending_ids(epoch_state, "l1") == set()
        assert _pending_ids(epoch_state, "book") == set()
    asyncio.run(go())
    rows = _epochs(tmp_path / "cap.db")
    old_rows = [r for r in rows if r[0] == _SPY_CONTRACT]
    assert all(r[2] is None for r in old_rows), (
        "a failed close must leave the OLD epoch genuinely OPEN in the durable table — "
        "claiming it closed when it did not would misreport an ended coverage window as "
        "still open, or vice versa fabricate an end that never landed")
    assert [r for r in rows if r[0] == _QQQ_CONTRACT] == [], (
        "no epoch may be opened for the new contract while the old one is still open")
    writer.close()


def test_D_pending_close_self_heals_once_the_writer_recovers(tmp_path, monkeypatch):
    """D. DB error/retry/recovery -> coverage state converges without fabricating
    intervals. A close that failed once must succeed on the NEXT reconciliation tick once
    the durable write stops failing — no operator action required.

    Retargeted (PR214 bidirectional coverage truth) to the STREAM-RECYCLE teardown, which
    is where pending-close still legitimately arises: the main loop closes both option
    epochs directly when the socket is recycled, with no vendor subscription left to
    compensate against. On the A->B SWITCH path a failed close is now compensated
    (the prior subscription is restored and the epoch is no longer pending), so that path
    no longer leaves a pending entry to retry — see
    test_coverage_C_pending_close_retry_cannot_close_a_restored_subscription."""
    from tools.run_stream_capture import _close_coverage_epoch_tracked

    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=1, batch_sec=10.0)
    writer._conn.execute(
        "INSERT INTO stream_coverage_epochs(id,symbol,service,started_ts,reason) "
        "VALUES(1,?,?,0,?),(2,?,?,0,?)",
        (_SPY_CONTRACT, "LEVELONE_OPTIONS", "seed", _SPY_CONTRACT, "OPTIONS_BOOK", "seed"))
    writer._conn.commit()
    real_close = writer.close_coverage_epoch
    fail_toggle = {"on": True}

    def _flaky_close(epoch_id, **k):
        if fail_toggle["on"] and epoch_id in (1, 2):
            raise CoverageWriteError("simulated durable-write outage on close")
        return real_close(epoch_id, **k)
    monkeypatch.setattr(writer, "close_coverage_epoch", _flaky_close)
    epoch_state: dict = {"l1": 1, "book": 2}

    # Recycle teardown while the durable write is out: both closes FAIL, both tracked.
    _close_coverage_epoch_tracked(writer, epoch_state, "l1", reason="stream_recycle")
    _close_coverage_epoch_tracked(writer, epoch_state, "book", reason="stream_recycle")
    assert _pending_ids(epoch_state, "l1") == {1}
    assert _pending_ids(epoch_state, "book") == {2}
    assert all(r[2] is None for r in _epochs(tmp_path / "cap.db")), (
        "a failed close must leave the epoch genuinely OPEN, never fabricate an end")

    fail_toggle["on"] = False   # the durable-write outage recovers
    _retry_pending_epoch_closes(writer, epoch_state, "l1", reason="retry_pending_close")
    _retry_pending_epoch_closes(writer, epoch_state, "book", reason="retry_pending_close")

    assert _pending_ids(epoch_state, "l1") == set()
    assert _pending_ids(epoch_state, "book") == set()
    old_rows =[r for r in _epochs(tmp_path / "cap.db") if r[0] == _SPY_CONTRACT]
    assert len(old_rows) == 2 and all(r[2] is not None for r in old_rows), (
        "once the writer recovers, the previously-stuck epochs must actually close")
    writer.close()


def test_E_mutation_ignoring_open_failure_would_fabricate_durable_coverage(tmp_path, monkeypatch):
    """E. mutation removing the fail-closed/reconciliation behavior -> test FAILS. Proves
    this suite actually DISCRIMINATES: a mutated _open_coverage_epoch_tracked that (like
    the pre-fix code) claims success regardless of the underlying write outcome produces
    an epoch_state the real epochs table CONTRADICTS — caught by cross-checking the
    in-memory claim against the durable row, not merely asserting the function returned
    something."""
    monkeypatch.setattr("tools.run_stream_capture.read_active_option_contract_signal",
                        lambda: _SPY_CONTRACT)
    stream = _FlakyOptionStream()
    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=1, batch_sec=10.0)

    def _boom(*a, **k):
        raise CoverageWriteError("simulated durable-write outage")
    monkeypatch.setattr(writer, "open_coverage_epoch", _boom)

    # THE MUTATION: a naive tracker that (like the old bug) fabricates a success marker
    # even when the underlying write raised.
    def _mutated_open_ignoring_failure(writer, epoch_state, key, symbol, service, *, reason):
        try:
            epoch_state[key] = writer.open_coverage_epoch(symbol, service, reason=reason)
        except CoverageWriteError:
            epoch_state[key] = -1   # BUG: claims a fabricated "durable" epoch id anyway
    monkeypatch.setattr("tools.run_stream_capture._open_coverage_epoch_tracked",
                        _mutated_open_ignoring_failure)
    epoch_state: dict = {"l1": None, "book": None}

    async def go():
        state = {"l1": None, "book": None}
        return await _apply_active_option_contract_subs(
            stream, state, writer=writer, epoch_state=epoch_state)
    asyncio.run(go())
    # The mutation fabricates a non-None epoch id in memory...
    assert epoch_state["l1"] == -1 and epoch_state["book"] == -1
    # ...but the REAL table has no such row — the cross-check a correct test must make.
    assert _epochs(tmp_path / "cap.db") == [], (
        "the durable table has no row for id=-1 (it was never actually written) — a test "
        "that only checked epoch_state and not the real table would have PASSED the "
        "mutation, exactly the gap this cross-check closes")
    writer.close()


def test_a_stuck_close_must_block_a_new_epoch_on_the_same_service(tmp_path, monkeypatch):
    """REVERSED (PR214 bidirectional coverage truth).

    This test previously asserted the OPPOSITE: "a NEW epoch for QQQ must open even
    though the OLD SPY epoch is stuck pending-close." That encoded the contradiction as
    a requirement -- it is exactly how two open epochs on one service came to be written,
    and it was measured doing so. Because these epochs are now also read as PRODUCER
    SUBSCRIPTION IDENTITY, a stuck close must instead BLOCK the new open and the vendor
    must be restored to the contract the ledger still says is open. The keys remain
    independent; what changed is that an unclosed epoch is no longer something a new open
    may step over."""
    p = tmp_path / "signal.json"
    write_active_option_contract_signal(_QQQ_CONTRACT, path=p)
    monkeypatch.setattr("tools.run_stream_capture.read_active_option_contract_signal",
                        lambda: read_active_option_contract_signal(path=p))
    stream = _FlakyOptionStream()
    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=1, batch_sec=10.0)
    writer._conn.execute(
        "INSERT INTO stream_coverage_epochs(id,symbol,service,started_ts,reason) "
        "VALUES(1,?,?,0,?)", (_SPY_CONTRACT, "LEVELONE_OPTIONS", "seed"))
    writer._conn.commit()
    real_close = writer.close_coverage_epoch

    def _flaky_close(epoch_id, **k):
        if epoch_id == 1:
            raise CoverageWriteError("stuck close")
        return real_close(epoch_id, **k)
    monkeypatch.setattr(writer, "close_coverage_epoch", _flaky_close)
    epoch_state: dict = {"l1": 1, "book": None}

    async def go():
        state = {"l1": _SPY_CONTRACT, "book": None}
        return await _apply_active_option_contract_subs(
            stream, state, writer=writer, epoch_state=epoch_state)
    final = asyncio.run(go())
    # L1: the stuck close blocks the switch entirely — SPY is restored and stays current.
    assert final["l1"] == _SPY_CONTRACT, (
        "with SPY's epoch un-closable, the vendor must remain on SPY, not advance to QQQ")
    assert epoch_state["l1"] == 1, "SPY's epoch id is the current L1 epoch again"
    assert _pending_ids(epoch_state, "l1") == set(), (
        "the still-live epoch must not stay queued for closing (it is legitimately open: "
        "the close failed before the vendor was touched, so the subscription never ended)")
    l1_open = [r for r in _epochs(tmp_path / "cap.db")
               if r[1] == "LEVELONE_OPTIONS" and r[2] is None]
    assert len(l1_open) == 1 and l1_open[0][0] == _SPY_CONTRACT, (
        f"exactly one open L1 epoch, still SPY; got {l1_open}")
    # BOOK had nothing held and no stuck close, so it transitions to QQQ normally — the
    # two services stay independent, which is the property this file exists to protect.
    assert final["book"] == _QQQ_CONTRACT
    book_open = [r for r in _epochs(tmp_path / "cap.db")
                 if r[1] == "OPTIONS_BOOK" and r[2] is None]
    assert len(book_open) == 1 and book_open[0][0] == _QQQ_CONTRACT
    writer.close()


# ─────────────────────────────────────────────────────────────────────────────
# #3 — PARTIAL LEVELONE_OPTIONS / OPTIONS_BOOK SUBSCRIPTION FAILURE controls
# ─────────────────────────────────────────────────────────────────────────────

def test_first_service_succeeds_second_fails_first_still_advances(monkeypatch):
    """L1 subscribes fine; OPTIONS_BOOK errors. L1's vendor-held truth must advance
    (a real ack happened) even though BOOK's does not — the two services are NOT
    collapsed into one all-or-nothing outcome."""
    monkeypatch.setattr("tools.run_stream_capture.read_active_option_contract_signal",
                        lambda: _SPY_CONTRACT)
    stream = _FlakyOptionStream(fail_calls={"options_book_sub"})

    async def go():
        state = {"l1": None, "book": None}
        return await _apply_active_option_contract_subs(stream, state)
    new_state = asyncio.run(go())
    assert new_state["l1"] == _SPY_CONTRACT, "L1's real vendor ack must not be discarded"
    assert new_state["book"] is None, "BOOK's failure must not be papered over as success"


def test_unsubscribe_old_l1_succeeds_book_unsub_fails(monkeypatch):
    """Switching away: L1 unsub succeeds and moves on to subscribe the new symbol; BOOK
    unsub fails, so BOOK must NOT also attempt a new subscribe this tick (would risk two
    live BOOK keys for one service) — it stays on the old (unknown-to-us) symbol, retried
    next tick."""
    p = "unused"
    monkeypatch.setattr("tools.run_stream_capture.read_active_option_contract_signal",
                        lambda: _QQQ_CONTRACT)
    stream = _FlakyOptionStream(fail_calls={"options_book_unsub"})

    async def go():
        state = {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}
        return await _apply_active_option_contract_subs(stream, state)
    new_state = asyncio.run(go())
    assert new_state["l1"] == _QQQ_CONTRACT, "L1 switch completes despite BOOK's failure"
    assert new_state["book"] == _SPY_CONTRACT, (
        "BOOK must stay on its last KNOWN vendor-held symbol, not silently jump to QQQ "
        "without a confirmed unsub+sub, and not silently become None either")
    assert ("options_book_sub", (_QQQ_CONTRACT,)) not in stream.calls, (
        "must not attempt a second live BOOK key while the old one's unsub is unconfirmed"
    )


def test_both_new_subscriptions_succeed(monkeypatch):
    monkeypatch.setattr("tools.run_stream_capture.read_active_option_contract_signal",
                        lambda: _SPY_CONTRACT)
    stream = _FlakyOptionStream()

    async def go():
        state = {"l1": None, "book": None}
        return await _apply_active_option_contract_subs(stream, state)
    new_state = asyncio.run(go())
    assert new_state == {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}


def test_reconnect_with_both_prior_services_active(monkeypatch):
    """_schwab_connect's reconnect-reapply path (a fresh StreamClient, both services
    None) must re-establish both services when both succeed."""
    import tools.run_stream_capture as d
    from types import SimpleNamespace
    import sys
    import types

    class _Fake:
        def __init__(self, *a, **k):
            self.calls = []

        def add_level_one_equity_handler(self, h): pass
        def add_chart_equity_handler(self, h): pass
        def add_nasdaq_book_handler(self, h): pass
        def add_nyse_book_handler(self, h): pass
        def add_level_one_option_handler(self, h): pass
        def add_options_book_handler(self, h): pass

        async def login(self): pass
        async def level_one_equity_subs(self, s): pass
        async def chart_equity_subs(self, s): pass
        async def level_one_option_subs(self, s): self.calls.append(("l1_sub", tuple(s)))
        async def options_book_subs(self, s): self.calls.append(("book_sub", tuple(s)))
        async def level_one_option_unsubs(self, s): pass
        async def options_book_unsubs(self, s): pass
        async def handle_message(self): await asyncio.sleep(3600)

    monkeypatch.setitem(sys.modules, "schwab.streaming",
                        types.SimpleNamespace(StreamClient=_Fake))

    async def go():
        from stream_spine import HealthRegistry, MessageBus
        bus, health, stats, stop = MessageBus(), object(), object(), asyncio.Event()
        from tools.run_stream_capture import CaptureStats
        stream, task, contract_state = await d._schwab_connect(
            SimpleNamespace(client=object()), ["SPY"], bus, HealthRegistry(), CaptureStats(),
            stop, active_option_contract=_SPY_CONTRACT)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return stream, contract_state
    stream, contract_state = asyncio.run(go())
    assert contract_state == {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}
    assert ("l1_sub", (_SPY_CONTRACT,)) in stream.calls
    assert ("book_sub", (_SPY_CONTRACT,)) in stream.calls


def test_reconnect_where_one_resubscription_fails(monkeypatch):
    """Reconnect-reapply: L1 resubscribes; BOOK errors. contract_state must reflect the
    partial outcome truthfully — never claim BOOK is held when it is not."""
    import tools.run_stream_capture as d
    from types import SimpleNamespace
    import sys
    import types

    class _Fake:
        def __init__(self, *a, **k):
            self.calls = []

        def add_level_one_equity_handler(self, h): pass
        def add_chart_equity_handler(self, h): pass
        def add_nasdaq_book_handler(self, h): pass
        def add_nyse_book_handler(self, h): pass
        def add_level_one_option_handler(self, h): pass
        def add_options_book_handler(self, h): pass

        async def login(self): pass
        async def level_one_equity_subs(self, s): pass
        async def chart_equity_subs(self, s): pass
        async def level_one_option_subs(self, s): self.calls.append(("l1_sub", tuple(s)))
        async def options_book_subs(self, s):
            raise RuntimeError("simulated post-reconnect BOOK resub failure")
        async def level_one_option_unsubs(self, s): pass
        async def options_book_unsubs(self, s): pass
        async def handle_message(self): await asyncio.sleep(3600)

    monkeypatch.setitem(sys.modules, "schwab.streaming",
                        types.SimpleNamespace(StreamClient=_Fake))

    async def go():
        from stream_spine import HealthRegistry, MessageBus
        from tools.run_stream_capture import CaptureStats
        bus, stop = MessageBus(), asyncio.Event()
        stream, task, contract_state = await d._schwab_connect(
            SimpleNamespace(client=object()), ["SPY"], bus, HealthRegistry(), CaptureStats(),
            stop, active_option_contract=_SPY_CONTRACT)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return contract_state
    contract_state = asyncio.run(go())
    assert contract_state == {"l1": _SPY_CONTRACT, "book": None}


def test_repeated_poll_after_partial_failure_recovers_without_duplicate_sub(monkeypatch):
    """After a partial-failure tick (L1 ok, BOOK fails), the NEXT poll tick must retry
    ONLY the still-unheld service (BOOK) — never re-issue L1's already-successful
    subscribe, which the operator explicitly warned against ('blindly issuing duplicate
    subscriptions until they happen to converge')."""
    monkeypatch.setattr("tools.run_stream_capture.read_active_option_contract_signal",
                        lambda: _SPY_CONTRACT)
    stream = _FlakyOptionStream(fail_calls={"options_book_sub"})

    async def go():
        state = {"l1": None, "book": None}
        state = await _apply_active_option_contract_subs(stream, state)   # tick 1
        assert state == {"l1": _SPY_CONTRACT, "book": None}
        calls_after_tick1 = len(stream.calls)
        stream.fail_calls = set()   # the transient vendor failure clears
        state = await _apply_active_option_contract_subs(stream, state)   # tick 2 (recovery)
        return state, calls_after_tick1
    state, calls_after_tick1 = asyncio.run(go())
    assert state == {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}
    l1_sub_calls = [c for c in stream.calls if c[0] == "l1_option_sub"]
    assert len(l1_sub_calls) == 1, (
        f"L1 was already successfully held after tick 1 (no change requested for it on "
        f"tick 2) — a duplicate resubscribe is exactly the anti-pattern being tested for; "
        f"calls={stream.calls}")
    book_sub_calls = [c for c in stream.calls if c[0] == "options_book_sub"]
    assert len(book_sub_calls) == 2, "BOOK retries on tick 2 after its tick-1 failure"


# ─────────────────────────────────────────────────────────────────────────────
# PR214_FINAL_MERGE_BLOCKERS_V2 — Blocker 2B must COMPOSE with the existing
# pending-close retry machinery this file already protects. open_coverage_epoch now
# refuses a second open epoch for the same (symbol, service); a close that FAILED
# leaves that row open, so the next re-open of the same pair meets the guard. It must
# fail CLOSED (memory claims no coverage) and SELF-HEAL once the pending close lands.
# ─────────────────────────────────────────────────────────────────────────────

def test_blocker2b_guard_fails_closed_on_stuck_close_then_self_heals(tmp_path, monkeypatch):
    from tools.run_stream_capture import (
        _close_coverage_epoch_tracked,
        _open_coverage_epoch_tracked,
        _retry_pending_epoch_closes,
    )

    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=1, batch_sec=10.0)
    try:
        epoch_state: dict = {"l1": None}
        _open_coverage_epoch_tracked(writer, epoch_state, "l1", _SPY_CONTRACT,
                                     "LEVELONE_OPTIONS", reason="active_contract_set")
        first_id = epoch_state["l1"]
        assert first_id is not None

        # The durable CLOSE fails -> the row stays OPEN, the id is tracked pending.
        real_close = writer.close_coverage_epoch
        fail = {"on": True}

        def _flaky_close(epoch_id, **k):
            if fail["on"]:
                raise CoverageWriteError("simulated durable-write outage on close")
            return real_close(epoch_id, **k)
        monkeypatch.setattr(writer, "close_coverage_epoch", _flaky_close)
        _close_coverage_epoch_tracked(writer, epoch_state, "l1", reason="stream_recycle")
        assert _pending_ids(epoch_state, "l1") == {first_id}
        assert epoch_state["l1"] is None

        # Re-opening the SAME (symbol, service) while that row is still open must be
        # REFUSED, and refused FAIL-CLOSED: memory must not claim coverage.
        _open_coverage_epoch_tracked(writer, epoch_state, "l1", _SPY_CONTRACT,
                                     "LEVELONE_OPTIONS", reason="active_contract_set")
        assert epoch_state["l1"] is None, (
            "a refused open must leave epoch_state None -- never a coverage claim the "
            "epoch table does not durably record")
        assert len(_epochs(tmp_path / "cap.db")) == 1, (
            "the refused open must not have written a contradictory second row")

        # Once the outage clears, the EXISTING retry path closes the stuck epoch and the
        # re-open then succeeds -- no operator action, exactly as before the guard.
        fail["on"] = False
        _retry_pending_epoch_closes(writer, epoch_state, "l1", reason="retry_pending_close")
        assert _pending_ids(epoch_state, "l1") == set()
        _open_coverage_epoch_tracked(writer, epoch_state, "l1", _SPY_CONTRACT,
                                     "LEVELONE_OPTIONS", reason="active_contract_set")
        assert epoch_state["l1"] is not None and epoch_state["l1"] != first_id
        rows = _epochs(tmp_path / "cap.db")
        assert len(rows) == 2
        assert rows[0][2] is not None, "the stuck epoch is closed by the retry"
        assert rows[1][2] is None, "exactly one epoch is now open for this pair"
    finally:
        writer.close()


def test_gap4_D_duplicate_open_refusal_cannot_leave_vendor_held(tmp_path, monkeypatch):
    """PR214 premerge gap 4, attack D. The 2B duplicate-open guard REFUSES the epoch
    open (a stale open row for this pair already exists). That refusal must not be a
    back door into the exact shape gap 4 closes: vendor subscribed, ledger holding no
    new valid epoch. Compensation applies to a refusal exactly as to a write failure."""
    monkeypatch.setattr("tools.run_stream_capture.read_active_option_contract_signal",
                        lambda: _SPY_CONTRACT)
    stream = _FlakyOptionStream()
    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=1, batch_sec=10.0)
    try:
        # Seed a stale OPEN epoch for the same (symbol, service) pairs, as a lost close
        # or a skipped reconciliation would leave behind.
        writer._conn.execute(
            "INSERT INTO stream_coverage_epochs(symbol,service,started_ts,reason) "
            "VALUES(?,?,0,'stale_open'),(?,?,0,'stale_open')",
            (_SPY_CONTRACT, "LEVELONE_OPTIONS", _SPY_CONTRACT, "OPTIONS_BOOK"))
        writer._conn.commit()
        epoch_state: dict = {"l1": None, "book": None}

        async def go():
            return await _apply_active_option_contract_subs(
                stream, {"l1": None, "book": None}, writer=writer, epoch_state=epoch_state)
        new_state = asyncio.run(go())

        assert new_state == {"l1": None, "book": None}, (
            "a refused duplicate open must compensate the vendor subscription away, not "
            "leave it held against a ledger with no new valid epoch")
        assert epoch_state["l1"] is None and epoch_state["book"] is None
        rows = _epochs(tmp_path / "cap.db")
        assert len(rows) == 2, "the refusal must not have written a second row per pair"
    finally:
        writer.close()


def test_gap4_steady_state_vendor_held_implies_durable_open_epoch(tmp_path, monkeypatch):
    """ADJACENT INVARIANT, mechanically demonstrated across the outcomes that can end a
    tick: for EVERY option service, VENDOR_HELD(symbol) ⇒ CURRENT_DURABLE_OPEN_EPOCH
    (symbol, service). Checked against the REAL epochs table, not against epoch_state."""
    monkeypatch.setattr("tools.run_stream_capture.read_active_option_contract_signal",
                        lambda: _SPY_CONTRACT)

    def _assert_invariant(db_path, held_state):
        con = sqlite3.connect(db_path)
        try:
            open_rows = con.execute(
                "SELECT symbol, service FROM stream_coverage_epochs "
                "WHERE ended_ts IS NULL").fetchall()
        finally:
            con.close()
        open_by_service = {svc: sym for sym, svc in open_rows}
        for key, service in (("l1", "LEVELONE_OPTIONS"), ("book", "OPTIONS_BOOK")):
            held = held_state.get(key)
            if held is not None:
                assert open_by_service.get(service) == held, (
                    f"VENDOR_HELD({held}) for {service} with no matching durable open "
                    f"epoch — open rows: {open_rows}")

    # 1. NORMAL: subscribe + durable epoch both succeed -> held, and the epoch exists.
    db1 = tmp_path / "ok.db"
    w1 = CaptureWriter(db1, batch_rows=1, batch_sec=10.0)
    try:
        st1 = asyncio.run(_apply_active_option_contract_subs(
            _FlakyOptionStream(), {"l1": None, "book": None},
            writer=w1, epoch_state={"l1": None, "book": None}))
        assert st1 == {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}
        _assert_invariant(db1, st1)
    finally:
        w1.close()

    # 2. COMPENSATED: durable open fails -> nothing held, invariant vacuously holds.
    db2 = tmp_path / "compensated.db"
    w2 = CaptureWriter(db2, batch_rows=1, batch_sec=10.0)
    try:
        def _boom(*a, **k):
            raise CoverageWriteError("simulated durable-write outage")
        monkeypatch.setattr(w2, "open_coverage_epoch", _boom)
        st2 = asyncio.run(_apply_active_option_contract_subs(
            _FlakyOptionStream(), {"l1": None, "book": None},
            writer=w2, epoch_state={"l1": None, "book": None}))
        assert st2 == {"l1": None, "book": None}
        _assert_invariant(db2, st2)
    finally:
        w2.close()

    # 3. PARTIAL VENDOR FAILURE: one service subscribes, the other does not. The one that
    #    IS held must still have its durable epoch; the failed one holds nothing.
    db3 = tmp_path / "partial.db"
    w3 = CaptureWriter(db3, batch_rows=1, batch_sec=10.0)
    try:
        st3 = asyncio.run(_apply_active_option_contract_subs(
            _FlakyOptionStream(fail_calls={"options_book_sub"}), {"l1": None, "book": None},
            writer=w3, epoch_state={"l1": None, "book": None}))
        assert st3["l1"] == _SPY_CONTRACT and st3["book"] is None
        _assert_invariant(db3, st3)
    finally:
        w3.close()


# ─────────────────────────────────────────────────────────────────────────────
# PR214 BIDIRECTIONAL COVERAGE TRUTH (defect 1) — the SUBSCRIBE->open direction was
# already compensated; its mirror was missing. MEASURED before the fix, driving the real
# seam: vendor UNSUB A succeeded, durable CLOSE A failed, and the code went on to
# SUBSCRIBE B, leaving `id=1 SPY ended_ts=None` AND `id=2 QQQ ended_ts=None` on ONE
# service. Because these epochs are also read as PRODUCER SUBSCRIPTION IDENTITY, that
# makes "what is this service subscribed to" unanswerable.
#
# Canonical steady-state invariant per option service:
#   VENDOR_HELD(X)    IFF  exactly one open epoch exists AND its symbol == X
#   VENDOR_HELD(None) IFF  zero open epochs exist
# (an explicit compensation/recycle failure may leave UNKNOWN, but never continues as
# normal steady state).
# ─────────────────────────────────────────────────────────────────────────────

def _one_service_open(db_path, service="LEVELONE_OPTIONS"):
    con = sqlite3.connect(db_path)
    try:
        return con.execute(
            "SELECT id, symbol FROM stream_coverage_epochs "
            "WHERE service=? AND ended_ts IS NULL ORDER BY id", (service,)).fetchall()
    finally:
        con.close()


def _switch_tick(stream, writer, epoch_state, held, requested):
    return asyncio.run(_reconcile_option_service(
        stream, held, requested,
        subs_fn=stream.level_one_option_subs, unsubs_fn=stream.level_one_option_unsubs,
        writer=writer, epoch_state=epoch_state,
        epoch_key="l1", service_name="LEVELONE_OPTIONS"))


def test_coverage_A_close_failure_never_touches_the_vendor(tmp_path, monkeypatch):
    """CASE A — the most important attack (PR214 coverage-interval causality).

    REWRITTEN. This previously asserted the resubscribe ROLLBACK (unsub A, then resub A
    on close failure). That rollback restored the END state but could not undo the
    INTERVAL: measured, A's epoch stayed open across a window in which the vendor was
    definitively unsubscribed. Durable-close-first removes the need for it entirely --
    when the close fails the vendor is never touched at all, so there is no interval to
    hide and nothing to compensate."""
    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        eid = w.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS",
                                    reason="active_contract_set", ts=1.0)
        epoch_state = {"l1": eid}
        monkeypatch.setattr(w, "close_coverage_epoch", _failing_close)
        stream = _FlakyOptionStream()

        held = _switch_tick(stream, w, epoch_state, _SPY_CONTRACT, _QQQ_CONTRACT)

        unsub_calls = [c for c in stream.calls if c[0] == "l1_option_unsub"]
        sub_calls = [c for c in stream.calls if c[0] == "l1_option_sub"]
        assert len(unsub_calls) == 0, (
            f"unsubs_fn CALL COUNT must be 0 when the durable close failed; got {unsub_calls}")
        assert len(sub_calls) == 0, (
            f"subs_fn CALL COUNT must be 0 when the durable close failed; got {sub_calls}")
        assert stream.calls == [], "the vendor must not be touched at all"
        assert held == _SPY_CONTRACT, "the vendor still holds A — it was never changed"
        rows = _one_service_open(db)
        assert len(rows) == 1 and rows[0][1] == _SPY_CONTRACT, (
            f"exactly one open epoch, still on A; got {rows}")
        assert epoch_state["l1"] == eid, "A's epoch id remains the current epoch"
        assert _pending_ids(epoch_state, "l1") == set(), (
            "the epoch describes a live subscription we deliberately kept — closing it is "
            "not the correct action to retry")
    finally:
        w.close()


def test_coverage_C_vendor_unsub_failure_after_durable_close_fails_closed(tmp_path, monkeypatch):
    """CASE C — durable CLOSE A succeeded, vendor UNSUB A then failed/unconfirmed.

    REPLACES the old close-fail + resubscribe-fail escalation, which cannot occur under
    durable-close-first (no resubscribe exists). The ledger has already surrendered A's
    coverage claim while the vendor operation is unconfirmed: B must not be subscribed,
    no false A epoch may be recreated to make the states look equal, and the existing
    recycle path must be forced. A conservative uncovered interval beats a fabricated
    subscribed one."""
    from tools.run_stream_capture import OptionCoverageCompensationError

    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        w.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS",
                              reason="active_contract_set", ts=1.0)
        epoch_state = {"l1": 1}
        stream = _FlakyOptionStream(fail_calls={"l1_option_unsub"})   # vendor unsub fails

        with pytest.raises(OptionCoverageCompensationError) as exc:
            _switch_tick(stream, w, epoch_state, _SPY_CONTRACT, _QQQ_CONTRACT)
        msg = str(exc.value)
        assert "was closed but the vendor unsubscribe then failed" in msg
        assert "forcing stream recycle" in msg

        assert [c for c in stream.calls if c[0] == "l1_option_sub"] == [], (
            "B must never be subscribed on the escalation path")
        assert _one_service_open(db) == [], (
            "A's epoch stays CLOSED — no false open epoch may be recreated merely to make "
            "vendor and ledger look equal over an interval we cannot vouch for")
    finally:
        w.close()


def test_4A_vendor_held_with_no_durable_epoch_fails_closed(tmp_path):
    """4A. REVERSED. This test previously asserted the OPPOSITE — that a writer present
    with no tracked epoch id should keep the historical unsub-failure retry, "not escalate
    the whole session over a coverage claim that was never made". That reasoning is wrong,
    and the test was holding the defect in place.

    Under production coverage authority the shape

        vendor-held = A   AND   epoch_state[service] is None

    is not a harmless one-tick under-claim. `held` is a remembered string, not a vendor
    acknowledgement. Nothing in the tick re-confirms it, and an unsubscribe failure hands
    the SAME shape back — so it re-enters itself for as long as the unsubscribe keeps
    failing, with real quotes landing in stream_options_quotes_raw the whole time while
    the ledger answers "not subscribed". A provenance hole that sustains itself defeats
    the exact distinction the ledger exists to make.

    It must fail closed instead, so a fresh generation can EARN coverage through
    vendor SUB success -> durable OPEN success."""
    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        epoch_state = {"l1": None}          # vendor holds A, but no epoch is tracked
        stream = _FlakyOptionStream(fail_calls={"l1_option_unsub"})
        with pytest.raises(rsc.OptionCoverageCompensationError) as exc:
            _switch_tick(stream, w, epoch_state, _SPY_CONTRACT, _QQQ_CONTRACT)
        assert "with NO durable coverage epoch at tick entry" in str(exc.value)
        assert "forcing stream recycle" in str(exc.value)
        assert stream.calls == [], (
            "fail closed BEFORE touching the vendor: no unsubscribe, and above all no "
            f"subscribe of the new contract; got {stream.calls}")
        assert _one_service_open(db) == [], "no epoch may be fabricated from a memory"
    finally:
        w.close()


def test_4A_the_state_cannot_self_sustain_across_repeated_unsub_failures(tmp_path):
    """4A-B. The persistent-unsubscribe-failure attack: the same entry state, driven
    repeatedly. It must escalate on EVERY tick rather than quietly returning held=A and
    re-entering itself, which is how the hole used to sustain indefinitely."""
    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        epoch_state = {"l1": None}
        for tick in range(5):
            stream = _FlakyOptionStream(fail_calls={"l1_option_unsub"})
            with pytest.raises(rsc.OptionCoverageCompensationError):
                _switch_tick(stream, w, epoch_state, _SPY_CONTRACT, _QQQ_CONTRACT)
            assert stream.calls == [], f"tick {tick}: vendor touched while inconsistent"
            assert _one_service_open(db) == [], f"tick {tick}: coverage fabricated"
    finally:
        w.close()


def test_4B_open_epoch_with_no_vendor_hold_is_surrendered_before_any_subscribe(tmp_path):
    """4B. The inverse impossible state, adjudicated mechanically rather than assumed
    away: nothing is held at the vendor, yet a durable epoch is still open.

    Claiming coverage while holding no subscription is a false positive by definition. It
    must be resolved BEFORE any new subscribe — never left open beside a B epoch, which
    would put two open epochs on one single-contract service and make "what is this
    service subscribed to" unanswerable. Surrender is sufficient and correct here (unlike
    4A there is no uncertain vendor state to recycle over): no subscription exists, so the
    claim is simply false and is closed."""
    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        stale = w.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS",
                                      reason="active_contract_set", ts=1.0)
        epoch_state = {"l1": stale}
        stream = _FlakyOptionStream()
        held = _switch_tick(stream, w, epoch_state, None, _QQQ_CONTRACT)

        assert held == _QQQ_CONTRACT, "the legitimate B subscribe still completes"
        rows = _epochs(db)
        stale_row = [r for r in rows if r[0] == _SPY_CONTRACT]
        assert len(stale_row) == 1 and stale_row[0][2] is not None, (
            f"the stale A claim must be surrendered, not left open: {rows}")
        assert len(_one_service_open(db)) == 1, (
            f"exactly one open epoch afterwards, on B; got {_one_service_open(db)}")
        assert _one_service_open(db)[0][1] == _QQQ_CONTRACT
    finally:
        w.close()


def test_coverage_C_no_ledger_caller_keeps_historical_unsub_failure_behaviour():
    """Scoping control for CASE C: a caller with NO writer/epoch_state surrenders no
    coverage claim, so an unsub failure must NOT escalate — it keeps the historical
    behaviour of staying on the last KNOWN vendor-held symbol and retrying next tick.
    Without this scoping the fix would have changed the no-ledger path too."""
    stream = _FlakyOptionStream(fail_calls={"l1_option_unsub"})
    held = asyncio.run(_reconcile_option_service(
        stream, _SPY_CONTRACT, _QQQ_CONTRACT,
        subs_fn=stream.level_one_option_subs, unsubs_fn=stream.level_one_option_unsubs,
        writer=None, epoch_state=None, epoch_key="l1", service_name="LEVELONE_OPTIONS"))
    assert held == _SPY_CONTRACT
    assert [c for c in stream.calls if c[0] == "l1_option_sub"] == [], (
        "must not open a second live key while the old unsub is unconfirmed")


def test_coverage_C_pending_close_retry_cannot_close_a_still_live_subscription(tmp_path, monkeypatch):
    """1G-C (defect 1D), RETARGETED for durable-close-first.

    Originally: 'after the compensating RESUB restores A'. There is no resubscribe any
    more — under close-first a failed durable close means the vendor was NEVER touched,
    so A was never unsubscribed and nothing had to be restored. The assertion this test
    exists for is unchanged and is now reached by a stronger route: A's epoch is still
    open because A's subscription is still LIVE, so the pending-close retry machinery
    must not later close it behind that live subscription's back."""
    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        eid = w.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS",
                                    reason="active_contract_set", ts=1.0)
        epoch_state = {"l1": eid}
        real_close = w.close_coverage_epoch
        monkeypatch.setattr(w, "close_coverage_epoch", _failing_close)
        stream = _FlakyOptionStream()
        held = _switch_tick(stream, w, epoch_state, _SPY_CONTRACT, _QQQ_CONTRACT)
        assert held == _SPY_CONTRACT
        # The close-first reason the epoch is legitimately open: no vendor op ever ran.
        assert stream.calls == [], (
            "the durable close failed first, so the vendor must be untouched — the epoch "
            "is open because the subscription never stopped, not because it was restored")
        assert _pending_ids(epoch_state, "l1") == set(), (
            "a still-live epoch must not remain queued for closing")

        # The DB recovers; a retry pass now runs with A still subscribed the whole time.
        monkeypatch.setattr(w, "close_coverage_epoch", real_close)
        _retry_pending_epoch_closes(w, epoch_state, "l1", reason="retry_pending_close")

        rows = _one_service_open(db)
        assert len(rows) == 1 and rows[0][1] == _SPY_CONTRACT, (
            "the retry must not have closed the epoch of a still-live subscription")
        assert epoch_state["l1"] == eid
    finally:
        w.close()


def test_coverage_D_switch_completes_cleanly_once_the_db_recovers(tmp_path, monkeypatch):
    """1G-D. Next tick, with B still requested and the durable write working again, the
    A->B switch completes: exactly one open epoch, on B."""
    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        eid = w.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS",
                                    reason="active_contract_set", ts=1.0)
        epoch_state = {"l1": eid}
        real_close = w.close_coverage_epoch
        monkeypatch.setattr(w, "close_coverage_epoch", _failing_close)
        stream = _FlakyOptionStream()
        held = _switch_tick(stream, w, epoch_state, _SPY_CONTRACT, _QQQ_CONTRACT)
        assert held == _SPY_CONTRACT     # tick 1: vendor untouched, transition deferred
        assert stream.calls == [], "close failed first, so tick 1 issued no vendor op"

        monkeypatch.setattr(w, "close_coverage_epoch", real_close)   # DB recovers
        stream2 = _FlakyOptionStream()
        held2 = _switch_tick(stream2, w, epoch_state, held, _QQQ_CONTRACT)

        assert held2 == _QQQ_CONTRACT, "tick 2 must complete the transition"
        assert stream2.calls == [("l1_option_unsub", (_SPY_CONTRACT,)),
                                 ("l1_option_sub", (_QQQ_CONTRACT,))]
        rows = _one_service_open(db)
        assert len(rows) == 1 and rows[0][1] == _QQQ_CONTRACT, (
            f"exactly one open epoch, now on B; got {rows}")
    finally:
        w.close()


def test_coverage_E_service_wide_duplicate_open_is_blocked(tmp_path):
    """1G-E (defect 1E). A OPEN must mechanically prevent B OPEN on the SAME service,
    even though the symbols differ -- the old (symbol, service) guard let this through,
    which is exactly how the measured A-open/B-open contradiction was written."""
    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        for service in ("LEVELONE_OPTIONS", "OPTIONS_BOOK"):
            w.open_coverage_epoch(_SPY_CONTRACT, service, reason="active_contract_set", ts=1.0)
            with pytest.raises(CoverageWriteError) as exc:
                w.open_coverage_epoch(_QQQ_CONTRACT, service,
                                      reason="active_contract_set", ts=2.0)
            msg = str(exc.value)
            assert "refusing to open a second epoch" in msg
            assert f"service {service}" in msg, (
                "the refusal must be scoped to the SERVICE, not to (symbol, service)")
            assert len(_one_service_open(db, service)) == 1
        # A non-single-contract service keeps the historical per-(symbol, service) scope.
        w.open_coverage_epoch("SPY", "NASDAQ_BOOK", reason="x", ts=1.0)
        w.open_coverage_epoch("QQQ", "NASDAQ_BOOK", reason="x", ts=1.0)
        assert len(_one_service_open(db, "NASDAQ_BOOK")) == 2, (
            "multi-symbol services must NOT be narrowed by the option-service rule")
    finally:
        w.close()


def test_coverage_G_normal_switch_path_is_unchanged(tmp_path):
    """1G-G. With a healthy durable writer the ordinary A->B switch behaves exactly as
    before: unsub A, close A, sub B, one open epoch on B."""
    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        eid = w.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS",
                                    reason="active_contract_set", ts=1.0)
        epoch_state = {"l1": eid}
        stream = _FlakyOptionStream()
        held = _switch_tick(stream, w, epoch_state, _SPY_CONTRACT, _QQQ_CONTRACT)
        assert held == _QQQ_CONTRACT
        assert stream.calls == [("l1_option_unsub", (_SPY_CONTRACT,)),
                                ("l1_option_sub", (_QQQ_CONTRACT,))]
        rows = _one_service_open(db)
        assert len(rows) == 1 and rows[0][1] == _QQQ_CONTRACT
    finally:
        w.close()


def test_coverage_bidirectional_invariant_holds_at_every_tick_boundary(tmp_path, monkeypatch):
    """The full BIDIRECTIONAL invariant, checked against the REAL table:
       VENDOR_HELD(X)    IFF exactly one open epoch, symbol == X
       VENDOR_HELD(None) IFF zero open epochs."""
    def _check(db_path, held, service="LEVELONE_OPTIONS"):
        rows = _one_service_open(db_path, service)
        if held is None:
            assert rows == [], f"vendor holds nothing but {len(rows)} epoch(s) are open: {rows}"
        else:
            assert len(rows) == 1 and rows[0][1] == held, (
                f"vendor holds {held!r} but open epochs are {rows}")

    # normal switch
    db1 = tmp_path / "a.db"
    w1 = CaptureWriter(db1, batch_rows=1, batch_sec=10.0)
    try:
        eid = w1.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS", reason="x", ts=1.0)
        st = {"l1": eid}
        s = _FlakyOptionStream()
        _check(db1, _SPY_CONTRACT)
        held = _switch_tick(s, w1, st, _SPY_CONTRACT, _QQQ_CONTRACT)
        _check(db1, held)
        # switch to nothing requested -> vendor holds nothing, zero open epochs
        held = _switch_tick(_FlakyOptionStream(), w1, st, held, None)
        _check(db1, held)
        assert held is None
    finally:
        w1.close()

    # close-failure compensation boundary
    db2 = tmp_path / "b.db"
    w2 = CaptureWriter(db2, batch_rows=1, batch_sec=10.0)
    try:
        eid = w2.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS", reason="x", ts=1.0)
        st = {"l1": eid}
        monkeypatch.setattr(w2, "close_coverage_epoch", _failing_close)
        held = _switch_tick(_FlakyOptionStream(), w2, st, _SPY_CONTRACT, _QQQ_CONTRACT)
        _check(db2, held)
    finally:
        w2.close()


# ─────────────────────────────────────────────────────────────────────────────
# PR214 COVERAGE-INTERVAL CAUSALITY — tick-boundary consistency is not interval truth.
#
# MEASURED before the fix, with a deterministic clock:
#   t=101.0 DURABLE_OPEN_A            started_ts=101.0
#   t=102.0 VENDOR_UNSUB_COMPLETE     <- A definitively NOT subscribed from here
#   t=103.0 DURABLE_CLOSE_A failed
#   t=104.0 VENDOR_SUB_COMPLETE       <- A subscribed again (compensating resubscribe)
#   ledger: started_ts=101.0, ended_ts=NULL
# The single continuous open epoch therefore CLAIMED coverage across [102.0, 104.0], a
# window in which the vendor was definitively unsubscribed -- turning our own coverage
# hole into what would later read as observed market silence.
#
# Root fix: durable CLOSE happens BEFORE the vendor is touched, so a failed close never
# produces a vendor operation at all, and a successful transition brackets the vendor gap
# conservatively from the outside.
# ─────────────────────────────────────────────────────────────────────────────

class _RecordingOptionStream(_FlakyOptionStream):
    """Records a wall-clock timestamp for each COMPLETED vendor operation, so the real
    ordering and the durable timestamps can be compared without a test-only `ts`
    parameter threaded through production code."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.events: list[tuple] = []

    async def _maybe_fail(self, name, syms):
        await super()._maybe_fail(name, syms)
        self.events.append((name, tuple(syms), time.time()))


def test_temporal_normal_switch_orders_close_unsub_sub_open(tmp_path):
    """REQUIRED attack 2 + 5. Records the real operation order and the durable timestamps
    on an ordinary A->B switch, and proves the conservative bracketing:
        durable CLOSE A  <  vendor UNSUB A  <  vendor SUB B  <  durable OPEN B
        A.ended_ts   <= confirmed vendor UNSUB A completion
        B.started_ts >= confirmed vendor SUB B completion
    so every known vendor-not-subscribed instant lies OUTSIDE durable coverage."""
    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        order: list[str] = []
        real_close, real_open = w.close_coverage_epoch, w.open_coverage_epoch

        def _close(eid, **k):
            order.append("durable_close")
            return real_close(eid, **k)

        def _open(sym, svc, **k):
            order.append("durable_open")
            return real_open(sym, svc, **k)
        w.close_coverage_epoch, w.open_coverage_epoch = _close, _open

        w.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS",
                              reason="active_contract_set")
        order.clear()                      # ignore the setup open
        epoch_state = {"l1": 1}
        stream = _RecordingOptionStream()

        held = _switch_tick(stream, w, epoch_state, _SPY_CONTRACT, _QQQ_CONTRACT)
        assert held == _QQQ_CONTRACT

        vendor_order = [e[0] for e in stream.events]
        assert vendor_order == ["l1_option_unsub", "l1_option_sub"]
        assert order == ["durable_close", "durable_open"]

        # Interleave the two recordings into one causal sequence.
        t_unsub = next(e[2] for e in stream.events if e[0] == "l1_option_unsub")
        t_sub = next(e[2] for e in stream.events if e[0] == "l1_option_sub")
        con = sqlite3.connect(db)
        try:
            rows = con.execute(
                "SELECT symbol, started_ts, ended_ts FROM stream_coverage_epochs "
                "ORDER BY id").fetchall()
        finally:
            con.close()
        a_row = next(r for r in rows if r[0] == _SPY_CONTRACT)
        b_row = next(r for r in rows if r[0] == _QQQ_CONTRACT)

        assert a_row[2] is not None, "A must be durably closed"
        assert a_row[2] <= t_unsub, (
            f"A.ended_ts ({a_row[2]}) must not be AFTER the confirmed vendor unsubscribe "
            f"({t_unsub}) — the coverage claim is surrendered before the vendor is touched")
        assert b_row[1] >= t_sub, (
            f"B.started_ts ({b_row[1]}) must not precede the confirmed vendor subscribe "
            f"({t_sub}) — coverage may not begin before the subscription exists")
        assert b_row[2] is None
        # The uncovered ledger interval strictly CONTAINS the real vendor gap.
        assert a_row[2] <= t_unsub <= t_sub <= b_row[1]
    finally:
        w.close()


def test_temporal_no_open_epoch_may_bridge_a_known_unsubscribed_interval(tmp_path, monkeypatch):
    """REQUIRED attack 6, stated as the canonical principle:
        KNOWN_VENDOR_NOT_SUBSCRIBED(service, t)
          => DURABLE_COVERAGE_MUST_NOT_CLAIM_SUBSCRIBED(service, t)

    Drives both outcomes a transition can have and, for each, checks every epoch row
    against every interval in which the vendor was known to be unsubscribed. This is the
    assertion the pre-fix code failed: its single continuous A epoch spanned the
    unsub->resubscribe window."""
    def _known_unsubscribed_intervals(events):
        """[(start, end)] windows where this service had NO vendor subscription."""
        out, open_since = [], None
        for name, _syms, ts in events:
            if name.endswith("_unsub"):
                open_since = ts                     # not subscribed from here...
            elif name.endswith("_sub") and open_since is not None:
                out.append((open_since, ts))        # ...until here
                open_since = None
        if open_since is not None:
            out.append((open_since, float("inf")))
        return out

    def _assert_no_bridge(db_path, events):
        con = sqlite3.connect(db_path)
        try:
            rows = con.execute(
                "SELECT symbol, started_ts, ended_ts FROM stream_coverage_epochs").fetchall()
        finally:
            con.close()
        for lo, hi in _known_unsubscribed_intervals(events):
            for sym, started, ended in rows:
                end = float("inf") if ended is None else ended
                overlap = max(started, lo) < min(end, hi)
                assert not overlap, (
                    f"epoch {sym!r} [{started}, {ended}] CLAIMS coverage inside a known "
                    f"unsubscribed interval [{lo}, {hi}]")

    # 1. Ordinary switch: a real vendor gap exists between unsub A and sub B.
    db1 = tmp_path / "switch.db"
    w1 = CaptureWriter(db1, batch_rows=1, batch_sec=10.0)
    try:
        w1.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS", reason="x")
        s1 = _RecordingOptionStream()
        _switch_tick(s1, w1, {"l1": 1}, _SPY_CONTRACT, _QQQ_CONTRACT)
        assert _known_unsubscribed_intervals(s1.events), "the attack needs a real gap"
        _assert_no_bridge(db1, s1.events)
    finally:
        w1.close()

    # 2. Close-failure: no vendor operation at all, so no interval and no bridge.
    db2 = tmp_path / "closefail.db"
    w2 = CaptureWriter(db2, batch_rows=1, batch_sec=10.0)
    try:
        w2.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS", reason="x")
        monkeypatch.setattr(w2, "close_coverage_epoch", _failing_close)
        s2 = _RecordingOptionStream()
        held = _switch_tick(s2, w2, {"l1": 1}, _SPY_CONTRACT, _QQQ_CONTRACT)
        assert held == _SPY_CONTRACT
        assert s2.events == [], "the vendor was never touched, so no interval exists"
        _assert_no_bridge(db2, s2.events)
    finally:
        w2.close()


@pytest.mark.parametrize("close_ok", [True, False])
@pytest.mark.parametrize("unsub_ok", [True, False])
@pytest.mark.parametrize("sub_ok", [True, False])
@pytest.mark.parametrize("open_ok", [True, False])
def test_exhaustive_failure_matrix_never_claims_false_coverage(
        tmp_path, monkeypatch, close_ok, unsub_ok, sub_ok, open_ok):
    """EXHAUSTIVE: all 16 combinations of (durable close, vendor unsub, vendor sub,
    durable open) succeeding or failing on one A->B transition. For EVERY outcome --
    including the explicit fail-closed escalations -- the durable ledger must satisfy:

      1. no epoch claims coverage inside a known vendor-unsubscribed interval;
      2. at most ONE open epoch for the service;
      3. on a normal (non-escalating) return, vendor-held and the ledger agree exactly:
         held is X  <=> exactly one open epoch whose symbol is X
         held is None <=> zero open epochs.

    An escalation (OptionCoverageCompensationError) is an allowed UNKNOWN outcome, but
    (1) and (2) must still hold — the recycle path may not leave fabricated coverage."""
    from tools.run_stream_capture import OptionCoverageCompensationError

    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        real_close, real_open = w.close_coverage_epoch, w.open_coverage_epoch
        w.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS", reason="seed")
        epoch_state = {"l1": 1}

        def _close(eid, **k):
            if not close_ok:
                raise CoverageWriteError("matrix: close fails")
            return real_close(eid, **k)

        def _open(sym, svc, **k):
            if not open_ok:
                raise CoverageWriteError("matrix: open fails")
            return real_open(sym, svc, **k)
        monkeypatch.setattr(w, "close_coverage_epoch", _close)
        monkeypatch.setattr(w, "open_coverage_epoch", _open)

        fails = set()
        if not unsub_ok:
            fails.add("l1_option_unsub")
        if not sub_ok:
            fails.add("l1_option_sub")
        stream = _RecordingOptionStream(fail_calls=fails)

        escalated = False
        held = None
        try:
            held = _switch_tick(stream, w, epoch_state, _SPY_CONTRACT, _QQQ_CONTRACT)
        except OptionCoverageCompensationError:
            escalated = True

        con = sqlite3.connect(db)
        try:
            rows = con.execute(
                "SELECT symbol, started_ts, ended_ts FROM stream_coverage_epochs "
                "WHERE service='LEVELONE_OPTIONS'").fetchall()
        finally:
            con.close()
        open_rows = [r for r in rows if r[2] is None]
        label = (f"close_ok={close_ok} unsub_ok={unsub_ok} sub_ok={sub_ok} "
                 f"open_ok={open_ok} escalated={escalated} held={held!r}")

        # (2) at most one open epoch for the service, in every outcome
        assert len(open_rows) <= 1, f"{label}: {len(open_rows)} open epochs -> {open_rows}"

        # (1) no epoch may bridge a known unsubscribed interval
        gaps, open_since = [], None
        for name, _syms, ts in stream.events:
            if name.endswith("_unsub"):
                open_since = ts
            elif name.endswith("_sub") and open_since is not None:
                gaps.append((open_since, ts))
                open_since = None
        if open_since is not None:
            gaps.append((open_since, float("inf")))
        for lo, hi in gaps:
            for sym, started, ended in rows:
                end = float("inf") if ended is None else ended
                assert not (max(started, lo) < min(end, hi)), (
                    f"{label}: epoch {sym!r} [{started},{ended}] claims coverage inside "
                    f"known-unsubscribed [{lo},{hi}]")

        # (3) exact vendor <-> ledger agreement on every non-escalating return
        if not escalated:
            if held is None:
                assert open_rows == [], f"{label}: vendor holds nothing but epochs are open"
            else:
                assert len(open_rows) == 1 and open_rows[0][0] == held, (
                    f"{label}: vendor holds {held!r} but open epochs are {open_rows}")
    finally:
        w.close()


def test_an_unpublishable_surrender_must_not_release_the_vendor(tmp_path, monkeypatch):
    """WRITE-AHEAD RETRACTION. A published coverage claim is a LATCHED POSITIVE: it stands
    until something overwrites it. So a surrender the daemon cannot PUBLISH is as
    disqualifying as one it cannot durably close.

    MEASURED before the retraction was ordered first: with both the durable close and the
    claim write failing, the row stayed open, the previously published claim stayed
    standing, and it was still inside the liveness TTL — so the real consumer returned
    contract_match=true against a 0.07s-old heartbeat naming an epoch the daemon had
    already given up. "The heartbeat will go stale" is not a defence; staleness is a whole
    TTL away.

    The fix is the same shape as the durable-close-first law beside it: retract the claim
    BEFORE touching the vendor, and if the retraction cannot be published, keep the
    subscription — which keeps the standing claim TRUE — rather than surrendering behind a
    claim nobody can be told about."""
    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        eid = w.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS",
                                    reason="active_contract_set", ts=1.0)
        epoch_state = {"l1": eid}

        # The durable close still WORKS; only the claim publication fails. That isolates
        # the retraction as the thing being gated — nothing else here can explain a pass.
        def _no_publish(*a, **k):
            raise CoverageWriteError("claim publication unavailable")
        monkeypatch.setattr(w, "write_heartbeat", _no_publish)

        stream = _FlakyOptionStream()
        held = _switch_tick(stream, w, epoch_state, _SPY_CONTRACT, _QQQ_CONTRACT)

        assert held == _SPY_CONTRACT, "the vendor must still hold the old contract"
        assert stream.calls == [], (
            "no vendor operation may run behind an unpublishable surrender; got "
            f"{stream.calls}")
        rows = _one_service_open(db)
        assert len(rows) == 1 and rows[0][1] == _SPY_CONTRACT, (
            f"the epoch must remain open and current, so the standing claim stays TRUE; "
            f"got {rows}")
        assert epoch_state["l1"] == eid, "the epoch id must be reinstated as current"
        assert _pending_ids(epoch_state, "l1") == set(), (
            "a still-live epoch must not be queued for closing")
    finally:
        w.close()


def test_deferred_close_records_the_surrender_time_not_the_retry_time(tmp_path, monkeypatch):
    """A DEFERRED close must not drag ended_ts forward across the durable-write outage.

    Close-first fixes the ordering, but the pending-close retry could still defeat it.
    _try_close_one used to call close_coverage_epoch WITHOUT a ts, so the writer defaulted
    to time.time() -- the moment the database finally accepted the write, not the moment
    coverage was given up. A close that failed at t=100 and only landed at t=400 recorded
    ended_ts=400, claiming the subscription covered [100, 400] -- exactly the window the
    subscription was already gone for, and unbounded by anything except outage length.

    This is the same false-positive claim as the original interval defect, deferred, so
    it gets the same standard: the ledger may under-claim, never over-claim.

    MEASURED against the pre-fix code this asserts ended_ts == 400.0 (the retry instant);
    it must now be 100.0 (the surrender instant)."""
    clock = {"t": 100.0}
    monkeypatch.setattr(rsc.time, "time", lambda: clock["t"])

    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        eid = w.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS",
                                    reason="active_contract_set", ts=1.0)
        epoch_state = {"l1": eid}

        # t=100: coverage is surrendered. The durable write fails and is queued.
        real_close = w.close_coverage_epoch
        monkeypatch.setattr(w, "close_coverage_epoch", _failing_close)
        _close_coverage_epoch_tracked(w, epoch_state, "l1", reason="active_contract_changed")
        assert _pending_ids(epoch_state, "l1") == {eid}, "the close must be queued, not lost"

        # A long durable-write outage. The subscription is ALREADY gone for all of it.
        clock["t"] = 400.0
        monkeypatch.setattr(w, "close_coverage_epoch", real_close)
        _retry_pending_epoch_closes(w, epoch_state, "l1", reason="retry_pending_close")
        assert _pending_ids(epoch_state, "l1") == set(), "the retry must have landed"

        con = sqlite3.connect(db)
        try:
            ended = con.execute(
                "SELECT ended_ts FROM stream_coverage_epochs WHERE id=?", (eid,)).fetchone()[0]
        finally:
            con.close()

        assert ended == 100.0, (
            f"ended_ts must be the SURRENDER instant (100.0), not the retry instant "
            f"(400.0); got {ended}. Anything later claims coverage across the outage.")
        assert ended < 400.0, "a 300s over-claim across a known-unsubscribed window"
    finally:
        w.close()


def test_surrender_time_survives_repeated_failed_retries(tmp_path, monkeypatch):
    """The surrender instant is captured ONCE and must not be refreshed by each failed
    retry -- otherwise a long outage with per-tick retries walks ended_ts forward one
    tick at a time and arrives at the same over-claim by increments."""
    clock = {"t": 100.0}
    monkeypatch.setattr(rsc.time, "time", lambda: clock["t"])

    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        eid = w.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS",
                                    reason="active_contract_set", ts=1.0)
        epoch_state = {"l1": eid}
        real_close = w.close_coverage_epoch
        monkeypatch.setattr(w, "close_coverage_epoch", _failing_close)
        _close_coverage_epoch_tracked(w, epoch_state, "l1", reason="active_contract_changed")

        for t in (150.0, 200.0, 250.0, 300.0):      # four failed retry ticks
            clock["t"] = t
            _retry_pending_epoch_closes(w, epoch_state, "l1", reason="retry_pending_close")
            assert _pending_ids(epoch_state, "l1") == {eid}

        clock["t"] = 350.0
        monkeypatch.setattr(w, "close_coverage_epoch", real_close)
        _retry_pending_epoch_closes(w, epoch_state, "l1", reason="retry_pending_close")

        con = sqlite3.connect(db)
        try:
            ended = con.execute(
                "SELECT ended_ts FROM stream_coverage_epochs WHERE id=?", (eid,)).fetchone()[0]
        finally:
            con.close()
        assert ended == 100.0, (
            f"the original surrender instant must survive every retry; got {ended}")
    finally:
        w.close()


def test_case_C_escalation_cannot_fabricate_a_new_epoch_if_the_signal_flips_back(
        tmp_path, monkeypatch):
    """CASE C aftermath: a later tick must NOT re-open an epoch for the symbol whose
    vendor state is unconfirmed.

    CASE C raises, so `contract_state["l1"] = await _reconcile_option_service(...)` never
    assigns and the dict keeps naming A -- while epoch_state["l1"] is already None (the
    durable close DID succeed; it was the vendor unsubscribe that failed). The poll loop
    catches OptionCoverageCompensationError, sets request_recycle and KEEPS TICKING; the
    main loop only services the recycle on its own slower cadence.

    If the operator's signal flips back to A inside that window, `held == requested`, the
    whole transition block is skipped, and the bottom block sees "held with no epoch" and
    opens a NEW epoch for A -- asserting coverage from now on for a subscription whose
    vendor state is explicitly unknown (the failed unsub may well have landed). That is a
    fabricated claim, and it is the precise thing CASE C exists to refuse: never create a
    new A epoch on the assumption that the old steady state survived."""
    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        write_active_option_contract_signal(_QQQ_CONTRACT)
        contract_state = {"l1": _SPY_CONTRACT, "book": None}
        eid = w.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS",
                                    reason="active_contract_set", ts=1.0)
        epoch_state = {"l1": eid, "book": None}
        stream = _FlakyOptionStream(fail_calls={"l1_option_unsub"})

        with pytest.raises(rsc.OptionCoverageCompensationError):
            asyncio.run(_apply_active_option_contract_subs(
                stream, contract_state, writer=w, epoch_state=epoch_state))

        # The state CASE C leaves behind, measured rather than assumed.
        assert contract_state["l1"] == _SPY_CONTRACT, "stale vendor-held name is retained"
        assert epoch_state["l1"] is None, "the durable close succeeded"
        assert _one_service_open(db) == [], "no open epoch: the claim was surrendered"

        # ── Now the SAME sequence through the real poll loop, which is where the
        # aftermath actually plays out: the loop catches the escalation, requests a
        # recycle, and keeps ticking until the main loop services it.
        write_active_option_contract_signal(_QQQ_CONTRACT)
        contract_state = {"l1": _SPY_CONTRACT, "book": None}
        eid2 = w.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS",
                                     reason="active_contract_set", ts=1.0)
        epoch_state = {"l1": eid2, "book": None}
        live = _FlakyOptionStream(fail_calls={"l1_option_unsub"})

        async def go():
            stop = asyncio.Event()
            recycle = asyncio.Event()
            ticks = {"n": 0}

            def get_stream():
                ticks["n"] += 1
                if ticks["n"] == 2:
                    # Between ticks the operator flips the signal back to A. The recycle
                    # has been requested but NOT yet serviced: same stream object.
                    write_active_option_contract_signal(_SPY_CONTRACT)
                if ticks["n"] >= 6:
                    stop.set()
                return live

            await _active_option_contract_poll_loop(
                get_stream, lambda: contract_state,
                lambda c: contract_state.update(c),
                stop, w, epoch_state, interval_sec=0.001, request_recycle=recycle)
            return recycle.is_set()

        assert asyncio.run(go()) is True, "the escalation must have requested a recycle"

        open_rows = _one_service_open(db)
        assert open_rows == [], (
            "a new epoch was fabricated for a contract whose vendor state is UNCONFIRMED "
            f"-- open rows: {open_rows}. Coverage may only be claimed after a confirmed "
            "subscribe, never inferred from a stale held-name that survived an escalation.")
        assert live.calls == [("l1_option_unsub", (_SPY_CONTRACT,))], (
            "exactly the one failed unsub: no vendor op may be issued on a stream already "
            f"declared unusable; got {live.calls}")
    finally:
        w.close()
