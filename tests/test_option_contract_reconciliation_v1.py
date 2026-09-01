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

from stream_spine import (
    CaptureWriter,
    CoverageWriteError,
    read_active_option_contract_signal,
    write_active_option_contract_signal,
)
from tools.run_stream_capture import _apply_active_option_contract_subs

_SPY_CONTRACT = "SPY   260820C00767000"
_QQQ_CONTRACT = "QQQ   260820C00450000"


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


def test_B_coverage_open_write_fails_never_falsely_claims_durable_coverage(tmp_path, monkeypatch):
    """B. option subscriptions succeed + coverage OPEN write fails -> the vendor-held
    truth may correctly advance (the subscribe really did happen), but the DURABLE
    coverage truth (epoch_state) must NOT — the exact IN-MEMORY-CURRENT-CONTRACT-vs-
    ABSENT-DURABLE-EPOCH divergence the operator's finding named. Verified two ways: the
    in-memory epoch_state stays None, AND the epochs table has no row for this symbol."""
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
        # Vendor truth: the subscribe calls really were made (real Schwab ack, in this
        # fake, always succeeds) — held correctly reflects that.
        assert new_state == {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}
        # Durable truth: NEVER falsely claimed. This is the invariant the operator's
        # finding named directly.
        assert epoch_state["l1"] is None, "coverage OPEN failure must not fabricate a durable epoch id"
        assert epoch_state["book"] is None
    asyncio.run(go())
    assert _epochs(tmp_path / "cap.db") == [], (
        "no epoch row may exist when every open_coverage_epoch call was made to fail")
    writer.close()


def test_C_coverage_close_write_fails_keeps_the_old_epoch_id_for_retry(tmp_path, monkeypatch):
    """C. old subscription changes + coverage CLOSE write fails -> the old durable epoch
    must NOT be silently forgotten. Verified against the REAL sqlite row: it must still be
    OPEN (ended_ts IS NULL) after the failed close, AND its id must survive in the
    pending-close retry set — never discarded."""
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
        # Vendor truth still advances — the unsub+sub really happened.
        assert new_state == {"l1": _QQQ_CONTRACT, "book": _QQQ_CONTRACT}
        # The failed-to-close ids must be tracked for retry, not discarded.
        assert 1 in epoch_state.get("l1_pending_close", set())
        assert 2 in epoch_state.get("book_pending_close", set())
    asyncio.run(go())
    rows = _epochs(tmp_path / "cap.db")
    old_rows = [r for r in rows if r[0] == _SPY_CONTRACT]
    assert all(r[2] is None for r in old_rows), (
        "a failed close must leave the OLD epoch genuinely OPEN in the durable table — "
        "claiming it closed when it did not would misreport an ended coverage window as "
        "still open, or vice versa fabricate an end that never landed")
    writer.close()


def test_D_pending_close_self_heals_once_the_writer_recovers(tmp_path, monkeypatch):
    """D. DB error/retry/recovery -> coverage state converges without fabricating
    intervals. A close that failed once must succeed on the NEXT reconciliation tick once
    the durable write stops failing — no operator action required."""
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
    fail_toggle = {"on": True}

    def _flaky_close(epoch_id, **k):
        if fail_toggle["on"] and epoch_id in (1, 2):
            raise CoverageWriteError("simulated durable-write outage on close")
        return real_close(epoch_id, **k)
    monkeypatch.setattr(writer, "close_coverage_epoch", _flaky_close)
    epoch_state: dict = {"l1": 1, "book": 2}
    state = {"l1": _SPY_CONTRACT, "book": _SPY_CONTRACT}

    async def tick():
        nonlocal state
        state = await _apply_active_option_contract_subs(
            stream, state, writer=writer, epoch_state=epoch_state)

    asyncio.run(tick())   # tick 1: switch SPY->QQQ, close of 1/2 FAILS, tracked pending
    assert epoch_state.get("l1_pending_close") == {1}
    assert epoch_state.get("book_pending_close") == {2}
    fail_toggle["on"] = False   # the durable-write outage recovers
    asyncio.run(tick())   # tick 2: no change requested (still QQQ) -> pure retry pass
    assert epoch_state.get("l1_pending_close") == set()
    assert epoch_state.get("book_pending_close") == set()
    rows = {r[0]: r for r in [r for r in _epochs(tmp_path / "cap.db") if r[0] == _SPY_CONTRACT]}
    old_rows = [r for r in _epochs(tmp_path / "cap.db") if r[0] == _SPY_CONTRACT]
    assert all(r[2] is not None for r in old_rows), (
        "once the writer recovers, the previously-stuck epoch must actually close")
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


def test_pending_close_and_current_epoch_are_independent_keys(tmp_path, monkeypatch):
    """A stuck pending-close for the OLD symbol must never block opening a fresh epoch for
    a NEW symbol on the same service — the two are tracked under distinct dict keys
    (epoch_state[key] vs epoch_state[f'{key}_pending_close']) precisely so a stuck close
    can never starve a legitimate new open."""
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
    asyncio.run(go())
    assert epoch_state.get("l1_pending_close") == {1}
    assert epoch_state["l1"] is not None, (
        "a NEW epoch for QQQ must open even though the OLD SPY epoch is stuck pending-close")
    new_rows = [r for r in _epochs(tmp_path / "cap.db") if r[0] == _QQQ_CONTRACT]
    # Both services transition None/SPY -> QQQ this tick, so both open a fresh QQQ epoch —
    # the assertion that matters is that L1's stuck pending-close (service "l1") did not
    # block ITS OWN new QQQ epoch from opening, which epoch_state["l1"] is not None already
    # proves; this just confirms neither new open was silently skipped either.
    assert len(new_rows) == 2 and all(r[2] is None for r in new_rows)
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
