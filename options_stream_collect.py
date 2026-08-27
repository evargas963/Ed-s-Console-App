"""Raw options collection, owned by the CAPTURE DAEMON — the single streaming Collect authority.

WHY THIS MODULE EXISTS. Raw options collection was first built into order_flow_streaming.py,
which drives the UI's Schwab stream in the server process. But the repo already defines ONE
streaming Collect authority: tools/run_stream_capture.py (the CR-01 capture daemon), which owns
the only Schwab stream and writes only stream_capture.db. Putting options Collect on the UI
socket created a SECOND stream surface with its own key accounting, its own persistence
lifecycle, and its own coverage epochs — exactly the competing-ownership blast area Cursor
flagged.

So the options Collect subsystem lives HERE and is driven by the DAEMON. order_flow_streaming
returns to being purely observational (live quotes for the UI, persisting nothing). The
functions are the same ones proven under test — the move preserves every truthfulness property
(per-service subscription truth, the key-budget cap against actual held keys, SUBS-establishes /
ADD-extends, roster fail-closed, intersection-based fully-observed coverage) — with two
couplings re-homed off the UI:

  * the KEY BUDGET is derived from the DAEMON's equity load (its symbol count and the number of
    equity services it runs — two: LEVELONE_EQUITIES + CHART_EQUITY — not the UI's three), so
    options can never crowd out the stream the daemon actually holds.
  * the vendor-call lock is this module's OWN asyncio.Lock, serialising a rotation slice against
    the daemon's start/re-establish (a watchdog recycle). There is no UI ticker switch here to
    interleave with.

Options stay OUTSIDE Decide: this writes raw frames to stream_capture.db and nothing else reads
them into the money path. Collection is OFF unless ED_OPTIONS_STREAM is explicitly set.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

ED_OPTIONS_STREAM_ENV = "ED_OPTIONS_STREAM"

#: SUBSCRIPTION TRUTH, PER SERVICE. LEVELONE_OPTIONS and OPTIONS_BOOK are separate vendor
#: services that succeed and fail independently — subscribe_options returns a receipt with a
#: slot for each and reports partial success as the normal case. One service-agnostic list
#: could not represent that: a contract whose LEVELONE_OPTIONS was accepted and whose
#: OPTIONS_BOOK was refused was recorded as "subscribed", so the refused service was never in
#: the next slice's add-set and was never retried, while the coverage record showed one epoch
#: open and the other absent with nothing to reconcile them.
OPTIONS_SERVICES: tuple[str, ...] = ("LEVELONE_OPTIONS", "OPTIONS_BOOK")

#: PERSISTENCE RIDES THE DAEMON'S ONE WRITER. Options frames are PUBLISHED onto the daemon's
#: MessageBus and persisted by the SAME CaptureWriter connection that writes the equity capture —
#: never a second sqlite connection to stream_capture.db. Two connections to one WAL file was the
#: "competing writers" defect that silently lost equity rows to lock contention. So there is no
#: OptionsFrameIngest in the live path: the frame handler is an O(1) bus publish, and the writer's
#: registered option persister (make_capture_topic_writer) does the insert on the shared connection.
_options_bus: Any = None
#: The stream client options are collecting on, held so a CLEAN teardown can UNSUBSCRIBE the vendor
#: (release keys) rather than only dropping local state and leaking the subscription until logout.
_active_stream: Any = None
#: DROP ACCOUNTING, without a cross-thread counter. `_options_offered` is incremented by the frame
#: handler ON THE EVENT LOOP. The frames WRITTEN are counted by the single CaptureWriter itself
#: (writer.option_rows), on its worker thread, and read ONCE at daemon shutdown AFTER the writer is
#: joined — so no per-frame counter is mutated across the worker/loop boundary and no reset races a
#: live writer. offered and the writer's option_rows span the whole daemon run (reset once at
#: start, flushed once at shutdown); a recycle does NOT touch them.
_options_offered: int = 0
_options_started_ms: int = 0
#: OWED COVERAGE CLOSES, per service: {symbol: ended_ms}. When a Phase-2 close write FAILS, the
#: epoch stays open and we remember the instant it SHOULD have ended. The next slice retries the
#: close AT THAT STORED TIME, and a contract that ROTATES BACK IN is blocked from re-opening
#: coverage until its owed close has landed — so a re-subscribe can never erase an unlanded close
#: and leave one epoch spanning the unsubscribed gap (the "permanent false coverage" defect).
_coverage_close_owed: dict[str, dict[str, int]] = {s: {} for s in OPTIONS_SERVICES}
#: REAL RE-SUBSCRIBE TIME, per service: {symbol: return_ms}. When a contract that still owes a close
#: is re-subscribed at the vendor, we stamp the ACTUAL instant it returned. When its owed close
#: finally lands (a later slice), the fresh epoch is opened at THAT return time, not at the slice
#: the close happened to land — so the two epochs are [.., drop] and [return, ..] with no fabricated
#: NOT_SUBSCRIBED gap between the real return and the (possibly delayed) re-open. Cleared when the
#: fresh epoch opens, or when the contract is dropped again before it could.
_coverage_reopen_at: dict[str, dict[str, int]] = {s: {} for s in OPTIONS_SERVICES}
#: TWO STATES THAT ARE ALLOWED TO DIVERGE, tracked separately because they are different facts and
#: a single set could only ever be right about one of them:
#:   _vendor_held  — what the VENDOR has subscribed. This is the KEY-ACCOUNTING truth (each held
#:                   symbol×service consumes one Schwab key), and it only ever moves on an
#:                   acknowledged vendor subscribe/unsubscribe. It says nothing about persistence.
#:   _coverage_open— what has a DURABLE open coverage epoch. This is the RECORD truth that replay
#:                   and explain_absence read, and it only ever moves on a confirmed sqlite write.
#: They agree on the happy path. They diverge exactly when a coverage write fails after the vendor
#: call succeeded: the vendor holds the key but the epoch did not open (or close). Fusing them —
#: the prior _options_subscribed — forced a choice on every sqlite failure that corrupted whichever
#: fact it did not track: advance and the key count is right but the record claims coverage it never
#: wrote; hold back and the record is right but the key budget under/over-counts. Kept apart, each
#: is authoritative for its own question, and coverage is reconciled TOWARD vendor state (never
#: toward the wish-list) with its own retry, so a failed write self-heals on the next slice.
_vendor_held: dict[str, set[str]] = {s: set() for s in OPTIONS_SERVICES}
_coverage_open: dict[str, set[str]] = {s: set() for s in OPTIONS_SERVICES}
_options_last_receipt: dict[str, Any] | None = None
#: The last slice this process applied — what rotated in, what rotated out, and when. Without it
#: an operator can see that frames are arriving but not that the ROTATION is advancing, which is
#: the difference between "options collection works" and "the intended architecture is running".
_options_last_slice: dict[str, Any] | None = None
#: The rotation task, on the daemon's event loop. Held so teardown can cancel it; an orphaned
#: rotation would keep subscribing against a client being torn down.
_options_rotation_task: Any = None

#: The daemon's equity load, set by start_options_collection. The budget is derived from these so
#: options are sized against the stream that is ACTUALLY held, not a hardcoded topology.
_equity_symbols: int = 1
_equity_key_services: int = 2
_book_enabled: bool = True
#: This module's OWN lock, serialising vendor calls (a rotation slice vs a daemon re-establish).
_options_lock: Any = None


def options_streaming_enabled() -> bool:
    """True only when the operator has explicitly turned options collection on."""
    import os
    return str(os.environ.get(ED_OPTIONS_STREAM_ENV, "")).strip().lower() in ("1", "true", "yes", "on")


#: LEVELONE_OPTIONS rides the 'optionchain' topic KIND, OPTIONS_BOOK the 'optionbook' kind. The
#: kind is what the CaptureWriter dispatches on; the service travels inside the message so the one
#: persister can shape either row from the vendor's own field names.
_TOPIC_KIND = {"LEVELONE_OPTIONS": "optionchain", "OPTIONS_BOOK": "optionbook"}


def _options_frame_handler(service: str) -> Callable[[dict], None]:
    """PUBLISH one options frame onto the daemon's bus and return. O(1), no SQLite on the loop.

    The frame does not touch storage here — it rides the same bus the equity handlers use, and the
    daemon's single CaptureWriter persists it on its own task. Failure containment is DRIVEN: the
    handler closes over module globals only, so a test can point the bus at a raising fake and
    confirm nothing escapes into the shared message loop.
    """
    kind = _TOPIC_KIND.get(service, "optionchain")

    def _handler(msg: dict) -> None:
        global _options_offered
        bus = _options_bus
        if bus is None:
            return
        try:
            key = ""
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list) and content and isinstance(content[0], dict):
                key = str(content[0].get("key") or "")
            _options_offered += 1
            bus.publish(f"{kind}.{key}",
                        {"service": service, "frame": msg,
                         "received_ts_ms": int(time.time() * 1000.0)})
        except Exception as e:                  # noqa: BLE001
            # A publish problem must never propagate into the shared loop that services equities.
            log.debug("options frame publish (%s): %s", service, e)
    return _handler


def make_capture_topic_writer() -> Callable[[Any, str, dict], int]:
    """Build the persister the daemon registers on its CaptureWriter for the option topic kinds.

    fn(conn, topic, msg) -> rows written. It writes options_stream_frames + the per-contract index
    onto the CaptureWriter's OWN connection — the single writer — so options never opens a second
    connection to stream_capture.db. Row shaping is the SHARED shaping from options_stream_frames,
    so this path and any other writer produce byte-identical rows. Schema is ensured lazily on the
    first frame (the writer's connection is the daemon's, created before any option frame arrives).
    """
    from calibration.options_stream_frames import (ensure_options_stream_schema, frame_row_values,
                                                    frame_symbol_rows)
    state = {"schema_ready": False}

    def _write(conn: Any, topic: str, msg: dict) -> int:
        # Runs on the CaptureWriter's WORKER thread. It touches NO module global — the writer counts
        # what it persisted (writer.option_rows), read once at shutdown after the writer is joined.
        if not isinstance(msg, dict):
            return 0
        if not state["schema_ready"]:
            ensure_options_stream_schema(conn)
            state["schema_ready"] = True
        service = msg.get("service")
        frame = msg.get("frame")
        rx = msg.get("received_ts_ms")
        vals = frame_row_values(service, frame, rx)
        if vals is None:
            return 0
        cur = conn.execute(
            "INSERT INTO options_stream_frames (service, frame_ts_ms, received_ts_ms, "
            "ingest_lag_ms, n_contracts, payload_json) VALUES (?,?,?,?,?,?)", vals)
        rows = frame_symbol_rows(cur.lastrowid, frame)
        if rows:
            conn.executemany(
                "INSERT OR REPLACE INTO options_stream_frame_symbols (frame_id, symbol_key, "
                "content_idx) VALUES (?,?,?)", rows)
        return 1
    return _write


def register_options_handlers(sc: Any, make_handler: Callable[[str], Callable[[dict], None]]) -> None:
    """Attach options handlers to the daemon's EXISTING client. Inert until something subscribes.

    Registration is separated from subscription on purpose: a handler with no subscription
    receives nothing, so this is safe to run unconditionally and keeps the enable/disable
    decision in exactly one place (start_options_collection).
    """
    for attr, service in (("add_level_one_option_handler", "LEVELONE_OPTIONS"),
                          ("add_options_book_handler", "OPTIONS_BOOK")):
        fn = getattr(sc, attr, None)
        if fn is None:
            log.warning("stream client has no %s — options %s cannot be collected", attr, service)
            continue
        try:
            fn(make_handler(service))
        except Exception as e:                          # noqa: BLE001
            log.warning("registering %s failed: %s", attr, e)


def options_desired_for_slice(at_epoch_s: float, *, equity_symbols: int,
                              equity_key_services: int = 2,
                              book_enabled: bool = True) -> dict[str, Any]:
    """THE ONE COMPUTATION of "which contracts should be subscribed at this instant".

    Everything downstream — the first subscribe at stream start, every rotation boundary, and
    the diagnostics surface — asks THIS function and reconciles to its answer. A second place
    that decided what to subscribe would be a second coverage authority, and the two would
    disagree the first time either changed.

    CORE underlyings appear in every slice (continuous, money-path); the remaining budget rotates
    deterministically over the rest of the enrolled universe; the budget itself is DERIVED from
    the vendor key limit and the daemon's actual equity load, so options can never crowd out the
    stream the daemon holds. The universe is the ENROLLMENT ROSTER (the sole enrollment authority
    shared by the background logger and ml_scheduler), NOT the freshness-derived chain set, so the
    deterministic cohort really is a pure function of the clock and a governed roster.
    """
    from options_stream_subscription import (
        RotationPolicy, SelectionPolicy, build_chains_for_selection,
        contract_budget_from_key_limit, rotation_cohort, select_contracts, split_budget,
    )

    import dataclasses

    base = RotationPolicy()
    universe: list[str] = []
    roster_ok = False
    roster_error: str | None = None
    try:
        from db import get_db
        universe = sorted(get_db().logging_universe_authoritative_tickers())
        roster_ok = bool(universe)
        if not universe:
            roster_error = "enrollment roster is empty"
    except Exception as e:                              # noqa: BLE001
        roster_error = f"{type(e).__name__}: {e}"

    if not roster_ok:
        # FAIL EXPLICIT, NOT OPEN. The fallback used to be the freshness-derived universe, which
        # reshuffles cohorts as chains age. A plan with no roster carries roster_ok=False and NO
        # symbols, and the reconciler holds the current subscription unchanged rather than
        # reconciling toward a garbage universe (which would UNSUB the current set).
        log.warning("options rotation: enrollment roster unavailable (%s) — holding the current "
                    "subscription unchanged; no deterministic cohort can be computed", roster_error)
        return {
            "at_epoch_s": float(at_epoch_s), "roster_ok": False, "roster_error": roster_error,
            "slice_index": base.slice_index(at_epoch_s), "slice_seconds": base.slice_seconds,
            "core": [], "rotating": [], "non_core_total": 0,
            "full_cycle_slices": 0, "full_cycle_seconds": 0,
            "budget": {}, "split": {}, "useful_depth_contracts": base.useful_depth_contracts,
            "rotating_depth_each": 0, "rotating_per_slice": 0,
            "symbols": [], "per_underlying": {},
            "notes": [f"roster unavailable ({roster_error}) — subscription held unchanged"],
            "policy": base.describe(),
        }

    budget = contract_budget_from_key_limit(
        equity_symbols=max(1, int(equity_symbols)), equity_key_services=equity_key_services,
        book_enabled=book_enabled)

    # THE COHORT SIZE IS DERIVED FROM THE BUDGET. Sizing the cohort first and letting depth fall
    # out of it is how rotating coverage becomes a permanent sliver; depth is the invariant and
    # breadth-per-slice gives way, with the cycle length reported so the gap stays a known
    # quantity.
    n_core = len([c for c in base.core if c in set(universe)])
    provisional = split_budget(budget["contracts_allowed"], n_core, base.rotating_per_slice, base)
    pol = dataclasses.replace(
        base, rotating_per_slice=base.cohort_size_for_budget(provisional["rotating"]))

    cohort = rotation_cohort(universe, at_epoch_s, pol)
    split = split_budget(budget["contracts_allowed"], len(cohort["core"]),
                         len(cohort["rotating"]), pol)

    symbols: list[str] = []
    per_underlying: dict[str, int] = {}
    symbol_underlying: dict[str, str] = {}
    notes: list[str] = []
    # Core and cohort are selected SEPARATELY so a large cohort cannot dilute the core's depth.
    for label, names, ceiling in (("core", cohort["core"], split["core"]),
                                  ("rotating", cohort["rotating"], split["rotating"])):
        if not names or ceiling <= 0:
            continue
        chains = build_chains_for_selection(tickers=names)
        missing = sorted(set(names) - set(chains))
        if missing:
            notes.append(f"{label}: no fresh chain for {missing} — not subscribed this slice")
        sel = select_contracts(chains, SelectionPolicy(max_contracts=int(ceiling)))
        symbols.extend(sel.symbols)
        for k, v in sel.per_underlying.items():
            per_underlying[k] = per_underlying.get(k, 0) + v
        symbol_underlying.update(sel.symbol_underlying)
        notes.extend(f"{label}: {n}" for n in sel.notes)

    return {
        "at_epoch_s": float(at_epoch_s),
        "roster_ok": True,
        "slice_index": cohort["slice_index"],
        "slice_seconds": cohort["slice_seconds"],
        "core": cohort["core"],
        "rotating": cohort["rotating"],
        "non_core_total": cohort["non_core_total"],
        "full_cycle_slices": cohort["full_cycle_slices"],
        "full_cycle_seconds": cohort["full_cycle_seconds"],
        "budget": budget,
        "split": split,
        "useful_depth_contracts": pol.useful_depth_contracts,
        "rotating_depth_each": (split["rotating"] // len(cohort["rotating"])
                                if cohort["rotating"] else 0),
        "rotating_per_slice": pol.rotating_per_slice,
        "symbols": symbols,
        "per_underlying": per_underlying,
        "symbol_underlying": symbol_underlying,
        "notes": notes,
        "policy": cohort["policy"],
    }


async def apply_options_slice(sc: Any, at_epoch_s: float, reason: str) -> dict[str, Any]:
    """Reconcile the live subscription to what this slice should be observing.

    ORDERING IS THE WHOLE POINT: drop then close-epoch (only after the vendor confirms the
    unsubscribe), add then open-epoch (only for services the vendor accepted), so the coverage
    record never claims observability we did not have. Core symbols appear in both the old and
    new set, so they are neither dropped nor re-added — continuous by construction.

    The daemon owns ONE stream. This module's own lock serialises a rotation slice against a
    daemon start / watchdog re-establish so two paths cannot drive the socket at once. The plan
    is computed OUTSIDE the lock (sqlite + arithmetic, no vendor call); only the vendor calls are
    serialised. The key budget is re-derived under the lock from the daemon's equity load.
    """
    global _options_last_receipt, _options_last_slice

    from stream_spine import STREAM_DB_DEFAULT as _CAPTURE_DB
    from calibration.options_stream_coverage import close_epochs, open_epochs
    from options_stream_subscription import (contract_budget_from_key_limit, subscribe_options,
                                             unsubscribe_options)

    # PLANNING OFF THE LOOP. options_desired_for_slice reads the enrollment roster and builds and
    # selects option chains — sqlite + selection work. Run inline on the daemon's event loop it
    # would stall the pump that services equity, book and options frames for the whole duration of
    # the plan (a slow slice becomes a stream stall and dropped frames). Hand it to a worker thread
    # so the loop keeps reading the socket while the slice is computed. The plan is a pure function
    # of (clock, equity load, roster); nothing it touches is loop-affine, and the vendor calls that
    # DO need the loop happen afterwards, under the lock, back on the loop.
    plan = await asyncio.to_thread(
        options_desired_for_slice, at_epoch_s, equity_symbols=_equity_symbols,
        equity_key_services=_equity_key_services, book_enabled=_book_enabled)

    if not plan.get("roster_ok", True):   # caps-ok: options_desired_for_slice ALWAYS sets roster_ok; the True default only covers a hand-built plan (tests), and "proceed" is the normal-case reading
        # ROSTER UNAVAILABLE: hold the current subscription EXACTLY as it is rather than
        # reconciling toward an empty want-set (which would UNSUB continuous core on a transient
        # DB read failure). Recorded so the gap is visible.
        _options_last_slice = {"reason": reason, "at_epoch_s": plan["at_epoch_s"],
                               "slice_index": plan["slice_index"], "roster_ok": False,
                               "added": 0, "dropped": 0,
                               "vendor_held_by_service": {s: len(_vendor_held[s])
                                                          for s in OPTIONS_SERVICES},
                               "notes": plan["notes"][:12]}
        log.warning("options slice held unchanged: %s", plan["notes"][:1])
        return _options_last_slice

    want = list(dict.fromkeys(plan["symbols"]))

    lock = _options_lock
    if lock is None:
        # Outside the daemon loop (tests, or a teardown race) there is no shared socket to
        # protect. A null lock must not silently mean "unsynchronised on a live socket", so the
        # only path that reaches here is one where the daemon is not running.
        import contextlib
        lock = contextlib.AsyncExitStack()

    async with lock:
        # RE-DERIVE UNDER THE LOCK against the daemon's equity load.
        fresh = contract_budget_from_key_limit(
            equity_symbols=_equity_symbols, equity_key_services=_equity_key_services,
            book_enabled=_book_enabled)
        allowed = int(fresh["contracts_allowed"])
        if len(want) > allowed:
            plan["notes"].append(
                f"equity load changed while planning: trimmed {len(want)} -> {allowed} contracts "
                f"to stay inside the key budget")
            want = want[:allowed]

        return await _reconcile_options_subscription(
            sc, plan, want, reason, keys_available=int(fresh["keys_available_for_options"]),
            capture_db=_CAPTURE_DB, close_epochs=close_epochs, open_epochs=open_epochs,
            subscribe_options=subscribe_options, unsubscribe_options=unsubscribe_options)


async def _reconcile_options_subscription(sc, plan, want, reason, *, keys_available,
                                          capture_db, close_epochs, open_epochs,
                                          subscribe_options, unsubscribe_options
                                          ) -> dict[str, Any]:
    """Two independent reconciliations, in this order and never fused:

      PHASE 1 — reconcile the VENDOR to the WANT list. Unsubscribe held-but-unwanted, subscribe
                wanted-but-unheld, per service, capped by the key budget. `_vendor_held` moves ONLY
                on an acknowledged vendor result; it is the key-accounting truth and touches no
                coverage record.

      PHASE 2 — reconcile the durable COVERAGE to the VENDOR state (not to the want list). Open an
                epoch for everything vendor-held-without-one, close the epoch for everything with
                one the vendor no longer holds. `_coverage_open` moves ONLY on a confirmed sqlite
                write.

    Because the two states are separate, a coverage write that fails after the vendor call
    succeeded leaves `_vendor_held` correct (the key IS consumed) and `_coverage_open` behind; the
    NEXT slice's Phase 2 retries the write from the durable delta, so it self-heals without ever
    letting the key count and the record corrupt each other.
    """
    global _options_last_receipt, _options_last_slice
    from calibration.options_stream_coverage import CoverageWriteError
    _CAPTURE_DB = capture_db
    want_set = set(want)
    now_ms = int(time.time() * 1000.0)

    # ══ PHASE 1: VENDOR ⇐ WANT ═══════════════════════════════════════════════════════════════
    # DROP: unsubscribe held-but-unwanted; _vendor_held retreats ONLY on an acknowledged release.
    to_drop = sorted({s for svc in OPTIONS_SERVICES for s in _vendor_held[svc]} - want_set)
    if to_drop:
        receipt = await unsubscribe_options(sc, to_drop)
        for service, key in (("LEVELONE_OPTIONS", "level_one"), ("OPTIONS_BOOK", "book")):
            held = [s for s in to_drop if s in _vendor_held[service]]
            if not held:
                continue
            if receipt.get(key):
                _vendor_held[service] -= set(held)
                # A dropped contract's pending re-subscribe time is moot — clear it so a stale
                # return can never later stamp a fresh epoch the contract no longer warrants.
                for s in held:
                    _coverage_reopen_at[service].pop(s, None)
            else:
                plan["notes"].append(
                    f"{service}: unsubscribe NOT acknowledged for {len(held)} contract(s) — key "
                    f"still held, will retry; errors={receipt.get('errors')}")
                log.warning("options %s: unsubscribe not acknowledged for %d contracts; key stays "
                            "accounted for", service, len(held))

    # KEY-BUDGET CAP, against ACTUAL post-drop vendor-held keys (incl. any the vendor refused to
    # release). want is CORE-FIRST, so core is funded before any rotating name.
    held_keys = sum(len(_vendor_held[svc]) for svc in OPTIONS_SERVICES)
    projected = held_keys
    affordable: set[str] = set()
    for s in want:
        cost = sum(1 for svc in OPTIONS_SERVICES if s not in _vendor_held[svc])
        if cost == 0:
            affordable.add(s)
            continue
        if projected + cost <= keys_available:
            affordable.add(s)
            projected += cost
    if len(affordable) < len(want):
        plan["notes"].append(
            f"key budget: {held_keys}/{keys_available} keys already held (incl. undroppable "
            f"contracts); admitted {len(affordable)}/{len(want)} wanted contracts to stay under "
            f"the limit and protect the equity stream")
        log.warning("options key budget: %d/%d held, admitting %d/%d wanted contracts",
                    held_keys, keys_available, len(affordable), len(want))

    # ADD: subscribe wanted-but-unheld; _vendor_held advances ONLY on an acknowledged subscribe.
    for service, key in (("LEVELONE_OPTIONS", "level_one"), ("OPTIONS_BOOK", "book")):
        missing = [s for s in want if s in affordable and s not in _vendor_held[service]]
        if not missing:
            continue
        # SUBS ESTABLISHES (replaces the service's whole key list), ADD EXTENDS. An empty held set
        # means establish/re-establish; a non-empty set means extend.
        operation = "subs" if not _vendor_held[service] else "add"
        receipt = await subscribe_options(
            sc, missing, level_one=(service == "LEVELONE_OPTIONS"),
            book=(service == "OPTIONS_BOOK"), operation=operation)
        _options_last_receipt = receipt
        if receipt.get(key):
            _vendor_held[service] |= set(missing)
            # If a contract that still OWES a close is re-subscribed, stamp the ACTUAL return time
            # now (first return only), so when its owed close finally lands its fresh epoch opens
            # here, not at the later slice — no fabricated gap between the real return and re-open.
            for s in missing:
                if s in _coverage_close_owed[service] and s not in _coverage_reopen_at[service]:
                    _coverage_reopen_at[service][s] = now_ms
        else:
            plan["notes"].append(
                f"{service}: subscribe REFUSED for {len(missing)} contract(s) — will retry next "
                f"slice; errors={receipt.get('errors')}")
            log.warning("options %s: subscribe refused for %d contracts; will retry",
                        service, len(missing))

    # ══ PHASE 2: COVERAGE ⇐ VENDOR (durable record; OFF the loop; owed-close aware) ══════════════
    # The record tracks what the vendor actually holds. Every durable write runs OFF the event loop
    # (asyncio.to_thread) so a WAL-lock wait cannot stall the pump that services equity/option
    # receive — the coverage writes were the half of the crowd-out the frame writer alone did not
    # fix. A close that FAILS is REMEMBERED in _coverage_close_owed at the instant it should have
    # ended and retried at THAT time; a contract that rotates back in is not re-opened until its
    # owed close has landed, so one epoch can never be stretched across an unsubscribed gap.
    per_service: dict[str, dict[str, int]] = {}
    for service in OPTIONS_SERVICES:
        owed = _coverage_close_owed[service]
        # (a) FRESH DROPS — covered, vendor no longer holds, not already owed. End at now.
        fresh_close = sorted(_coverage_open[service] - _vendor_held[service] - set(owed))
        if fresh_close:
            try:
                await asyncio.to_thread(close_epochs, _CAPTURE_DB, fresh_close,
                                        service=service, reason=reason, at_ms=now_ms)
                _coverage_open[service] -= set(fresh_close)
                per_service.setdefault(service, {})["dropped"] = len(fresh_close)
            except CoverageWriteError as e:
                for s in fresh_close:
                    owed[s] = now_ms     # remember the intended end time; retried in (b)
                plan["notes"].append(
                    f"{service}: coverage close FAILED for {len(fresh_close)} released contract(s) "
                    f"— epoch left open, owed a close at drop time, will retry ({e})")
                log.warning("options %s: coverage close failed for %d contracts; owed at drop time",
                            service, len(fresh_close))
        # (b) OWED CLOSES — retry each at its ORIGINAL end time, so a stale epoch is closed at the
        #     boundary the contract left, never merged forward across the gap.
        for sym in sorted(owed):
            try:
                await asyncio.to_thread(close_epochs, _CAPTURE_DB, [sym],
                                        service=service, reason=reason, at_ms=owed[sym])
                _coverage_open[service].discard(sym)
                del owed[sym]
            except CoverageWriteError:
                pass                     # keep owed at its recorded time; retry next slice
        # (c) OPENS — vendor-held with no current epoch AND no owed close. A contract still owing a
        #     close is withheld until (b) closes its stale epoch, so the fresh epoch starts cleanly
        #     after the gap instead of extending the stale one. A contract that RETURNED while owed
        #     opens at its REAL re-subscribe time (_coverage_reopen_at), even if its owed close only
        #     landed a later slice — so the record ends as two TRUTHFUL epochs, [.., drop] and
        #     [return, ..], with NO fabricated NOT_SUBSCRIBED gap. Contracts with no recorded return
        #     time (fresh subscriptions this slice) open at now.
        reopen = _coverage_reopen_at[service]
        need_open = sorted(_vendor_held[service] - _coverage_open[service] - set(owed))
        at_now = [s for s in need_open if s not in reopen]
        returned = [s for s in need_open if s in reopen]
        opened: list[str] = []
        if at_now:
            try:
                await asyncio.to_thread(open_epochs, _CAPTURE_DB, at_now, service=service,
                                        policy=plan["policy"], reason=reason, at_ms=now_ms)
                opened.extend(at_now)
            except CoverageWriteError as e:
                plan["notes"].append(
                    f"{service}: vendor holds {len(at_now)} contract(s) but coverage open FAILED "
                    f"— record left behind, will retry next slice ({e})")
        for sym in returned:
            try:
                await asyncio.to_thread(open_epochs, _CAPTURE_DB, [sym], service=service,
                                        policy=plan["policy"], reason=reason, at_ms=reopen[sym])
                opened.append(sym)
                del reopen[sym]     # consumed: the fresh epoch now carries the real return time
            except CoverageWriteError:
                pass                # keep the return time; retry the reopen next slice
        if opened:
            _coverage_open[service] |= set(opened)
            per_service.setdefault(service, {})["added"] = len(opened)

    added = sum(v.get("added", 0) for v in per_service.values())  # caps-ok: per_service is built in THIS function; a service with no coverage-open this slice recorded none, so 0 is the true count
    dropped_ok = sum(v.get("dropped", 0) for v in per_service.values())  # caps-ok: per_service is built in THIS function; a service with no coverage-close this slice recorded none, so 0 is the true count

    # PLANNED vs ADMITTED, service-aware. ADMITTED uses the DURABLE coverage (_coverage_open), not
    # vendor state: a contract is only "observed" if its epoch is actually on the record. Fully-
    # observed depth is the INTERSECTION of coverage-open symbols across every service, so different
    # contracts on different services cannot combine into fake full coverage.
    sym_und = dict(plan.get("symbol_underlying") or {})

    def _underlying(sym: str) -> str:
        u = sym_und.get(sym)
        if u:
            return u
        root = sym.split()[0].strip() if isinstance(sym, str) and sym else ""
        return root or "UNKNOWN"

    def _by_underlying(symbols) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in symbols:
            u = _underlying(s)
            out[u] = out.get(u, 0) + 1
        return out

    admitted_by_service = {s: _by_underlying(_coverage_open[s]) for s in OPTIONS_SERVICES}
    covered_all_services = (set.intersection(*(_coverage_open[s] for s in OPTIONS_SERVICES))
                            if OPTIONS_SERVICES else set())
    per_underlying_admitted = {u: c for u, c in _by_underlying(covered_all_services).items() if c > 0}
    admitted_underlyings = set(per_underlying_admitted)
    rotating_admitted = sorted(u for u in plan["rotating"] if u in admitted_underlyings)
    core_admitted = sorted(u for u in plan["core"] if u in admitted_underlyings)
    fully_admitted = all(
        per_underlying_admitted.get(u, 0) >= cnt for u, cnt in plan["per_underlying"].items())

    _options_last_slice = {
        "reason": reason,
        "at_epoch_s": plan["at_epoch_s"],
        "slice_index": plan["slice_index"],
        "core_planned": plan["core"],
        "rotating_planned": plan["rotating"],
        "per_underlying_planned": plan["per_underlying"],
        "core_admitted": core_admitted,
        "rotating_admitted": rotating_admitted,
        "per_underlying_admitted": per_underlying_admitted,
        "admitted_by_service": admitted_by_service,
        "fully_admitted": fully_admitted,
        "added": added,
        "dropped": dropped_ok,
        # KEY accounting (vendor) and RECORD (coverage) are reported separately — when they diverge
        # after a failed write, the divergence is the truth, and the slice makes it visible.
        "vendor_held_by_service": {s: len(_vendor_held[s]) for s in OPTIONS_SERVICES},
        "coverage_open_by_service": {s: len(_coverage_open[s]) for s in OPTIONS_SERVICES},
        "vendor_held_total": len(set().union(*_vendor_held.values())),
        "coverage_matches_vendor": all(_coverage_open[s] == _vendor_held[s]
                                       for s in OPTIONS_SERVICES),
        # Closes owed but not yet landed (a failed close being retried) and returns whose fresh
        # epoch is pending — visible so a lingering divergence is attributable, not mysterious.
        "coverage_close_owed": {s: len(_coverage_close_owed[s]) for s in OPTIONS_SERVICES},
        "coverage_reopen_pending": {s: len(_coverage_reopen_at[s]) for s in OPTIONS_SERVICES},
        "services_in_agreement": len({frozenset(v) for v in _vendor_held.values()}) == 1,
        "full_cycle_seconds": plan["full_cycle_seconds"],
        "notes": plan["notes"][:12],
    }
    log.info("OPTIONS slice %s (%s): +%d -%d epochs; vendor %s; coverage %s; ADMITTED %d/%d "
             "underlyings (fully=%s); core=%s cycle=%ss",
             plan["slice_index"], reason, added, dropped_ok,
             _options_last_slice["vendor_held_by_service"],
             _options_last_slice["coverage_open_by_service"],
             len(per_underlying_admitted), len(plan["per_underlying"]), fully_admitted,
             core_admitted, plan["full_cycle_seconds"])
    return _options_last_slice


async def _options_rotation_loop(sc: Any) -> None:
    """Advance the rotation at each slice boundary, on the daemon's loop and its ONE client.

    A task on the existing loop, cancelled by stop_options_collection — never a thread and never
    a second client. Boundaries are computed from the clock, not a fixed sleep, so a slow slice
    cannot drift from the deterministic slice_index that replay and the coverage record depend on.
    """
    from options_stream_subscription import RotationPolicy

    pol = RotationPolicy()
    while True:
        now = time.time()
        nxt = (pol.slice_index(now) + 1) * float(pol.slice_seconds)
        try:
            await asyncio.sleep(max(1.0, nxt - now))
        except asyncio.CancelledError:
            raise
        try:
            await apply_options_slice(sc, time.time(), reason="rotation")
        except asyncio.CancelledError:
            raise
        except Exception as e:                          # noqa: BLE001
            log.warning("options rotation slice failed (collection continues): %s", e)


def flush_options_ingest_health(capture_db: Any, *, offered: int, written: int,
                                started_ms: int, at_ms: int | None = None) -> None:
    """Record one options_stream_ingest_health window from the live counters.

    offered is counted by the handler as it publishes; written by the persister as it inserts. Any
    shortfall (offered - written) is a DROP — a frame shed by the bounded bus queue under load, the
    same measured hole OptionsFrameIngest recorded, kept durable so SUBSCRIBED_MAYBE_DROPPED stays
    answerable after the process exits. Best-effort: a failed health write must not fail teardown.
    """
    try:
        import sqlite3
        from calibration.options_stream_ingest import ensure_ingest_health_schema
        dropped = max(0, int(offered) - int(written))
        now = int(at_ms if at_ms is not None else time.time() * 1000.0)  # caps-ok: at_ms unspecified means stamp the health window at the current instant (this call's documented default), not a measurement being replaced
        conn = sqlite3.connect(str(capture_db), timeout=30.0)
        try:
            ensure_ingest_health_schema(conn)
            conn.execute(
                "INSERT INTO options_stream_ingest_health (window_start_ms, window_end_ms, "
                "offered, written, dropped, write_errors, max_queue_depth, max_ingest_lag_ms, "
                "batches, write_ms_total) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (int(started_ms or now), now, int(offered), int(written), dropped, 0, 0, None, 0, 0.0))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:                              # noqa: BLE001
        log.debug("options ingest health flush: %s", e)


def reset_options_ingest_counters() -> None:
    """Zero the drop-accounting window ONCE, at daemon start. Called by the daemon before the
    capture loop, NOT by start_options_collection (which re-runs on every watchdog recycle) — so the
    window spans the whole daemon run and lines up with the writer's cumulative option_rows."""
    global _options_offered, _options_started_ms
    _options_offered = 0
    _options_started_ms = int(time.time() * 1000.0)


