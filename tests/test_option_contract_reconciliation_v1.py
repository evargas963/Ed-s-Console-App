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

import pytest

from stream_spine import (
    CaptureWriter,
    CoverageWriteError,
    read_active_option_contract_signal,
    write_active_option_contract_signal,
)
from tools.run_stream_capture import (
    _apply_active_option_contract_subs,
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
        assert epoch_state.get("l1_pending_close") == set()
        assert epoch_state.get("book_pending_close") == set()
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
    assert epoch_state.get("l1_pending_close") == {1}
    assert epoch_state.get("book_pending_close") == {2}
    assert all(r[2] is None for r in _epochs(tmp_path / "cap.db")), (
        "a failed close must leave the epoch genuinely OPEN, never fabricate an end")

    fail_toggle["on"] = False   # the durable-write outage recovers
    _retry_pending_epoch_closes(writer, epoch_state, "l1", reason="retry_pending_close")
    _retry_pending_epoch_closes(writer, epoch_state, "book", reason="retry_pending_close")

    assert epoch_state.get("l1_pending_close") == set()
    assert epoch_state.get("book_pending_close") == set()
    old_rows = [r for r in _epochs(tmp_path / "cap.db") if r[0] == _SPY_CONTRACT]
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
    assert epoch_state.get("l1_pending_close") == set(), (
        "the restored epoch must not stay queued for closing (it is legitimately open)")
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
        assert epoch_state.get("l1_pending_close") == {first_id}
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
        assert epoch_state.get("l1_pending_close") == set()
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


def test_coverage_A_close_failure_restores_prior_subscription(tmp_path, monkeypatch):
    """1G-A. UNSUB A ok -> CLOSE A fails -> compensating RESUB A succeeds.
    Vendor held = A, exactly one open epoch = A, B never subscribed, no B epoch."""
    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        eid = w.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS",
                                    reason="active_contract_set", ts=1.0)
        epoch_state = {"l1": eid}
        monkeypatch.setattr(w, "close_coverage_epoch", _failing_close)
        stream = _FlakyOptionStream()

        held = _switch_tick(stream, w, epoch_state, _SPY_CONTRACT, _QQQ_CONTRACT)

        assert held == _SPY_CONTRACT, "the prior subscription must be restored, not dropped"
        assert stream.calls == [("l1_option_unsub", (_SPY_CONTRACT,)),
                                ("l1_option_sub", (_SPY_CONTRACT,))], (
            f"B must never be subscribed while A's epoch is still open; got {stream.calls}")
        rows = _one_service_open(db)
        assert len(rows) == 1 and rows[0][1] == _SPY_CONTRACT, (
            f"exactly one open epoch, on A; got {rows}")
        assert epoch_state["l1"] == eid, "A's epoch id is the current epoch again"
    finally:
        w.close()


def test_coverage_B_close_and_resubscribe_both_fail_escalates(tmp_path, monkeypatch):
    """1G-B. CLOSE A fails AND the compensating RESUB A also fails -> vendor state is
    uncertain while A's epoch is still open. No steady-state continuation, no healthy
    claim: it escalates into the same recycle path the subscribe-direction uses."""
    from tools.run_stream_capture import OptionCoverageCompensationError

    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        eid = w.open_coverage_epoch(_SPY_CONTRACT, "LEVELONE_OPTIONS",
                                    reason="active_contract_set", ts=1.0)
        epoch_state = {"l1": eid}
        monkeypatch.setattr(w, "close_coverage_epoch", _failing_close)
        stream = _FlakyOptionStream(fail_calls={"l1_option_sub"})   # resubscribe fails

        with pytest.raises(OptionCoverageCompensationError) as exc:
            _switch_tick(stream, w, epoch_state, _SPY_CONTRACT, _QQQ_CONTRACT)
        msg = str(exc.value)
        assert "close failed" in msg and "compensating resubscribe also failed" in msg
        assert "forcing stream recycle" in msg
        rows = _one_service_open(db)
        assert len(rows) == 1 and rows[0][1] == _SPY_CONTRACT, (
            "no B epoch may have been created on the escalation path")
    finally:
        w.close()


def test_coverage_C_pending_close_retry_cannot_close_a_restored_subscription(tmp_path, monkeypatch):
    """1G-C (defect 1D). After the compensating RESUB restores A, the pending-close retry
    machinery must NOT later close A's epoch behind a live subscription's back."""
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
        assert epoch_state.get("l1_pending_close") == set(), (
            "the restored epoch must not remain queued for closing")

        # The DB recovers; a retry pass now runs with A legitimately subscribed.
        monkeypatch.setattr(w, "close_coverage_epoch", real_close)
        _retry_pending_epoch_closes(w, epoch_state, "l1", reason="retry_pending_close")

        rows = _one_service_open(db)
        assert len(rows) == 1 and rows[0][1] == _SPY_CONTRACT, (
            "the retry must not have closed the epoch of a live, restored subscription")
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
        assert held == _SPY_CONTRACT           # tick 1: restored, transition pending

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