def options_ingest_window() -> tuple[int, int]:
    """(offered, window_start_ms) for the daemon's single shutdown health flush. Read on the loop
    AFTER the writer is joined, so it never races the worker. `written` is NOT here — it is the
    writer's own count (writer.option_rows), the authority for frames actually persisted."""
    return _options_offered, _options_started_ms


async def start_options_collection(sc: Any, *, bus: Any, equity_symbols: int,
                                   equity_key_services: int = 2, book_enabled: bool = True) -> None:
    """Reconcile any orphaned coverage, wire the bus, subscribe slice zero, run the rotation.

    Called by the capture daemon after it has subscribed its equity services on the ONE stream and
    registered the option persister on its single CaptureWriter. `bus` is that daemon's MessageBus:
    option frames publish onto it and are persisted by the shared writer — no second connection.
    Every failure path is soft: options collection is additive and must never disturb the daemon's
    equity/book capture. `equity_symbols`/`equity_key_services` describe the DAEMON's equity load so
    the options budget is sized against the stream that is actually held.
    """
    global _options_bus, _active_stream, _options_rotation_task
    global _equity_symbols, _equity_key_services, _book_enabled, _options_lock

    _equity_symbols = max(1, int(equity_symbols))
    _equity_key_services = max(1, int(equity_key_services))
    _book_enabled = bool(book_enabled)
    _options_bus = bus
    _active_stream = sc
    if _options_lock is None:
        _options_lock = asyncio.Lock()

    if not options_streaming_enabled():
        log.info("options streaming disabled (%s unset) — LEVELONE_OPTIONS/OPTIONS_BOOK handlers "
                 "registered but nothing subscribed", ED_OPTIONS_STREAM_ENV)
        return
    try:
        # RC-6 law: raw stream capture goes to stream_capture.db, NEVER ed_console.db.
        from stream_spine import STREAM_DB_DEFAULT as _CAPTURE_DB
        from calibration.options_stream_coverage import reconcile_open_epochs_on_start
    except Exception as e:                              # noqa: BLE001
        log.warning("options collection unavailable: %s", e)
        return

    try:
        # RESTART COVERAGE TRUTH: close any epoch left open by a prior UNCLEAN exit at its LAST
        # PROVEN LIVENESS (never `now`), so the record never claims observation across the downtime
        # gap. Runs before any new epoch opens. (Counters are reset once by the daemon, not here, so
        # a watchdog recycle re-entering start does not zero the writer's cumulative accounting.)
        closed = reconcile_open_epochs_on_start(_CAPTURE_DB, services=OPTIONS_SERVICES)
        if any(closed.values()):
            log.warning("options coverage: closed orphaned epochs from an unclean prior exit: %s",
                        closed)

        # Slice zero runs through the SAME reconciler every boundary uses, so start-up and steady
        # state cannot drift apart. Frames only arrive after this subscribe, so the bus is wired
        # (above) before anything can be published.
        await apply_options_slice(sc, time.time(), reason="stream_start")
        if not any(_vendor_held.values()):
            log.warning("options collection: slice produced no contracts — nothing subscribed "
                        "(a COVERAGE GAP, not a market observation); tearing down cleanly")
            await stop_options_collection("start_no_contracts", unsubscribe=True)
            return

        _options_rotation_task = asyncio.create_task(
            _options_rotation_loop(sc), name="options_rotation")
    except Exception as e:                              # noqa: BLE001
        log.warning("options collection failed to start (equity stream unaffected): %s", e)
        try:
            # A start that subscribed part of a set before raising leaves keys held on the live
            # socket; unsubscribe them so they are not leaked until logout.
            await stop_options_collection("start_failed", unsubscribe=True)
        except Exception as e2:                         # noqa: BLE001
            log.warning("options collection: cleanup after failed start: %s", e2)


async def quiesce_options_collection(reason: str = "quiesce", *, unsubscribe: bool = False,
                                     timeout_s: float = 10.0) -> None:
    """PHASE ONE of teardown: stop DRIVING the stream. Cancels+awaits the rotation and unsubscribes.

    This runs BEFORE the daemon quiesces its Schwab pump. After it returns nothing will DRIVE the
    socket (the rotation task is gone) and, on a clean stop, the vendor has been told to stop
    sending (unsubscribe). It deliberately does NOT close coverage epochs: frames unsubscribed here
    may still be in flight through the pump and writer, so the record must stay open until the pump
    is quiesced and the writer drained. `close_options_coverage` does that, afterwards.
    """
    global _options_rotation_task, _options_last_slice

    task, _options_rotation_task = _options_rotation_task, None
    if task is not None:
        # ACQUIRE THE RECONCILE LOCK BEFORE CANCELLING, bounded. A slice holds _options_lock while
        # it drives the vendor AND its OFF-LOOP coverage writes (await asyncio.to_thread). If we
        # cancelled the task mid-slice, the CancelledError would land on the to_thread await AFTER
        # the worker already committed the durable epoch but BEFORE the in-memory _coverage_open
        # update — the same "cancelled between the durable write and the memory update" split the
        # frame writer avoids by being awaited, not cancelled. Taking the lock first makes the
        # cancel land on the inter-slice sleep instead, so every slice's write+memory update is
        # atomic. If a slice is wedged (a hung vendor call), fall back to cancelling after the
        # timeout — the teardown reconcile in close_options_coverage still closes any orphan epoch.
        lock = _options_lock
        acquired = False
        if lock is not None:
            try:
                await asyncio.wait_for(lock.acquire(), timeout=timeout_s)
                acquired = True
            except Exception as e:                      # noqa: BLE001
                log.warning("quiesce: reconcile lock not acquired in %.1fs (%s) — cancelling "
                            "anyway; teardown reconcile will close any orphan", timeout_s, e)
        try:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:                      # noqa: BLE001
                log.warning("awaiting cancelled options rotation: %s", e)
        finally:
            if acquired:
                lock.release()
    _options_last_slice = None

    sc = _active_stream
    if unsubscribe and sc is not None:
        held = sorted(set().union(*_vendor_held.values())) if _vendor_held else []
        if held:
            try:
                from options_stream_subscription import unsubscribe_options
                await asyncio.wait_for(unsubscribe_options(sc, held), timeout=timeout_s)
                # The vendor released these keys; reflect it so key accounting stays truthful even
                # if the process lingers. Coverage stays open until close_options_coverage.
                for svc in OPTIONS_SERVICES:
                    _vendor_held[svc] -= set(held)
            except Exception as e:                      # noqa: BLE001
                # A dead/half-open socket (a recycle) or a slow vendor must not hang or fail
                # teardown — the epoch close still records that observation ended.
                log.warning("options unsubscribe on teardown (%s): %s", reason, e)


def close_options_coverage(reason: str = "stream_stop") -> None:
    """PHASE TWO of teardown: close the coverage record and reset the collection state.

    Runs AFTER the daemon has quiesced the Schwab pump and drained the writer (clean shutdown) or
    after the old pump was cancelled (a watchdog recycle), so no further option frame can arrive.

    Epochs are closed at the LAST PROVEN LIVENESS, FLOORED per-epoch to their own start: on a
    recycle the socket has been dead ~90s, and closing at `now` would fold that dead-socket window
    into coverage — the same "silence as observation" error the crash reconcile avoids. Any close
    still OWED from a failed write is honoured FIRST at its ORIGINAL end time; then EVERY remaining
    open epoch IN THE DB is closed via the same crash-reconcile path (`reconcile_open_epochs_on_start`),
    which floors per-epoch (ended is always in [started, cap], never a malformed negative-width row)
    AND closes any epoch a torn-down slice may have committed to the db without recording in memory —
    so nothing is left open to read as false coverage until the next start. This does NOT flush
    ingest health or touch the drop counters — those span the whole daemon run and are flushed ONCE
    at daemon shutdown, after the writer is joined (a recycle must not reset a live writer's counters).
    """
    global _vendor_held, _coverage_open, _coverage_close_owed, _coverage_reopen_at
    global _options_bus, _active_stream

    from stream_spine import STREAM_DB_DEFAULT as _CAPTURE_DB
    try:
        from calibration.options_stream_coverage import (close_epochs, open_epochs,
                                                         reconcile_open_epochs_on_start)
        # 1. Honour owed closes at THEIR recorded end time (a failed close being retried), so an
        #    interrupted contract ends at the boundary it left, not at teardown.
        for service in OPTIONS_SERVICES:
            for sym, at in list(_coverage_close_owed[service].items()):
                try:
                    close_epochs(_CAPTURE_DB, [sym], service=service, reason=reason, at_ms=at)
                except Exception as e:                  # noqa: BLE001
                    log.warning("teardown owed-close (%s %s): %s", service, sym, e)
        # 2. Record any pending RETURN: a contract that re-subscribed while owed but whose fresh
        #    epoch never opened (the owed close kept failing) gets its fresh epoch opened at the REAL
        #    return time now, so the return window is on the record. The reconcile below then closes
        #    it at liveness. open_epochs is idempotent, so a contract whose stale epoch is still open
        #    is skipped rather than double-opened.
        for service in OPTIONS_SERVICES:
            for sym, at in list(_coverage_reopen_at[service].items()):
                if sym not in _coverage_open[service]:
                    try:
                        open_epochs(_CAPTURE_DB, [sym], service=service, reason=reason, at_ms=at)
                    except Exception as e:              # noqa: BLE001
                        log.warning("teardown reopen (%s %s): %s", service, sym, e)
        # 3. Close EVERY remaining open epoch at last proven liveness, floored per-epoch — the SAME
        #    path (and truthfulness) the crash reconcile uses. Reads the db, so it closes even an
        #    epoch that a cancelled slice committed but never recorded in _coverage_open.
        reconcile_open_epochs_on_start(_CAPTURE_DB, services=OPTIONS_SERVICES, reason=reason)
    except Exception as e:                              # noqa: BLE001
        log.warning("close_options_coverage: %s", e)
    finally:
        _vendor_held = {s: set() for s in OPTIONS_SERVICES}
        _coverage_open = {s: set() for s in OPTIONS_SERVICES}
        _coverage_close_owed = {s: {} for s in OPTIONS_SERVICES}
        _coverage_reopen_at = {s: {} for s in OPTIONS_SERVICES}
        _options_bus = None
        _active_stream = None


async def stop_options_collection(reason: str = "stream_stop", *, unsubscribe: bool = False,
                                  timeout_s: float = 10.0) -> None:
    """Combined teardown for paths where the pump is ALREADY quiesced (a recycle rebuilds the
    socket; a failed start never began pumping). Quiesce then immediately close coverage.

    The DAEMON SHUTDOWN path does NOT use this: there the pump is still live, so it calls
    quiesce_options_collection first, quiesces its pump and drains the writer, and only THEN calls
    close_options_coverage — so a frame in flight cannot arrive after the epoch is closed.
    """
    await quiesce_options_collection(reason, unsubscribe=unsubscribe, timeout_s=timeout_s)
    close_options_coverage(reason)


def options_stream_status() -> dict[str, Any]:
    """Live options-collection health, for the daemon's diagnostics surface."""
    out: dict[str, Any] = {
        "enabled": options_streaming_enabled(),
        # KEY accounting (what the vendor holds) and RECORD (what has a durable epoch) are reported
        # separately; when they diverge after a failed coverage write, the gap is the truth.
        "vendor_held_by_service": {s: len(_vendor_held[s]) for s in OPTIONS_SERVICES},
        "coverage_open_by_service": {s: len(_coverage_open[s]) for s in OPTIONS_SERVICES},
        "subscribed_contracts": len(set().union(*_vendor_held.values()) if _vendor_held else set()),
        "coverage_matches_vendor": all(_coverage_open[s] == _vendor_held[s]
                                       for s in OPTIONS_SERVICES),
        "coverage_close_owed": {s: len(_coverage_close_owed[s]) for s in OPTIONS_SERVICES},
        "coverage_reopen_pending": {s: len(_coverage_reopen_at[s]) for s in OPTIONS_SERVICES},
        "services_in_agreement": len({frozenset(v) for v in _vendor_held.values()}) == 1,
        "last_receipt": _options_last_receipt,
        "last_slice": _options_last_slice,
        "rotation_running": bool(_options_rotation_task is not None
                                 and not _options_rotation_task.done()),
        # PERSISTENCE rides the daemon's single CaptureWriter. `offered` is this process's loop-side
        # publish count; the frames actually WRITTEN are the writer's own count (writer.option_rows),
        # and the durable drop accounting lives in the options_stream_ingest_health table (flushed
        # once at daemon shutdown). Read in the server process, `offered` is 0 — collection is the
        # daemon's; use the health table for the authoritative window.
        "persistence": "daemon_capture_writer",
        "ingest": {"offered": _options_offered},
    }
    return out
